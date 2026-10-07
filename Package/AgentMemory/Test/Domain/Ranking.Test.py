import pytest
from Package.AgentMemory.Src.Domain.Ranking import bm25, cosine, fuse, tokens

def test_chinese_and_identifier_search():
    assert "记忆" in tokens("记忆保存 MySQL user_id")
    assert bm25("user_id", {"a": "user_id必须唯一", "b": "页面采用浅色主题"}) == ["a"]
    assert bm25("记忆保存", {"a": "记忆保存到MySQL", "b": "前端主题"})[0] == "a"

def test_vector_only_hit_survives_fusion():
    ranked, scores = fuse([["a"], ["b", "a"]])
    assert ranked == ["a", "b"] and scores["b"] > 0
    assert cosine([1, 0], [1, 0]) == 1
    with pytest.raises(ValueError):
        cosine([1], [1, 2])
