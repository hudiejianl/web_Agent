from app.eval.rag_eval import RAGEvaluator
from app.models.schemas import TutorProfile
from app.rag.bm25 import BM25Retriever
from app.rag.evidence import RetrievalEvidenceBuilder
from app.rag.reranker import TutorReranker
from app.rag.retriever import TutorRetriever


def test_bm25_prioritizes_keyword_matches():
    profiles = [
        TutorProfile(id="vision", name="张三", institution="示例大学", research_areas=["计算机视觉"], summary="研究图像识别"),
        TutorProfile(id="rag", name="李四", institution="示例大学", research_areas=["RAG", "大模型"], summary="研究检索增强生成和智能体"),
    ]

    results = BM25Retriever(profiles).search("RAG 检索增强 大模型", limit=2)

    assert results[0][0].id == "rag"
    assert results[0][1] > 0
    assert all(profile.id != "vision" for profile, _ in results)


def test_retrieval_evidence_builder_highlights_matching_fields():
    profile = TutorProfile(
        id="tutor-1",
        name="张三",
        institution="示例大学",
        location="武汉",
        homepage="https://example.edu.cn/zhangsan",
        research_areas=["多模态", "人工智能"],
        admission_directions=["硕士招生"],
        summary="长期研究多模态人工智能。",
    )

    evidence = RetrievalEvidenceBuilder().build("武汉 多模态 人工智能 硕士 导师", [profile])

    assert evidence
    assert evidence[0].tutor_name == "张三"
    assert any(item.field == "research_areas" for item in evidence)
    assert any("**" in item.snippet for item in evidence)


def test_reranker_prioritizes_query_aligned_profiles():
    generic = TutorProfile(id="generic", name="王五", institution="示例大学", research_areas=["机器学习"], summary="机器学习")
    aligned = TutorProfile(
        id="aligned",
        name="赵六",
        institution="示例大学",
        location="武汉",
        research_areas=["多模态", "人工智能"],
        admission_directions=["硕士招生"],
        summary="多模态人工智能导师",
    )

    results = TutorReranker().rerank("武汉 多模态 人工智能 硕士 导师", [generic, aligned], limit=2)

    assert [profile.id for profile in results] == ["aligned", "generic"]


def test_rag_evaluator_computes_metrics():
    expected = TutorProfile(id="expected", name="李若水", institution="上海交通大学", research_areas=["RAG", "智能体系统"], summary="RAG 和智能体系统")

    class FakeRetriever:
        def search(self, query, limit=5, strategy="reranker"):
            return [expected]

    evaluator = RAGEvaluator(retriever=FakeRetriever())
    case = evaluator.load_cases()[0]
    result = evaluator.evaluate_case(case, limit=5)
    comparison = evaluator.compare(limit=5)

    assert result.recall == 1.0
    assert result.precision == 1.0
    assert result.relevance > 0
    assert [item.strategy for item in comparison.strategies] == ["baseline", "hybrid", "reranker"]


def test_hybrid_retriever_merges_dense_bm25_and_reranker_results():
    dense_only = TutorProfile(id="dense", name="王五", institution="示例大学", research_areas=["机器学习"], summary="机器学习")
    keyword_match = TutorProfile(id="keyword", name="赵六", institution="示例大学", research_areas=["多模态", "人工智能"], summary="多模态人工智能导师")

    class FakeRepository:
        def list(self, limit=200):
            return [dense_only, keyword_match]

        def get(self, tutor_id):
            return {"dense": dense_only, "keyword": keyword_match}.get(tutor_id)

    class FakeVectorStore:
        def query(self, text, limit=5):
            return ["dense"]

    results = TutorRetriever(repository=FakeRepository(), vector_store=FakeVectorStore()).search("多模态 人工智能 导师", limit=2)

    assert [profile.id for profile in results] == ["keyword", "dense"]
