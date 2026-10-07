import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

class Files:
    _export_lock = threading.RLock()
    def __init__(self, directory):
        self.directory = Path(directory)
        self.outbox = self.directory / "Outbox"

    @staticmethod
    def _replace(temp, path):
        # Windows may briefly deny replacement when another process is closing
        # or replacing the same derived export. Never remove the old snapshot.
        for attempt in range(8):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(min(.005 * 2**attempt, .05))

    @staticmethod
    def _write(path, value):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        Files._replace(temp, path)

    def spool(self, payload):
        path = self.outbox / (payload.get("turn_id", str(uuid.uuid4())) + ".json")
        self._write(path, payload)
        return str(path)

    def replay(self):
        pending = []
        for path in self.outbox.glob("*.json"):
            try:
                payload = json.loads(path.read_text("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("outbox payload is not an object")
                pending.append((str(path), payload))
            except (ValueError, UnicodeError):
                quarantine = self.directory / "OutboxCorrupt"
                quarantine.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(path, quarantine / (path.stem + "." + uuid.uuid4().hex + ".json"))
                except FileNotFoundError:
                    pass  # Another process has already quarantined this file.
            except FileNotFoundError:
                continue  # Another process has already acknowledged this submission.
        return pending

    def acknowledge(self, path):
        target = Path(path).resolve()
        if target.parent != self.outbox.resolve():
            raise ValueError("outbox path outside module data")
        target.unlink(missing_ok=True)
        try:
            self.outbox.rmdir()
        except OSError:
            pass  # Other pending submissions still occupy the directory.

    def fingerprints(self, workspace, paths):
        root = Path(workspace).resolve(); result = {}
        for value in paths[:30]:
            try:
                path = root / value
                if path.is_symlink():
                    continue
                resolved = path.resolve()
                if resolved.is_relative_to(root) and resolved.is_file() and resolved.stat().st_size <= 2_000_000:
                    result[str(resolved.relative_to(root))] = hashlib.sha256(resolved.read_bytes()).hexdigest()
            except (OSError, ValueError):
                continue  # A removed/unreadable source invalidates only its own memories.
        return result

    def validate(self, workspace, paths):
        actual = self.fingerprints(workspace, list(paths))
        return all(actual.get(path) == digest for path, digest in paths.items())

    def export(self, destination, records):
        with self._export_lock:
            return self._export(destination, records)

    def _export(self, destination, records):
        destination = Path(destination)
        rows = [{**r.__dict__,"category":r.kind} for r in records]
        self._write(destination / "memory.json", {"authority": "mysql", "entries": rows})
        for scope in ("user","project","local"):
            self._write(destination / scope / "memory.json", {"authority":"mysql","scope":scope,"entries":[row for row in rows if row["scope"]==scope and row["status"]=="active"]})
        content = "# Memory export (derived from MySQL; active records)\n\n" + "\n".join(f"- [{r.scope}/{r.kind}; v{r.revision}] {r.content}" for r in records if r.status=="active")
        path = destination / "MEMORY.md"
        temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        temp.write_text(content, "utf-8"); self._replace(temp, path)
        return {"records": len(records), "path": str(destination.resolve())}
