"""Pure admission rules; model confidence never authorizes a write."""
import hashlib
import re

KINDS = {"fact", "preference", "decision", "procedure", "lesson", "insight", "general", "architecture", "convention", "pattern"}
STATUSES = {"active", "superseded", "archived", "deleted"}


def content_hash(content):
    return hashlib.sha256(" ".join(content.split()).encode("utf-8")).hexdigest()


def validate_candidate(candidate, events):
    if not isinstance(candidate, dict):
        return "candidate must be an object"
    text = candidate.get("content", "")
    if not isinstance(text, str) or not 8 <= len(text.strip()) <= 2000:
        return "content length must be 8..2000"
    if candidate.get("kind") not in KINDS or candidate.get("scope", "project") not in {"project", "local", "user"}:
        return "invalid kind or scope"
    refs = candidate.get("evidence_refs", [])
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in events for ref in refs):
        return "missing or unknown evidence"
    for field in ("tags", "domains"):
        values = candidate.get(field, [])
        if not isinstance(values, list) or len(values) > 16 or any(not isinstance(v, str) or len(v) > 100 for v in values):
            return "invalid tags or domains"
    if candidate.get("scope") == "user" and not any(events[r].get("role") == "user" for r in refs):
        return "user memory requires explicit user evidence"
    if candidate.get("kind") in {"procedure", "lesson"}:
        if not any(events[r].get("role") == "tool_result" and not events[r].get("isError", False) for r in refs):
            return "procedure requires successful tool evidence"
    if re.search(r"sk-[A-Za-z0-9_.-]{12,}|(?i:password|api_key)\s*[:=]\s*\S+", text):
        return "secret-like content"
    return None


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.search(r"(?i)password|api.?key|authorization|secret|token$", k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"sk-[A-Za-z0-9_.-]{12,}", "[REDACTED]", value)
        return re.sub(r"(?i)(password|api_key|authorization|secret)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", value)
    return value
