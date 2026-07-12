
"""
总结服务类：用户提问，搜索参考资料，将提问和参考资料提交给模型，让模型总结回复
"""
from utils.logger_handler import (logger)
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from rag.hybrid_search import HybridSearchService
from rag.vector_store import VectorStoreService
from utils.prompt_loader import load_rag_prompts
from langchain_core.prompts import PromptTemplate
from model.factory import chat_model
from utils.config_handler import chroma_conf



class RagSummarizeService(object):
    def __init__(self):
        self.vector_store = VectorStoreService()
        self.hybrid_search = HybridSearchService(self.vector_store)
        self.prompt_text = load_rag_prompts()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = chat_model
        self.chain = self._init_chain()

        # 从 ChromaDB 拉取已有文档，构建 BM25 索引
        self._init_bm25_index()

    def _init_bm25_index(self):
        """从向量库拉取所有文档，构建 BM25 索引"""
        try:
            # ChromaDB 的 get() 返回存储的所有文档
            all_data = self.vector_store.vector_store.get()
            if all_data and all_data.get("documents"):
                from langchain_core.documents import Document
                # 从元数据恢复 source 信息
                metadatas = all_data.get("metadatas", [{}] * len(all_data["documents"]))
                docs = [
                    Document(page_content=text, metadata=meta or {})
                    for text, meta in zip(all_data["documents"], metadatas)
                ]
                self.hybrid_search.build_index(docs)
                logger.info(f"[RagSummarize] BM25 索引已加载，共 {len(docs)} 个文档块")
            else:
                logger.warning("[RagSummarize] 向量库为空，BM25 索引未构建")
        except Exception as e:
            logger.warning(f"[RagSummarize] BM25 索引构建失败（向量库可能为空）: {e}")


    def _init_chain(self):
        chain = self.prompt_template |  self.model | StrOutputParser()
        return chain

    def retriever_docs(self, query: str) -> list[Document]:
        """使用混合检索，返回 Document 列表"""
        docs_with_scores = self.hybrid_search.search_with_scores(query, k=chroma_conf["k"])
        return [doc for doc, _ in docs_with_scores]

    def rag_summarize(self, query: str) -> str:

        context_docs = self.retriever_docs(query)

        context = ""
        counter = 0
        for doc in context_docs:
            counter += 1
            context += f"【参考资料{counter}】: 参考资料：{doc.page_content} | 参考元数据：{doc.metadata}\n"

        return self.chain.invoke(
            {
                "input": query,
                "context": context,
            }
        )


if __name__ == '__main__':
    rag = RagSummarizeService()

    print(rag.rag_summarize("小户型适合哪些扫地机器人"))
