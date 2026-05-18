from app.eval.rag_eval import RAGEvaluator
from app.models.schemas import TutorProfile
from app.rag.bm25 import BM25Retriever
from app.rag.embeddings import HashingEmbeddingFunction, OpenAICompatibleEmbeddingFunction, get_embedding_function
from app.rag.evidence import RetrievalEvidenceBuilder
from app.rag.reranker import TutorReranker
from app.rag.retriever import TutorRetriever
from app.rag.vector_store import VectorStore, chunk_text


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


def test_chunk_text_respects_size_and_overlap():
    chunks = chunk_text("abcdefghijklmnopqrstuvwxyz", chunk_size=10, overlap=3)

    assert chunks == ["abcdefghij", "hijklmnopq", "opqrstuvwx", "vwxyz"]


def test_vector_store_indexes_chunks_and_returns_unique_tutor_ids(monkeypatch):
    class FakeSettings:
        chroma_path = "data/runtime/test-chroma"
        chroma_collection = "test-tutors"
        rag_chunk_size = 20
        rag_chunk_overlap = 5

    class FakeCollection:
        def __init__(self):
            self.upsert_payload = None

        def upsert(self, ids, documents, metadatas):
            self.upsert_payload = {"ids": ids, "documents": documents, "metadatas": metadatas}

        def query(self, query_texts, n_results):
            return {
                "ids": [["tutor-1::chunk::1", "tutor-1::chunk::0", "tutor-2::chunk::0"]],
                "metadatas": [[{"tutor_id": "tutor-1"}, {"tutor_id": "tutor-1"}, {"tutor_id": "tutor-2"}]],
            }

    class FakeClient:
        def __init__(self):
            self.collection = FakeCollection()

        def get_or_create_collection(self, name, embedding_function, metadata):
            return self.collection

    fake_client = FakeClient()
    monkeypatch.setattr("app.rag.vector_store.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.rag.vector_store.chromadb.PersistentClient", lambda path, settings: fake_client)
    monkeypatch.setattr("app.rag.vector_store.get_embedding_function", lambda: object())

    store = VectorStore()
    profile = TutorProfile(id="tutor-1", name="张三", institution="示例大学", summary="人工智能" * 20)
    store.upsert_tutor(profile)

    assert len(fake_client.collection.upsert_payload["ids"]) > 1
    assert all(metadata["tutor_id"] == "tutor-1" for metadata in fake_client.collection.upsert_payload["metadatas"])
    assert store.query("人工智能", limit=2) == ["tutor-1", "tutor-2"]


def test_openai_compatible_embedding_function_calls_embeddings_api(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"index": 1, "embedding": [0.3, 0.4]}, {"index": 0, "embedding": [0.1, 0.2]}]}

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.rag.embeddings.requests.post", fake_post)
    embeddings = OpenAICompatibleEmbeddingFunction("text-embedding-demo", "secret", "https://api.example.com/v1", 12)(["a", "b"])

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert calls[0]["url"] == "https://api.example.com/v1/embeddings"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret"
    assert calls[0]["json"] == {"model": "text-embedding-demo", "input": ["a", "b"]}
    assert calls[0]["timeout"] == 12


def test_embedding_function_falls_back_without_api_key(monkeypatch):
    class FakeSettings:
        embedding_provider = "openai-compatible"
        embedding_api_key = ""
        embedding_base_url = "https://api.example.com/v1"
        openai_base_url = "https://api.openai.com/v1"
        embedding_model = "hashing"
        embedding_timeout_seconds = 30

    monkeypatch.setattr("app.rag.embeddings.get_settings", lambda: FakeSettings())

    assert isinstance(get_embedding_function(), HashingEmbeddingFunction)


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
    evaluation = evaluator.evaluate(limit=5)
    comparison = evaluator.compare(limit=5)
    config_comparison = evaluator.compare_configurations(limit=5)

    assert result.recall == 1.0
    assert result.precision == 1.0
    assert result.relevance > 0
    assert result.faithfulness == 1.0
    assert evaluation.config.retrieval_strategy == "reranker"
    assert 0 <= comparison.strategies[0].faithfulness <= 1
    assert [item.strategy for item in comparison.strategies] == ["baseline", "hybrid", "reranker"]
    assert len(config_comparison.configurations) >= 3
    assert all(item.config for item in config_comparison.configurations)


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
