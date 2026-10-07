import json
import math
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from Package.AgentMemory.Src.Application.Port.Out.Capabilities import RequestBudget

class ModelRequestError(RuntimeError):
    pass

class QwenModels:
    def __init__(self, settings, ledger: RequestBudget):
        self.settings, self.ledger = settings, ledger
        self.identity = settings["embedding_model"] + ":" + str(settings["dimensions"]) + ":" + settings["embedding_url"].rstrip("/")

    def _request(self, kind, url, key, body, max_output=0, extra_bound=0):
        if not url.startswith("https://") or not key:
            raise ModelRequestError("HTTPS model endpoint and API key are required")
        wire = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(wire) > 200_000:
            raise ModelRequestError("model payload exceeds bounded request size")
        ticket = self.ledger.reserve(kind, len(wire)+1024+extra_bound, max_output)
        try:
            with urlopen(Request(url, data=wire, headers={"Authorization": "Bearer "+key, "Content-Type": "application/json"}), timeout=60) as response:
                data = json.loads(response.read(4_000_000))
        except HTTPError as exc:
            # Never log body/headers: providers may echo sensitive input.
            raise ModelRequestError(f"{kind} endpoint returned HTTP {exc.code}") from None
        except Exception as exc:
            raise ModelRequestError(f"{kind} transport failed ({type(exc).__name__}); reservation retained") from None
        self.ledger.settle(ticket, data.get("usage"))
        return data

    def generate(self, system, payload, schema=None):
        body = {"model": self.settings["generation_model"], "messages": [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "response_format": {"type": "json_object"},
            "enable_thinking": False, "temperature": 0, "max_tokens": 2048}
        if schema is not None:
            body["response_format"] = {"type":"json_schema", "json_schema":{"name":"memory_contract","strict":True,"schema":schema}}
        data = self._request("generation", self.settings["generation_url"].rstrip("/")+"/chat/completions", self.settings["generation_key"], body, 2048)
        if data["choices"][0].get("finish_reason") == "length":
            raise ModelRequestError("structured generation truncated")
        result = json.loads(data["choices"][0]["message"]["content"])
        if not isinstance(result, dict):
            raise ModelRequestError("structured output is not an object")
        return result

    def embed(self, texts):
        result = []
        for start in range(0, len(texts), 20):
            batch = texts[start:start+20]
            body = {"model": self.settings["embedding_model"], "input": batch, "dimensions": self.settings["dimensions"]}
            data = self._request("embedding", self.settings["embedding_url"].rstrip("/")+"/embeddings", self.settings["embedding_key"], body)
            rows = sorted(data["data"], key=lambda item: item["index"])
            if [row["index"] for row in rows] != list(range(len(batch))):
                raise ModelRequestError("embedding indices missing or duplicated")
            for row in rows:
                vector = row["embedding"]
                if len(vector) != self.settings["dimensions"] or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector):
                    raise ModelRequestError("invalid embedding dimensions or values")
                result.append(vector)
        return result

    def rerank(self, query, documents, top_n):
        body = {"model": self.settings["rerank_model"], "input": {"query": query, "documents": documents}, "parameters": {"top_n": min(top_n, len(documents))}}
        data = self._request("rerank", self.settings["rerank_url"], self.settings.get("rerank_key", self.settings["generation_key"]), body,
            extra_bound=len(query.encode("utf-8"))*len(documents)+128*len(documents))
        results = [(row["index"], float(row["relevance_score"])) for row in data["output"]["results"]]
        if len(results) != min(top_n, len(documents)) or len({i for i, _ in results}) != len(results) or any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(documents) or not math.isfinite(score) for i, score in results):
            raise ModelRequestError("invalid rerank indices or scores")
        return results
