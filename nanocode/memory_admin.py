"""Explicit administration through the public memory runtime surface."""
import argparse
import json
from pathlib import Path
from Package.AgentMemory.Src.Boot.App import createApp

def main():
    parser = argparse.ArgumentParser(description="MySQL memory administration")
    parser.add_argument("action", choices=["status", "jobs", "export", "migrate", "reindex", "curate", "search"])
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--env-file")
    parser.add_argument("--test-database", action="store_true")
    parser.add_argument("--query", default="")
    parser.add_argument("--destination")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    service = createApp({"workspace": args.workspace, "env_file": args.env_file,
        "overrides": {"NANOCODE_MYSQL_DATABASE": "nanocode_memory_test"} if args.test_database else {}})
    if args.action == "status":
        result = {"active_memories": len(service.list_records()), "jobs": service.repository.job_counts(list(service.namespaces.values())), "cost": service.ledger.summary()}
    elif args.action == "jobs":
        result = service.run_jobs(args.limit)
    elif args.action == "export":
        result = service.export(args.destination or str(Path(service.settings.data_dir)/"Exports"))
    elif args.action == "migrate":
        root = Path(args.workspace)
        result = service.migrate({"project": root/".nanocode-memory"/"memory.json", "local": root/".nanocode-memory-local"/"memory.json", "user": Path.home()/".nanocode"/"memory"/"memory.json"})
    elif args.action == "reindex":
        result = service.reindex()
    elif args.action == "curate":
        result = service.curate()
    else:
        response = service.retrieve(args.query, limit=5)
        result = {"records": [r.__dict__ for r in response.records], "diagnostics": response.diagnostics}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and result.get("errors"):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
