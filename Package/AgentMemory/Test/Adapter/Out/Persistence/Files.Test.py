from Package.AgentMemory.Src.Adapter.Out.Persistence.Files import Files
from concurrent.futures import ThreadPoolExecutor
import json

def test_spool_replay_and_source_invalidation(tmp_path):
    files = Files(tmp_path/"data")
    source = tmp_path/"fact.txt"; source.write_text("v1", "utf-8")
    hashes = files.fingerprints(str(tmp_path), ["fact.txt", "../outside.txt"])
    assert list(hashes) == ["fact.txt"]
    assert files.validate(str(tmp_path), hashes)
    source.write_text("v2", "utf-8")
    assert not files.validate(str(tmp_path), hashes)
    path = files.spool({"turn_id": "test", "events": []})
    assert files.replay() == [(path, {"turn_id": "test", "events": []})]
    files.acknowledge(path)
    assert files.replay() == []

def test_corrupt_outbox_does_not_block_valid_submissions(tmp_path):
    files = Files(tmp_path/"data")
    good = files.spool({"turn_id":"valid", "events":[]})
    (files.outbox/"corrupt.json").write_text('{"events":', "utf-8")
    assert files.replay() == [(good, {"turn_id":"valid", "events":[]})]
    assert len(list((files.directory/"OutboxCorrupt").glob("*.json"))) == 1
    files.acknowledge(good)
    files.acknowledge(good)

def test_concurrent_exports_use_distinct_atomic_files(tmp_path):
    files = Files(tmp_path/"data")
    with ThreadPoolExecutor(max_workers=6) as executor:
        outputs = list(executor.map(lambda _:files.export(tmp_path/"exports", []), range(24)))
    assert len(outputs) == 24
    assert json.loads((tmp_path/"exports"/"memory.json").read_text("utf-8"))["entries"] == []
    assert (tmp_path/"exports"/"MEMORY.md").read_text("utf-8").startswith("# Memory export")
    assert not list((tmp_path/"exports").glob("*.tmp"))
