"""Collect real extraction outputs and score complete, audited annotations.

This evaluates the existing extractor only. It never writes memory records or
starts retrieval/embedding jobs. Model requests share the existing cost ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
DEFAULT_DATA = ROOT / "Package" / "AgentMemory" / "Data" / "Test" / "ExtractionV2"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_dataset(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [case["id"] for case in data["cases"]]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("dataset case IDs must be nonempty and unique")
    for case in data["cases"]:
        event_ids = [event["id"] for event in case["events"]]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("duplicate evidence IDs")
        gold_ids = [item["id"] for item in case["expected"]]
        if len(gold_ids) != len(set(gold_ids)):
            raise ValueError("duplicate expected-memory IDs")
        for item in case["expected"]:
            if item["scope"] not in {"user", "project", "local"} or not item["kinds"]:
                raise ValueError("gold scope and allowed kinds are required")
            if not set(item["evidence_any"]) <= set(event_ids):
                raise ValueError("gold evidence must occur in this case")
    return data


def collect(dataset_path, output_path, repeats=2, resume=False):
    from Package.AgentMemory.Src.Adapter.Out.External.QwenModels import QwenModels
    from Package.AgentMemory.Src.Adapter.Out.Persistence.CostLedger import CostLedger
    from Package.AgentMemory.Src.Adapter.Out.Persistence.Settings import load_settings
    from Package.AgentMemory.Src.Application.Dto.Contracts import MemoryRecord
    from Package.AgentMemory.Src.Application.Usecase.Extraction import extract
    from Package.AgentMemory.Src.Domain.Policy import redact

    dataset_path, output_path = Path(dataset_path), Path(output_path)
    dataset = load_dataset(dataset_path)
    if repeats < 1:
        raise ValueError("repeats must be positive")
    settings = load_settings(ROOT)
    ledger = CostLedger(settings.ledger_path, settings.budget_cny)
    models = QwenModels(settings.models, ledger)
    source_paths = ["Package/AgentMemory/Src/Application/Usecase/Extraction.py",
        "Package/AgentMemory/Src/Domain/Policy.py", "Package/AgentMemory/Src/Application/Dto/Schemas.py",
        "Package/AgentMemory/Src/Adapter/Out/External/QwenModels.py"]
    sources = {name:digest(ROOT / name) for name in source_paths}
    result = {"version":"extraction-eval-v1", "dataset_version":dataset["version"], "started_at":datetime.now(timezone.utc).isoformat(),
        "dataset":str(dataset_path.resolve()), "dataset_sha256":digest(dataset_path), "source_sha256":sources,
        "model":settings.models["generation_model"], "temperature":0, "repeats":repeats,
        "cost_before":ledger.summary(), "observations":[]}
    if resume and output_path.exists():
        result = json.loads(output_path.read_text(encoding="utf-8"))
        if result["dataset_sha256"] != digest(dataset_path) or result["source_sha256"] != sources or result["repeats"] != repeats:
            raise ValueError("resume requires unchanged data, extraction sources and repeats")
        if result["model"] != settings.models["generation_model"]:
            raise ValueError("resume model changed")
    completed = {(row["case_id"],row["repeat"]) for row in result["observations"] if not row.get("error")}
    result["observations"] = [row for row in result["observations"] if not row.get("error")]
    total = len(dataset["cases"]) * repeats
    for repeat in range(repeats):
        for case in dataset["cases"]:
            if (case["id"], repeat) in completed:
                continue
            existing = [MemoryRecord(namespace_id="synthetic-fixture-"+item["scope"], **item) for item in case.get("existing", [])]
            payload = redact({"task":case["task"], "events":case["events"], "outcome":case.get("outcome", "unknown")})
            started = time.monotonic()
            row = {"case_id":case["id"], "repeat":repeat, "category":case["category"]}
            before = ledger.summary()["calls"]
            try:
                candidates, rejected = extract(models, payload, existing)
                row.update(candidates=candidates, rejected=rejected)
            except Exception as exc:
                row.update(error=type(exc).__name__, candidates=[], rejected=[])
            row.update(elapsed_seconds=round(time.monotonic()-started,3), model_calls=ledger.summary()["calls"]-before)
            result["observations"].append(row)
            result["cost_after"] = ledger.summary()
            write_json(output_path,result)
            count = len(result["observations"])
            if count % 10 == 0 or row.get("error"):
                print(f"Extraction observations: {count}/{total}, request errors: {sum(bool(r.get('error')) for r in result['observations'])}", flush=True)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["complete"] = len(result["observations"]) == total and not any(row.get("error") for row in result["observations"])
    write_json(output_path,result)
    if not result["complete"]:
        raise RuntimeError("evaluation has failed requests; results retained for explicit resume")
    return result


def score(dataset_path, observations_path, labels_path):
    """Precision of complete accepted memories; missing memories aren't its denominator."""
    dataset = load_dataset(dataset_path)
    run = json.loads(Path(observations_path).read_text(encoding="utf-8"))
    labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    if not run.get("complete") or run["dataset_sha256"] != digest(dataset_path):
        raise ValueError("complete observations from this exact dataset are required")
    if labels["observations_sha256"] != digest(observations_path) or labels["dataset_sha256"] != digest(dataset_path):
        raise ValueError("labels must reference the exact frozen inputs and observations")
    cases = {case["id"]:case for case in dataset["cases"]}
    verdicts = {(item["case_id"],item["repeat"],item["candidate"]):item for item in labels["verdicts"]}
    if len(verdicts) != len(labels["verdicts"]):
        raise ValueError("duplicate candidate annotations")
    expected_rows = {(key,repeat) for key in cases for repeat in range(run["repeats"])}
    actual_rows = {(row["case_id"],row["repeat"]) for row in run["observations"]}
    if expected_rows != actual_rows or len(actual_rows) != len(run["observations"]):
        raise ValueError("missing or duplicate observation rows")
    used = set()
    counts = Counter()
    errors = []
    category_counts = {}
    for row in run["observations"]:
        if row.get("error"):
            raise ValueError("request failures cannot be scored as empty correct results")
        case = cases[row["case_id"]]
        gold = {item["id"]:item for item in case["expected"]}
        seen_gold = {}
        for index, candidate in enumerate(row["candidates"]):
            key = (row["case_id"],row["repeat"],index)
            if key not in verdicts:
                raise ValueError("every extracted candidate must be adjudicated")
            verdict = verdicts[key]
            used.add(key)
            if not isinstance(verdict["correct"],bool) or not verdict.get("reason"):
                raise ValueError("annotations need a boolean judgment and rationale")
            matched = verdict.get("matched_gold", [])
            if verdict["correct"]:
                if not matched or len(matched) != len(set(matched)) or not set(matched) <= set(gold):
                    raise ValueError("correct memories need unique golden support")
                support = verdict.get("gold_support", {})
                if not set(support) <= set(matched):
                    raise ValueError("support spans must belong to the matched golden memories")
                for gold_id in matched:
                    item = gold[gold_id]
                    # A gold sentence may contain several independent facts. A
                    # reviewer can assign literal, disjoint parts to split outputs;
                    # semantics are still adjudicated, not decided by text matching.
                    part = support.get(gold_id, item["content"])
                    if not isinstance(part, str) or not part.strip() or part not in item["content"]:
                        raise ValueError("gold support must be a nonempty literal span")
                    start = item["content"].index(part)
                    positions = set(range(start, start + len(part)))
                    if seen_gold.get(gold_id, set()) & positions:
                        raise ValueError("correct memories need unique golden support")
                    if candidate["scope"] != item["scope"] or candidate["kind"] not in item["kinds"] or candidate.get("operation","add") != item.get("operation","add"):
                        raise ValueError("a correct label disagrees with gold scope, kind or operation")
                    if not set(candidate["evidence_refs"]) & set(item["evidence_any"]):
                        raise ValueError("a correct label cites unrelated evidence")
                    if item.get("operation") == "update" and (candidate.get("memory_id") != item["memory_id"] or candidate.get("expected_revision") != item["expected_revision"]):
                        raise ValueError("a correct update targets the wrong record or revision")
                    seen_gold.setdefault(gold_id, set()).update(positions)
            counts["extracted"] += 1
            counts["correct"] += int(verdict["correct"])
            group = category_counts.setdefault(case["category"], Counter())
            group["extracted"] += 1
            group["correct"] += int(verdict["correct"])
            if not verdict["correct"]:
                errors.append({"case_id":row["case_id"],"repeat":row["repeat"],"candidate":candidate,"reason":verdict["reason"]})
    if used != set(verdicts):
        raise ValueError("annotations contain unknown observations")
    return {"metric":"accepted_memory_precision", "definition":"正确的完整候选条目数 / 提取器返回的候选条目总数；重复提取、不该记住的内容、错误作用域/类型/更新目标均算错误。漏提不进入该指标分母。",
        "dataset_cases":len(cases), "repeats":run["repeats"], "observations":len(run["observations"]),
        "extracted":counts["extracted"], "correct":counts["correct"],
        "accuracy":counts["correct"]/counts["extracted"] if counts["extracted"] else None,
        "empty_observations":sum(not row["candidates"] for row in run["observations"]),
        "case_categories":dict(Counter(case["category"] for case in cases.values())),
        "by_category":{key:{**value,"accuracy":value["correct"]/value["extracted"] if value["extracted"] else None} for key,value in category_counts.items()},
        "incorrect":errors, "model":run["model"], "dataset_sha256":run["dataset_sha256"],
        "observations_sha256":digest(observations_path), "labels_sha256":digest(labels_path),
        "source_sha256":run["source_sha256"], "cost_before":run["cost_before"], "cost_after":run["cost_after"],
        "model_requests":sum(row["model_calls"] for row in run["observations"]),
        "scope_note":"合成场景，测试集与语义判分由当前 Codex 编写和复核，未由独立人工标注者复核；结果衡量这一固定测试集上的候选准确率。"}


def main(argv=None):
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run","score"])
    parser.add_argument("--dataset",type=Path,default=DEFAULT_DATA/"golden.json")
    parser.add_argument("--observations",type=Path,default=DEFAULT_DATA/"observations.json")
    parser.add_argument("--labels",type=Path,default=DEFAULT_DATA/"adjudications.json")
    parser.add_argument("--report",type=Path,default=DEFAULT_DATA/"report.json")
    parser.add_argument("--repeats",type=int,default=2)
    parser.add_argument("--resume",action="store_true")
    args = parser.parse_args(argv)
    if args.action == "run":
        result = collect(args.dataset,args.observations,args.repeats,args.resume)
        print(json.dumps({"complete":result["complete"],"observations":len(result["observations"]),"cost":result["cost_after"]},ensure_ascii=False))
    else:
        result = score(args.dataset,args.observations,args.labels)
        write_json(args.report,result)
        print(json.dumps({key:result[key] for key in ("accuracy","correct","extracted","observations","model_requests","cost_after")},ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
