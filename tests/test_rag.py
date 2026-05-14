from app.models.schemas import TutorProfile
from app.rag.bm25 import BM25Retriever
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


def test_hybrid_retriever_merges_dense_and_bm25_results():
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
