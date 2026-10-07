from collections import OrderedDict
import threading
from Package.AgentMemory.Src.Domain.Ranking import bm25, cosine, fuse
from Package.AgentMemory.Src.Application.Dto.Contracts import RetrievalResult
from Package.AgentMemory.Src.Application.Port.Out.Capabilities import MemoryRepository, ModelGateway, SourceReader

class Retrieval:
    def __init__(self, repository: MemoryRepository, models: ModelGateway, files: SourceReader, settings):
        self.repository, self.models, self.files, self.settings = repository, models, files, settings
        self.query_cache = OrderedDict()
        self._cache_lock = threading.Lock()

    def retrieve(self, query, namespaces, limit=5, mode="hybrid", domains=None):
        if limit <= 0:
            return RetrievalResult([], {"reason": "empty_limit"})
        if not query.strip():
            return RetrievalResult([], {"reason": "empty_query"})
        records = self.repository.list_records(namespaces)
        records = [r for r in records if self.files.validate(self.settings.workspace, r.metadata.get("file_hashes", {}))]
        versions = {r.id: r.revision for r in records}
        records = [r for r in records if all(versions.get(key) == revision for key, revision in r.metadata.get("source_revisions", {}).items())]
        by_id = {r.id: r for r in records}
        texts = {r.id: r.content + " " + " ".join(r.tags) for r in records}
        keyword = bm25(query, texts)
        dense, errors = [], []
        if records and mode != "bm25":
            try:
                cache_key = (self.models.identity, query)
                with self._cache_lock:
                    query_vector = self.query_cache.get(cache_key)
                if query_vector is None:
                    query_vector = self.models.embed([query])[0]
                    with self._cache_lock:
                        self.query_cache[cache_key] = query_vector
                        if len(self.query_cache) > 128:
                            self.query_cache.popitem(last=False)
                vectors = self.repository.vectors(namespaces, self.models.identity)
                scores = {key: cosine(query_vector, vector) for key, vector in vectors.items() if key in by_id}
                dense = sorted(scores, key=lambda key: (-scores[key], key))
            except Exception as exc:
                if not self.settings.fail_open:
                    raise
                errors.append("dense:"+type(exc).__name__)
        top = min(max(1, self.settings.candidate_top_k), self.settings.max_candidate_top_k)
        ranked, scores = fuse([keyword[:top], dense[:top]], self.settings.rrf_k)
        if mode == "bm25":
            ranked = keyword; scores = {key: 1/(i+1) for i, key in enumerate(keyword)}
        if mode == "dense":
            ranked = dense; scores = {key: 1/(i+1) for i, key in enumerate(dense)}
        if domains:
            ranked.sort(key=lambda key: (-int(bool(set(domains)&set(by_id[key].domains))), -scores[key]))
        reranked = False
        if ranked and mode not in {"bm25", "dense", "rrf"} and self.settings.rerank_enabled:
            try:
                candidates = ranked[:top]
                result = self.models.rerank(query, [texts[key] for key in candidates], min(len(candidates), max(1, limit)))
                ranked = [candidates[index] for index, _ in result]; scores.update({candidates[index]: score for index, score in result})
                reranked = True
            except Exception as exc:
                if not self.settings.fail_open:
                    raise
                errors.append("rerank:"+type(exc).__name__)
        selected = []
        # Re-read after external calls: concurrent delete/edit cannot inject stale content.
        for key in ranked[:max(0, limit)]:
            current = self.repository.get(key, namespaces)
            if current and current.status == "active" and current.revision == by_id[key].revision and self.files.validate(self.settings.workspace, current.metadata.get("file_hashes", {})):
                valid_sources = True
                for source_id, revision in current.metadata.get("source_revisions", {}).items():
                    source = self.repository.get(source_id, namespaces)
                    if not source or source.status != "active" or source.revision != revision or not self.files.validate(self.settings.workspace, source.metadata.get("file_hashes", {})):
                        valid_sources = False
                        break
                if valid_sources:
                    current.score = scores[key]; selected.append(current)
        return RetrievalResult(selected, {"eligible": len(records), "keyword_hits": len(keyword), "dense_hits": len(dense),
            "reranked": reranked, "degraded": bool(errors), "errors": errors, "model_id": self.models.identity})
