"""
混合检索服务

在纯语义向量检索基础上，融合 BM25 关键词检索，
通过 RRF (Reciprocal Rank Fusion) 算法融合排序。

优势：
- 语义检索：理解"小户型适合什么"和"紧凑空间怎么选"的语义关联
- 关键词检索：精确匹配"5200mAh"、"2cm越障"等专业术语
- RRF 融合：取两者排序的交集优势
"""

import jieba
from rank_bm25 import BM25Okapi
from typing import List, Optional, Tuple
from langchain_core.documents import Document
from rag.vector_store import VectorStoreService
from utils.config_handler import chroma_conf
from utils.logger_handler import logger


class HybridSearchService:
    """混合检索服务"""

    def __init__(self, vector_store: VectorStoreService):
        self.vs = vector_store
        self.bm25: Optional[BM25Okapi] = None
        self._documents: List[Document] = []

        # 从配置读取混合检索参数
        hybrid_conf = chroma_conf.get("hybrid_search", {})
        self._enabled = hybrid_conf.get("enabled", True)
        self._semantic_weight = hybrid_conf.get("semantic_weight", 0.5)
        self._rrf_k = hybrid_conf.get("rrf_k", 60)

        if self._enabled:
            logger.info(f"[HybridSearch] 混合检索已启用 (语义权重: {self._semantic_weight}, RRF_K: {self._rrf_k})")

    # ────────────── 索引构建 ──────────────

    def build_index(self, documents: List[Document]):
        """从文档列表构建 BM25 索引"""
        if not self._enabled or not documents:
            return

        self._documents = documents
        corpus = [self._tokenize(d.page_content) for d in documents]
        self.bm25 = BM25Okapi(corpus)
        logger.info(f"[HybridSearch] BM25 索引构建完成，共 {len(documents)} 个文档块")

    def add_documents(self, documents: List[Document]):
        """增量添加文档，重建 BM25 索引"""
        if not self._enabled or not documents:
            return

        self._documents.extend(documents)
        corpus = [self._tokenize(d.page_content) for d in self._documents]
        self.bm25 = BM25Okapi(corpus)
        logger.info(f"[HybridSearch] BM25 索引增量更新，当前共 {len(self._documents)} 个文档块")

    # ────────────── 检索入口 ──────────────

    def search_with_scores(self, query: str, k: int = None) -> List[Tuple[Document, float]]:
        """
        混合检索入口

        返回：
        - list[(Document, score)]，score 为融合后的标准化分数 (0~1)
        """
        if k is None:
            k = chroma_conf.get("k", 3)

        if not self._enabled or self.bm25 is None:
            # 降级为纯语义检索
            return self.vs.search_with_scores(query, k=k)

        # 1. 语义向量检索（多取一些供融合）
        semantic_results = self.vs.search_with_scores(query, k=k * 2)

        # 2. BM25 关键词检索
        bm25_results = self._bm25_search(query, k * 2)

        # 3. RRF 融合排序
        fused = self._rrf_fusion(semantic_results, bm25_results, k)

        return fused

    # ────────────── 内部方法 ──────────────

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """中文分词（jieba 精确模式）"""
        return list(jieba.cut(text))

    def _bm25_search(self, query: str, k: int) -> List[Tuple[Document, float]]:
        """BM25 关键词检索"""
        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        # 取 top-k 索引
        top_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True
        )[:k]

        return [(self._documents[i], float(scores[i])) for i in top_indices]

    def _rrf_fusion(
        self,
        semantic: List[Tuple[Document, float]],
        bm25: List[Tuple[Document, float]],
        k: int,
    ) -> List[Tuple[Document, float]]:
        """
        Reciprocal Rank Fusion 融合算法

        公式：score(d) = w * R_sem(d) + (1-w) * R_bm25(d)
        其中 R(d) = 1 / (rrf_k + rank(d))
        """
        # 建立 document.page_content → rank 的映射
        def rank_map(results):
            return {doc.page_content: idx + 1 for idx, (doc, _) in enumerate(results)}

        sem_ranks = rank_map(semantic)
        bm25_ranks = rank_map(bm25)

        # 收集所有去重的 document
        seen = set()
        all_docs = []
        for doc, _ in semantic + bm25:
            if doc.page_content not in seen:
                seen.add(doc.page_content)
                all_docs.append(doc)

        # 计算融合分数
        scored = []
        for doc in all_docs:
            r_sem = sem_ranks.get(doc.page_content, k * 2)  # 未出现给最低排名
            r_bm25 = bm25_ranks.get(doc.page_content, k * 2)

            score_sem = 1.0 / (self._rrf_k + r_sem)
            score_bm25 = 1.0 / (self._rrf_k + r_bm25)

            fused = self._semantic_weight * score_sem + (1 - self._semantic_weight) * score_bm25
            scored.append((doc, fused))

        # 按融合分数降序排列
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]
