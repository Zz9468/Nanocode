"""The measurement must never hide unlabeled, failed or mismatched observations."""
import json
import pytest
from nanocode.memory_extraction_eval import digest, load_dataset, score, write_json


def artifacts(tmp_path, candidates, verdicts, gold_text="本项目使用MySQL。"):
    dataset_path=tmp_path/"gold.json"
    write_json(dataset_path,{"cases":[{"id":"E1","category":"decision","events":[{"id":"e0","role":"user","content":gold_text}],
        "expected":[{"id":"g1","content":gold_text,"scope":"project","kinds":["decision"],"evidence_any":["e0"],"operation":"add"}]}]})
    observations=tmp_path/"observations.json"
    write_json(observations,{"complete":True,"dataset_sha256":digest(dataset_path),"source_sha256":{},"model":"fixture-metadata-only",
        "repeats":1,"cost_before":{},"cost_after":{},"observations":[{"case_id":"E1","repeat":0,"candidates":candidates,"model_calls":0}]})
    labels=tmp_path/"labels.json"
    write_json(labels,{"dataset_sha256":digest(dataset_path),"observations_sha256":digest(observations),"verdicts":verdicts})
    return dataset_path,observations,labels


def candidate(scope="project"):
    return {"content":"本项目使用MySQL。","scope":scope,"kind":"decision","operation":"add","evidence_refs":["e0"]}


def verdict(index, correct, matched=None):
    return {"case_id":"E1","repeat":0,"candidate":index,"correct":correct,"matched_gold":matched or [],"reason":"Scoring arithmetic fixture; no model substitute is involved."}


def test_correctness_denominator_includes_incorrect_and_duplicate_candidates(tmp_path):
    paths=artifacts(tmp_path,[candidate(),candidate()], [verdict(0,True,["g1"]),verdict(1,False)])
    report=score(*paths)
    assert report["extracted"]==2 and report["correct"]==1 and report["accuracy"]==.5
    assert len(report["incorrect"])==1


def test_missing_adjudication_cannot_be_omitted_from_denominator(tmp_path):
    paths=artifacts(tmp_path,[candidate()],[])
    with pytest.raises(ValueError,match="every extracted candidate"):
        score(*paths)


def test_wrong_scope_cannot_be_labeled_correct(tmp_path):
    paths=artifacts(tmp_path,[candidate("user")],[verdict(0,True,["g1"])])
    with pytest.raises(ValueError,match="scope, kind or operation"):
        score(*paths)


def test_empty_output_has_undefined_candidate_accuracy(tmp_path):
    report=score(*artifacts(tmp_path,[],[]))
    assert report["accuracy"] is None and report["empty_observations"]==1


def test_modified_observations_or_failed_requests_cannot_be_scored(tmp_path):
    paths=artifacts(tmp_path,[candidate()],[verdict(0,True,["g1"])])
    run=json.loads(paths[1].read_text("utf-8")); run["observations"][0]["error"]="ModelRequestError"
    write_json(paths[1],run)
    with pytest.raises(ValueError,match="exact frozen"):
        score(*paths)
    labels=json.loads(paths[2].read_text("utf-8")); labels["observations_sha256"]=digest(paths[1]); write_json(paths[2],labels)
    with pytest.raises(ValueError,match="request failures"):
        score(*paths)


def test_fixed_dataset_has_unique_evidence_and_eighty_cases():
    from nanocode.memory_extraction_eval import DEFAULT_DATA
    dataset=load_dataset(DEFAULT_DATA/"golden.json")
    assert len(dataset["cases"])==80 and len(dataset["categories"])==10
    assert dataset["authored_before_model_runs"]


def test_independent_facts_split_from_one_gold_sentence_can_both_be_correct(tmp_path):
    gold_text="本项目使用Redis缓存，业务记录由MySQL保存。"
    outputs=[dict(candidate(),content="本项目使用Redis缓存。"),dict(candidate(),content="业务记录由MySQL保存。")]
    labels=[dict(verdict(0,True,["g1"]),gold_support={"g1":"本项目使用Redis缓存"}),
        dict(verdict(1,True,["g1"]),gold_support={"g1":"业务记录由MySQL保存"})]
    report=score(*artifacts(tmp_path,outputs,labels,gold_text))
    assert report["correct"]==2 and report["accuracy"]==1


@pytest.mark.parametrize("second_span,message",[("本项目使用MySQL","unique golden support"),("不存在的事实","literal span")])
def test_duplicate_or_invented_gold_spans_cannot_inflate_correct_count(tmp_path,second_span,message):
    labels=[dict(verdict(0,True,["g1"]),gold_support={"g1":"本项目使用MySQL"}),
        dict(verdict(1,True,["g1"]),gold_support={"g1":second_span})]
    with pytest.raises(ValueError,match=message):
        score(*artifacts(tmp_path,[candidate(),candidate()],labels))
