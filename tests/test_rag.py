"""RAG 模块单元测试"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from langchain_core.documents import Document

from rag.hybrid_search import HybridSearchService
from rag.rag_service import RagSummarizeService
from agent.tools.base_tool import ToolResult


# ═══════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════

@pytest.fixture
def mock_vector_store():
    """Mock VectorStoreService"""
    mock = MagicMock()
    # search_with_scores returns list of (Document, score)
    mock.search_with_scores.return_value = [
        (Document(page_content="扫地机器人适合小户型", metadata={"source": "选购指南.txt"}), 0.85),
        (Document(page_content="大户型推荐扫拖一体机", metadata={"source": "选购指南.txt"}), 0.72),
        (Document(page_content="5200mAh电池续航长", metadata={"source": "选购指南.txt"}), 0.65),
    ]
    return mock


@pytest.fixture
def sample_docs():
    """标准测试文档"""
    return [
        Document(page_content="扫地机器人适合小户型", metadata={"source": "doc1"}),
        Document(page_content="5200mAh电池续航", metadata={"source": "doc2"}),
        Document(page_content="2cm越障能力强", metadata={"source": "doc3"}),
    ]


@pytest.fixture
def hybrid_search(mock_vector_store):
    """已初始化的 HybridSearchService（启用混合检索）"""
    hs = HybridSearchService(mock_vector_store)
    hs._enabled = True
    hs._semantic_weight = 0.5
    hs._rrf_k = 60
    return hs


# ═══════════════════════════════════════════
# HybridSearchService 测试
# ═══════════════════════════════════════════

class TestHybridSearchService:
    """混合检索服务测试"""

    def test_build_index(self, hybrid_search, sample_docs):
        """构建 BM25 索引后应有 bm25 对象"""
        hybrid_search.build_index(sample_docs)
        assert hybrid_search.bm25 is not None, "BM25 索引未构建"
        assert len(hybrid_search._documents) == 3

    def test_build_index_empty(self, hybrid_search):
        """空文档列表不应构建索引"""
        hybrid_search.build_index([])
        assert hybrid_search.bm25 is None

    def test_build_index_disabled(self, mock_vector_store):
        """混合检索关闭时不应构建索引"""
        hs = HybridSearchService(mock_vector_store)
        hs._enabled = False
        hs.build_index([Document(page_content="test")])
        assert hs.bm25 is None

    def test_search_fallback_when_bm25_disabled(self, mock_vector_store):
        """BM25 不可用时降级为纯语义检索"""
        hs = HybridSearchService(mock_vector_store)
        hs._enabled = False
        results = hs.search_with_scores("小户型", k=3)
        assert len(results) == 3
        assert mock_vector_store.search_with_scores.called

    def test_search_fallback_when_no_index(self, hybrid_search):
        """BM25 索引未构建时降级"""
        results = hybrid_search.search_with_scores("小户型", k=3)
        assert len(results) == 3

    def test_rrf_fusion_ordering(self, hybrid_search):
        """RRF 融合后分数最高的排在第一个"""
        semantic = [
            (Document(page_content="doc_a", metadata={}), 0.9),
            (Document(page_content="doc_b", metadata={}), 0.7),
        ]
        bm25 = [
            (Document(page_content="doc_c", metadata={}), 0.8),
            (Document(page_content="doc_a", metadata={}), 0.6),
        ]
        fused = hybrid_search._rrf_fusion(semantic, bm25, k=3)
        # doc_a 在两组中都出现，应排在前列
        assert fused[0][0].page_content == "doc_a"

    def test_tokenize(self):
        """中文分词应返回词列表"""
        tokens = HybridSearchService._tokenize("扫地机器人")
        assert isinstance(tokens, list)
        assert len(tokens) > 0

    def test_add_documents_incremental(self, hybrid_search, sample_docs):
        """增量添加文档后索引应更新"""
        hybrid_search.build_index(sample_docs[:2])
        original_len = len(hybrid_search._documents)
        hybrid_search.add_documents(sample_docs[2:])
        assert len(hybrid_search._documents) == original_len + 1


# ═══════════════════════════════════════════
# RagSummarizeService 测试
# ═══════════════════════════════════════════

class TestRagSummarizeService:
    """总结服务测试"""

    @patch("rag.rag_service.chat_model")
    @patch("rag.rag_service.load_rag_prompts")
    def test_rag_summarize(self, mock_load_prompts, mock_chat_model):
        """rag_summarize 应返回字符串结果"""
        # Mock 提示词
        mock_load_prompts.return_value = "请根据参考资料回答问题：{context}\\n问题：{input}"

        # Mock LLM chain
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = "RAG是检索增强生成技术..."

        with patch.object(RagSummarizeService, "_init_chain", return_value=mock_chain):
            with patch.object(RagSummarizeService, "_init_bm25_index", return_value=None):
                rag = RagSummarizeService()
                # Mock 检索层，隔离对向量库 / Embedding API 的真实调用（无 key 离线可跑）
                with patch.object(rag, "retriever_docs", return_value=[Document(page_content="测试资料")]):
                    result = rag.rag_summarize("什么是RAG？")

        assert isinstance(result, str)
        assert len(result) > 0

    @patch("rag.rag_service.chat_model")
    @patch("rag.rag_service.load_rag_prompts")
    def test_retriever_docs_calls_hybrid_search(self, mock_load_prompts, mock_chat_model):
        """retriever_docs 应调用混合检索"""
        mock_load_prompts.return_value = "prompt"
        mock_chain = MagicMock()

        with patch.object(RagSummarizeService, "_init_chain", return_value=mock_chain):
            with patch.object(RagSummarizeService, "_init_bm25_index", return_value=None):
                rag = RagSummarizeService()
                # 替换 hybrid_search 为 Mock
                rag.hybrid_search = MagicMock()
                rag.hybrid_search.search_with_scores.return_value = [
                    (Document(page_content="test"), 0.9)
                ]

                docs = rag.retriever_docs("test query")

        assert len(docs) == 1
        rag.hybrid_search.search_with_scores.assert_called_once()
