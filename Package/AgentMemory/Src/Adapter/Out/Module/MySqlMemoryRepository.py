"""MySQL is authoritative. Each mutation, audit event and index job commits together."""
import hashlib
import json
import struct
import time
import uuid
import threading
from contextlib import contextmanager
from Package.AgentMemory.Src.Adapter.Out.Module.DatabaseBinding import database
from Package.AgentMemory.Src.Application.Dto.MemoryRecord import MemoryRecord
from Package.AgentMemory.Src.Application.Error.MemoryUnavailable import MemoryUnavailable

def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

def decoded(value, default):
    return json.loads(value) if isinstance(value, str) else value if value is not None else default

class RevisionConflict(RuntimeError):
    pass

class MySqlMemoryRepository:
    def __init__(self, settings, fail_open=False):
        self.db = database(settings)
        self._initialized = False
        self._initialization_lock = threading.RLock()
        self._namespace_identities = {}
        self._registered_namespaces = set()
        self.fail_open = fail_open
        try:
            self._ensure_initialized()
        except MemoryUnavailable:
            if not fail_open:
                raise

    @contextmanager
    def _connection(self):
        try:
            with self.db.transaction() as tx:
                yield tx
        except Exception as exc:
            if type(exc).__name__ in {"OperationalError", "InterfaceError", "ConnectionError", "TimeoutError", "OSError"}:
                raise MemoryUnavailable("mysql_unavailable") from None
            raise

    def _ensure_initialized(self):
        with self._initialization_lock:
            if not self._initialized:
                self.initialize()
                self._initialized = True
            pending = {key: value for key, value in self._namespace_identities.items() if key not in self._registered_namespaces}
            if pending:
                with self._connection() as tx:
                    for key, (scope, digest) in pending.items():
                        tx.execute("INSERT IGNORE INTO memory_namespaces(id,scope,identity_hash) VALUES(%s,%s,%s)", (key, scope, digest))
                self._registered_namespaces.update(pending)

    @contextmanager
    def _transaction(self):
        self._ensure_initialized()
        with self._connection() as tx:
            yield tx

    def initialize(self):
        statements = [
            """CREATE TABLE IF NOT EXISTS memory_namespaces (
                id CHAR(36) PRIMARY KEY, scope VARCHAR(16) NOT NULL, identity_hash CHAR(64) NOT NULL,
                epoch BIGINT NOT NULL DEFAULT 0, UNIQUE KEY namespace_identity(scope,identity_hash)) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS memories (
                id CHAR(36) PRIMARY KEY, namespace_id CHAR(36) NOT NULL, scope VARCHAR(16) NOT NULL,
                kind VARCHAR(32) NOT NULL, content TEXT NOT NULL, content_hash CHAR(64) NOT NULL,
                status VARCHAR(16) NOT NULL, tier VARCHAR(16) NOT NULL, revision BIGINT NOT NULL,
                tags JSON NOT NULL, domains JSON NOT NULL, metadata JSON NOT NULL, evidence_refs JSON NOT NULL,
                source_type VARCHAR(32) NOT NULL, created_at DOUBLE NOT NULL, updated_at DOUBLE NOT NULL,
                usage_count BIGINT NOT NULL DEFAULT 0, UNIQUE KEY dedup(namespace_id,kind,content_hash),
                INDEX scope_status(namespace_id,status), FOREIGN KEY(namespace_id) REFERENCES memory_namespaces(id)) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS memory_events (
                seq BIGINT AUTO_INCREMENT PRIMARY KEY, memory_id CHAR(36) NOT NULL,
                revision BIGINT NOT NULL, action VARCHAR(32) NOT NULL, before_state JSON NULL,
                after_state JSON NOT NULL, created_at DOUBLE NOT NULL,
                UNIQUE KEY event_revision(memory_id,revision)) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id CHAR(36) NOT NULL, revision BIGINT NOT NULL, model_id VARCHAR(255) NOT NULL,
                dimensions INT NOT NULL, vector MEDIUMBLOB NOT NULL,
                PRIMARY KEY(memory_id,model_id), FOREIGN KEY(memory_id) REFERENCES memories(id)) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS memory_turns (
                id CHAR(36) PRIMARY KEY, namespace_id CHAR(36) NOT NULL, payload JSON NOT NULL,
                created_at DOUBLE NOT NULL, FOREIGN KEY(namespace_id) REFERENCES memory_namespaces(id)) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS memory_consolidations (
                namespace_id CHAR(36) NOT NULL, signature CHAR(64) NOT NULL, model_id CHAR(64) NOT NULL,
                result JSON NOT NULL, created_at DOUBLE NOT NULL,
                PRIMARY KEY(namespace_id,signature,model_id), FOREIGN KEY(namespace_id) REFERENCES memory_namespaces(id)) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS memory_jobs (
                id CHAR(36) PRIMARY KEY, job_key VARCHAR(255) NOT NULL UNIQUE, kind VARCHAR(32) NOT NULL,
                payload JSON NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'pending', attempts INT NOT NULL DEFAULT 0,
                available_at DOUBLE NOT NULL, lease_until DOUBLE NOT NULL DEFAULT 0, lease_token CHAR(36) NULL,
                error VARCHAR(500) NULL, result JSON NULL, INDEX queue(status,available_at)) ENGINE=InnoDB""",
        ]
        with self._connection() as tx:
            lock = tx.query("SELECT GET_LOCK('AgentMemorySchemaV1',10) AS acquired")[0]["acquired"]
            if lock != 1:
                raise RuntimeError("memory schema lock unavailable")
            for statement in statements:
                tx.execute(statement)
            if not tx.query("SHOW COLUMNS FROM memory_jobs LIKE 'result'"):
                tx.execute("ALTER TABLE memory_jobs ADD COLUMN result JSON NULL")
            tx.query("SELECT RELEASE_LOCK('AgentMemorySchemaV1')")

    def namespace(self, scope, identity):
        digest = hashlib.sha256(identity.encode()).hexdigest()
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, scope + ":" + digest))
        with self._initialization_lock:
            self._namespace_identities[key] = (scope, digest)
        try:
            self._ensure_initialized()
        except MemoryUnavailable:
            if not self.fail_open:
                raise
        return key

    @staticmethod
    def _record(row):
        fields = {key: row[key] for key in MemoryRecord.__dataclass_fields__ if key in row}
        for key in ("tags", "domains", "evidence_refs"):
            fields[key] = decoded(fields.get(key), [])
        fields["metadata"] = decoded(fields.get("metadata"), {})
        return MemoryRecord(**fields)

    def list_records(self, namespaces, statuses=None):
        if not namespaces:
            return []
        statuses = statuses or ["active"]
        with self._transaction() as tx:
            rows = tx.query("SELECT * FROM memories WHERE namespace_id IN (" + ",".join(["%s"]*len(namespaces)) +
                ") AND status IN (" + ",".join(["%s"]*len(statuses)) + ") ORDER BY created_at,id", tuple(namespaces) + tuple(statuses))
        return [self._record(row) for row in rows]

    def get(self, key, namespaces):
        with self._transaction() as tx:
            rows = tx.query("SELECT * FROM memories WHERE id=%s AND namespace_id IN (" + ",".join(["%s"]*len(namespaces)) + ")", (key, *namespaces))
        return self._record(rows[0]) if rows else None

    @staticmethod
    def _enqueue(tx, kind, payload, job_key):
        key = str(uuid.uuid4())
        tx.execute("INSERT IGNORE INTO memory_jobs(id,job_key,kind,payload,available_at) VALUES(%s,%s,%s,%s,%s)",
            (key, job_key, kind, packed(payload), time.time()))
        return key

    def enqueue(self, kind, payload, job_key):
        with self._transaction() as tx:
            return self._enqueue(tx, kind, payload, job_key)

    def commit(self, namespace, content, **attrs):
        digest = hashlib.sha256(" ".join(content.split()).encode("utf-8")).hexdigest()
        now = time.time()
        with self._transaction() as tx:
            ns = tx.query("SELECT scope FROM memory_namespaces WHERE id=%s FOR UPDATE", (namespace,))
            if not ns and self.fail_open:
                # Namespace identities remain deterministic when a turn was spooled offline.
                raise MemoryUnavailable("namespace_not_registered")
            if not ns:
                raise ValueError("unknown namespace")
            key = attrs.get("memory_id")
            before = tx.query("SELECT * FROM memories WHERE namespace_id=%s AND " + ("id=%s" if key else "kind=%s AND content_hash=%s") + " FOR UPDATE",
                (namespace, key) if key else (namespace, attrs.get("kind", "fact"), digest))
            old = self._record(before[0]) if before else None
            if key and old is None:
                raise ValueError("memory not found in namespace")
            if old and attrs.get("expected_revision", old.revision) != old.revision:
                raise RevisionConflict("memory changed; reload before editing")
            if old and not key:
                if not attrs.pop("revive", False) or old.status == "active":
                    return old
                attrs.setdefault("status", "active")
            key = key or (old.id if old else str(uuid.uuid4()))
            record = MemoryRecord(id=key, namespace_id=namespace, scope=ns[0]["scope"], kind=attrs.get("kind", old.kind if old else "fact"), content=content,
                status=attrs.get("status", old.status if old else "active"), tier=attrs.get("tier", old.tier if old else "short_term"),
                revision=old.revision+1 if old else 1,
                tags=attrs.get("tags", old.tags if old else []), domains=attrs.get("domains", old.domains if old else []),
                metadata=attrs.get("metadata", old.metadata if old else {}), evidence_refs=attrs.get("evidence_refs", old.evidence_refs if old else []),
                source_type=attrs.get("source_type", old.source_type if old else "explicit"), created_at=old.created_at if old else now,
                updated_at=now, usage_count=old.usage_count if old else 0)
            data = record.__dict__
            columns = [k for k in data if k != "score"]
            values = [packed(data[k]) if k in {"tags", "domains", "metadata", "evidence_refs"} else data[k] for k in columns]
            columns.append("content_hash"); values.append(digest)
            if old:
                mutable = [(k, v) for k, v in zip(columns, values) if k not in {"id", "namespace_id", "created_at"}]
                tx.execute("UPDATE memories SET " + ",".join(k+"=%s" for k, _ in mutable) + " WHERE id=%s", tuple(v for _, v in mutable)+(key,))
            else:
                tx.execute("INSERT INTO memories("+",".join(columns)+") VALUES("+",".join(["%s"]*len(values))+")", tuple(values))
            tx.execute("INSERT INTO memory_events(memory_id,revision,action,before_state,after_state,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                (key, record.revision, "update" if old else "create", packed(old.__dict__) if old else None, packed(data), now))
            tx.execute("UPDATE memory_namespaces SET epoch=epoch+1 WHERE id=%s", (namespace,))
            self._enqueue(tx, "embed", {"memory_id": key, "namespace": namespace, "revision": record.revision}, f"embed:{key}:{record.revision}")
            return record

    def capture(self, namespace, payload):
        key = payload["turn_id"]
        with self._transaction() as tx:
            inserted = tx.execute("INSERT IGNORE INTO memory_turns(id,namespace_id,payload,created_at) VALUES(%s,%s,%s,%s)", (key, namespace, packed(payload), time.time()))
            if inserted:
                self._enqueue(tx, "extract", payload, "extract:"+key)
                count = tx.query("SELECT COUNT(*) AS n FROM memory_turns WHERE namespace_id=%s", (namespace,))[0]["n"]
                if count % payload.get("curator_interval", 10) == 0:
                    self._enqueue(tx, "curate", {"namespace": namespace}, f"curate:{namespace}:{count}")
        return key

    @staticmethod
    def _job_scope(namespaces):
        if namespaces is None:
            return "", ()
        if not namespaces:
            return " AND 1=0", ()
        return " AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.namespace')) IN ("+",".join(["%s"]*len(namespaces))+")", tuple(namespaces)

    def claim(self, kinds=None, namespaces=None):
        now = time.time()
        with self._transaction() as tx:
            clause = " AND kind IN ("+",".join(["%s"]*len(kinds))+")" if kinds else ""
            scope, values = self._job_scope(namespaces)
            rows = tx.query("SELECT * FROM memory_jobs WHERE (status='pending' AND available_at<=%s OR status='running' AND lease_until<%s)"+clause+
                scope+" ORDER BY available_at,id LIMIT 1 FOR UPDATE SKIP LOCKED", (now, now, *(kinds or []), *values))
            if not rows:
                return None
            job = rows[0]; token = str(uuid.uuid4())
            tx.execute("UPDATE memory_jobs SET status='running',attempts=attempts+1,lease_until=%s,lease_token=%s WHERE id=%s", (now+300, token, job["id"]))
            job.update(payload=decoded(job["payload"], {}), lease_token=token, attempts=job["attempts"]+1)
            return job

    def finish(self, job, error=None, result=None):
        with self._transaction() as tx:
            count = tx.execute("UPDATE memory_jobs SET status=%s,error=%s,result=%s,available_at=%s,lease_until=0 WHERE id=%s AND lease_token=%s AND status='running'",
                ("done" if error is None else "failed" if job["attempts"] >= 3 else "pending", error[:500] if error else None, packed(result) if result is not None else None,
                    time.time()+min(300, 2**job["attempts"]), job["id"], job["lease_token"]))
            if count != 1:
                raise RevisionConflict("job lease expired or replaced")

    def job_counts(self, namespaces=None):
        scope, values = self._job_scope(namespaces)
        with self._transaction() as tx:
            return {r["status"]: r["n"] for r in tx.query("SELECT status,COUNT(*) AS n FROM memory_jobs WHERE 1=1"+scope+" GROUP BY status", values)}

    def next_available_at(self, namespaces):
        scope, values = self._job_scope(namespaces)
        with self._transaction() as tx:
            row = tx.query("SELECT MIN(CASE WHEN status='pending' THEN available_at ELSE lease_until END) AS due FROM memory_jobs WHERE status IN ('pending','running')"+scope, values)[0]
            return row["due"]

    def consolidation_result(self, namespace, signature, model_id):
        with self._transaction() as tx:
            rows = tx.query("SELECT result FROM memory_consolidations WHERE namespace_id=%s AND signature=%s AND model_id=%s", (namespace, signature, model_id))
            return decoded(rows[0]["result"], {}) if rows else None

    @contextmanager
    def consolidation_lock(self, namespace):
        name = "AgentMemoryCurate:" + namespace
        with self._transaction() as tx:
            acquired = tx.query("SELECT GET_LOCK(%s,0) AS acquired", (name,))[0]["acquired"] == 1
            try:
                yield acquired
            finally:
                if acquired:
                    tx.query("SELECT RELEASE_LOCK(%s)", (name,))

    def save_consolidation(self, namespace, signature, model_id, result):
        with self._transaction() as tx:
            tx.execute("INSERT IGNORE INTO memory_consolidations(namespace_id,signature,model_id,result,created_at) VALUES(%s,%s,%s,%s,%s)",
                (namespace, signature, model_id, packed(result), time.time()))

    def save_embedding(self, record, model_id, vector):
        blob = struct.pack("<"+"f"*len(vector), *vector)
        with self._transaction() as tx:
            rows = tx.query("SELECT revision,status FROM memories WHERE id=%s FOR UPDATE", (record.id,))
            if not rows or rows[0]["revision"] != record.revision or rows[0]["status"] != "active":
                return False
            tx.execute("INSERT INTO memory_embeddings(memory_id,revision,model_id,dimensions,vector) VALUES(%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE revision=VALUES(revision),dimensions=VALUES(dimensions),vector=VALUES(vector)",
                (record.id, record.revision, model_id, len(vector), blob))
            return True

    def vectors(self, namespaces, model_id):
        with self._transaction() as tx:
            rows = tx.query("SELECT e.* FROM memory_embeddings e JOIN memories m ON m.id=e.memory_id AND m.revision=e.revision WHERE m.status='active' AND m.namespace_id IN ("+
                ",".join(["%s"]*len(namespaces))+") AND e.model_id=%s", (*namespaces, model_id))
        return {row["memory_id"]: struct.unpack("<"+"f"*row["dimensions"], row["vector"]) for row in rows}

    def mark_used(self, records):
        with self._transaction() as tx:
            for record in records:
                tx.execute("UPDATE memories SET usage_count=usage_count+1 WHERE id=%s AND revision=%s AND status='active'", (record.id, record.revision))
