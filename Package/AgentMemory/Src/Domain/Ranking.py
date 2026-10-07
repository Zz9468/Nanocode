"""Keyword, dense and reciprocal-rank fusion on the same eligible corpus."""
import math
import re
from collections import Counter


def tokens(text):
    words = re.findall(r"[a-z0-9_./:-]+", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.extend(run[i:i+2] for i in range(max(1, len(run)-1)))
    return words


def bm25(query, documents):
    corpus = {key: tokens(value) for key, value in documents.items()}
    frequencies = {key: Counter(doc) for key, doc in corpus.items()}
    average = sum(map(len, corpus.values())) / max(1, len(corpus))
    scores = {}
    for word in set(tokens(query)):
        df = sum(word in doc for doc in corpus.values())
        idf = math.log(1 + (len(corpus) - df + .5) / (df + .5))
        for key, doc in corpus.items():
            freq = frequencies[key][word]
            if freq:
                scores[key] = scores.get(key, 0) + idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * len(doc) / max(1, average)))
    return sorted(scores, key=lambda key: (-scores[key], key))


def cosine(left, right):
    if len(left) != len(right) or not left:
        raise ValueError("embedding dimensions differ")
    if not all(math.isfinite(x) for x in (*left, *right)):
        raise ValueError("non-finite embedding")
    norm = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    return sum(a*b for a, b in zip(left, right)) / norm if norm else 0.0


def fuse(rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            scores[key] = scores.get(key, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda key: (-scores[key], key)), scores
