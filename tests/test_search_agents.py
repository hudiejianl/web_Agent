import os

os.environ["LLM_PROVIDER"] = "none"

from app.agents.query_rewriter import QueryRewriter
from app.search.result_filter import SearchResultFilter


def test_query_rewriter_expands_user_goal_to_site_queries():
    queries = QueryRewriter().rewrite("帮我找武汉计算机方向导师，最好做多模态和人工智能", max_queries=5)

    assert queries
    assert all("site:" in query for query in queries[:2])
    assert any("武汉" in query for query in queries)
    assert any("hust.edu.cn" in query or "whut.edu.cn" in query or "whu.edu.cn" in query for query in queries)
    assert any("多模态" in query for query in queries)


def test_search_result_filter_keeps_faculty_pages_and_drops_noise():
    links = [
        {"text": "张三 教授 个人主页 研究方向 人工智能 多模态", "url": "https://cs.hust.edu.cn/teacher/zhangsan"},
        {"text": "武汉旅游酒店攻略", "url": "https://travel.example.com/wuhan/hotel"},
    ]

    candidates = SearchResultFilter().filter_links(links, "武汉 计算机 多模态 导师", "https://example.com/search")

    assert len(candidates) == 1
    assert candidates[0].url == "https://cs.hust.edu.cn/teacher/zhangsan"
    assert candidates[0].score > 5
