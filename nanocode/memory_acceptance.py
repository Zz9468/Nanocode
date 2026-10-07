"""Reproducible real MySQL/Qwen acceptance; uses only isolated test namespaces."""
import json
import math
import sys
import uuid
from pathlib import Path
from nanocode.memory import MemoryManager
from nanocode.memory_backend import BudgetedMemoryModel
from nanocode.agent_loop import run_agent_turn
from nanocode.tooling import ToolRegistry
from nanocode.tools.read_file import read_file_tool

def run(report_name="acceptance.json"):
    if Path(report_name).name != report_name or not report_name.endswith(".json"):
        raise ValueError("acceptance report must be a JSON filename")
    module = Path(__file__).parents[1]/"Package"/"AgentMemory"
    data = module/"Data"/"Test"
    root = data/"Runtime"/("Acceptance_"+uuid.uuid4().hex)
    root.mkdir(parents=True)
    manager = MemoryManager(root, backend="mysql", backend_env={"NANOCODE_MYSQL_DATABASE":"nanocode_memory_test", "NANOCODE_MEMORY_OWNER":root.name})
    service = manager._service
    report = {"schema":"nanocode_memory_test", "owner":root.name, "stages":{}}
    (root/"PROJECT.txt").write_text("本验收项目使用 MySQL 保存长期记忆，代码验证统一执行 pytest。", "utf-8")
    run_agent_turn(model=BudgetedMemoryModel(service, [{"name":"read_file","description":"读取工作区文件","input":{"path":"相对文件路径"}}]),
        tools=ToolRegistry([read_file_tool]), messages=[{"role":"system","content":"先实际读取文件再答复。"},
        {"role":"user","content":"请读取 PROJECT.txt 了解项目约定。我在所有项目都偏好用中文交流，请记住这个偏好。"}],
        cwd=str(root), memory_manager=manager, max_steps=5, enable_work_chain=False)
    service.drain(60)
    service.run_jobs(200, kinds=["extract", "embed"])
    with service.repository.db.transaction() as tx:
        turns=tx.query("SELECT payload FROM memory_turns WHERE namespace_id=%s", (service.namespaces["project"],))
    payload=json.loads(turns[-1]["payload"])
    records=service.list_records()
    stage={"actual_tool_result":any(e.get("role")=="tool_result" and not e.get("isError") for e in payload["events"]),
        "extracted":len(records), "user_preference":any(r.scope=="user" and r.kind=="preference" and "中文" in r.content for r in records),
        "evidence_quotes":all(r.metadata.get("evidence_quotes") for r in records)}
    report["stages"]["agent_turn"]=stage
    assert stage["actual_tool_result"] and stage["user_preference"] and stage["extracted"]>=2 and stage["evidence_quotes"], stage
    print("Actual agent turn, tool evidence, extraction and persistence passed", flush=True)
    # Separate benchmark namespace excludes memories extracted in the prior phase.
    cases=json.loads((data/"retrieval_cases.json").read_text("utf-8"))
    bench_root=root/"Benchmark"
    bench_root.mkdir()
    (bench_root/"cases.json").write_text(json.dumps(cases,ensure_ascii=False,indent=2),"utf-8")
    bench=MemoryManager(bench_root,backend="mysql",backend_env={"NANOCODE_MYSQL_DATABASE":"nanocode_memory_test","NANOCODE_MEMORY_OWNER":root.name+"-benchmark"})._service
    ids={item["key"]:bench.remember(item["content"],kind="fact").id for item in cases["memories"]}
    jobs=bench.run_jobs(200,kinds=["embed"])
    assert not jobs["errors"], jobs["errors"]
    metrics={mode:{"recall3":0,"recall5":0,"mrr":0,"ndcg3":0,"degraded":0} for mode in ("bm25","dense","rrf","hybrid")}
    rows=[]
    for index,case in enumerate(cases["queries"],1):
        relevant={ids[key] for key in case["relevant"]}
        row={"query":case["query"],"relevant":case["relevant"],"ranks":{}}
        for mode in metrics:
            result=bench.retrieve(case["query"],limit=5,mode=mode)
            ranked=[r.id for r in result.records]
            rank=next((i for i,key in enumerate(ranked,1) if key in relevant),None)
            row["ranks"][mode]=rank
            metric=metrics[mode]
            metric["recall3"]+=len(set(ranked[:3]) & relevant)/len(relevant)
            metric["recall5"]+=len(set(ranked[:5]) & relevant)/len(relevant)
            metric["mrr"]+=1/rank if rank else 0
            dcg=sum(1/math.log2(i+1) for i,key in enumerate(ranked[:3],1) if key in relevant)
            ideal=sum(1/math.log2(i+1) for i in range(1,min(3,len(relevant))+1))
            metric["ndcg3"]+=dcg/ideal if ideal else 0
            metric["degraded"]+=int(result.diagnostics.get("degraded",False))
        rows.append(row)
        if index%10==0:
            print(f"Labeled retrieval evaluation: {index}/{len(cases['queries'])}",flush=True)
    for metric in metrics.values():
        for key in ("recall3","recall5","mrr","ndcg3"):
            metric[key]=round(metric[key]/len(rows),4)
    report["stages"]["retrieval"]={"queries":len(rows),"metrics":metrics,"rows":rows}
    assert metrics["hybrid"]["recall3"]>=.90 and metrics["hybrid"]["mrr"]>=.75 and metrics["hybrid"]["degraded"]==0, metrics
    assert metrics["hybrid"]["recall5"]>=metrics["bm25"]["recall5"], metrics
    # The actual prompt path must consume the same ranked records and persist usage only on injection.
    context=manager.get_relevant_context(query="当前项目如何保存长期记忆",max_entries=5,max_tokens=1000)
    assert "MySQL" in context
    report["stages"]["injection"]={"bounded_context":bool(context),"usage_recorded":any(r.usage_count>0 for r in service.list_records())}
    # Bad/unknown execution evidence must not create a generic success memory.
    before={r.id for r in service.list_records()}
    service.capture_turn("嗯，谢谢",[{"role":"user","content":"嗯，谢谢"},{"role":"assistant","content":"任务已成功完成"}],outcome="unknown")
    jobs=service.run_jobs(200,kinds=["extract","embed"])
    assert not jobs["errors"] and {r.id for r in service.list_records()}==before
    report["stages"]["negative_evidence"]={"no_generic_success":True}
    for statement in ["本项目的记忆变更和审计事件必须通过同一个MySQL事务原子提交。",
        "本项目同一命名空间中相同内容的记忆必须去重，不能重复保存。",
        "本项目每次修改记忆必须递增revision，旧版本向量不能进入检索。"]:
        service.capture_turn(statement,[{"role":"user","content":statement}],outcome="user_declaration")
    jobs=service.run_jobs(200,kinds=["extract","embed"])
    assert not jobs["errors"]
    curated=service.curate()
    insights=[r for r in service.list_records() if r.kind=="insight"]
    assert curated["insights"]==1 and insights and len(insights[-1].metadata["source_revisions"])>=3
    calls_before=service.ledger.summary()["calls"]
    assert service.curate()["insights"]==0 and service.ledger.summary()["calls"]==calls_before
    source_id=next(iter(insights[-1].metadata["source_revisions"]))
    service.edit(source_id,"project",status="archived")
    assert insights[-1].id not in {r.id for r in service.retrieve("记忆存储事务和版本",mode="bm25",limit=100).records}
    report["stages"]["curation"]={"derived_insights":1,"idempotent":True,"stale_insight_excluded":True}
    jobs=service.run_jobs(200,kinds=["embed"])
    assert not jobs["errors"], jobs["errors"]
    report["queue"]=service.repository.job_counts(list(service.namespaces.values()))
    assert report["queue"].get("pending",0)==report["queue"].get("running",0)==report["queue"].get("failed",0)==0, report["queue"]
    report["cost"]=service.ledger.summary()
    report["passed"]=True
    (data/report_name).write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps({"passed":True,"metrics":metrics,"cost":report["cost"]},ensure_ascii=False),flush=True)
    return report

def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run()

if __name__=="__main__":
    main()
