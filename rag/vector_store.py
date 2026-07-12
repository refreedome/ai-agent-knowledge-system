from langchain_chroma import Chroma
from langchain_core.documents import Document
from utils.config_handler import chroma_conf
from model.factory import embed_model
from langchain_text_splitters import RecursiveCharacterTextSplitter
from utils.path_tool import get_abs_path
from utils.file_handler import (
    pdf_loader, txt_loader, docx_loader, csv_loader, image_loader,
    listdir_with_allowed_type, get_file_md5_hex, get_file_size_mb
)
from utils.logger_handler import logger
import os


class VectorStoreService:
    def __init__(self):
        self.vector_store = Chroma(
            collection_name=chroma_conf["collection_name"],
            embedding_function=embed_model,
            persist_directory=get_abs_path(chroma_conf["persist_directory"]),
        )

        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],
            chunk_overlap=chroma_conf["chunk_overlap"],
            separators=chroma_conf["separators"],
            length_function=len,
        )

    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": chroma_conf["k"]})
        # 新增：带相似度分数的检索

    def search_with_scores(self, query: str, k: int = None) -> list[tuple[Document, float]]:
        """
        检索并返回带相似度分数的文档

        参数：
        - query: 查询文本
        - k: 返回条数（默认使用配置文件中的值）

        返回：
        - list[(Document, score)]：文档对象与相似度分数（0~1，越高越相关）
        """
        if k is None:
            k = chroma_conf["k"]
        return self.vector_store.similarity_search_with_relevance_scores(query, k=k)

    # ---- 将内部函数提取为类方法 ----
    def _get_file_documents(self, filepath: str) -> list[Document]:
        """根据文件后缀分发到对应加载器"""
        ext = os.path.splitext(filepath)[1].lower().lstrip(".")
        loaders = {
            "txt": txt_loader,
            "pdf": pdf_loader,
            "docx": docx_loader,
            "csv": csv_loader,
            "jpg": image_loader,
            "jpeg": image_loader,
            "png": image_loader,
        }
        loader = loaders.get(ext)
        if loader:
            return loader(filepath)
        return []

    def _check_md5_exists(self, md5: str) -> bool:
        md5_path = get_abs_path(chroma_conf["md5_hex_store"])
        if not os.path.exists(md5_path):
            return False
        with open(md5_path, "r", encoding="utf-8") as f:
            return any(line.strip() == md5 for line in f)

    def _save_md5(self, md5: str):
        md5_path = get_abs_path(chroma_conf["md5_hex_store"])
        with open(md5_path, "a", encoding="utf-8") as f:
            f.write(md5 + "\n")

    def load_document(self):
        """从数据文件夹内批量加载（调用提取后的方法）"""
        allowed_files_path: list[str] = listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"]),
        )

        for path in allowed_files_path:
            md5_hex = get_file_md5_hex(path)

            if self._check_md5_exists(md5_hex):
                logger.info(f"[加载知识库]{path}内容已经存在知识库内，跳过")
                continue

            try:
                documents = self._get_file_documents(path)

                if not documents:
                    logger.warning(f"[加载知识库]{path}内没有有效文本内容，跳过")
                    continue

                split_document = self.spliter.split_documents(documents)

                if not split_document:
                    logger.warning(f"[加载知识库]{path}分片后没有有效文本内容，跳过")
                    continue

                self.vector_store.add_documents(split_document)
                self._save_md5(md5_hex)
                logger.info(f"[加载知识库]{path} 内容加载成功")
            except Exception as e:
                logger.error(f"[加载知识库]{path}加载失败：{str(e)}", exc_info=True)
                continue



    def add_document(self, filepath: str) -> dict:
        """
        单文件入库（供 DocumentUploadTool 调用）

        参数：
        - filepath: 文件绝对路径

        返回：
        - dict 包含处理结果统计
        """
        filename = os.path.basename(filepath)

        # 1. MD5 去重
        md5 = get_file_md5_hex(filepath)
        if not md5:
            return {"success": False, "error": "无法计算文件 MD5", "filename": filename}
        if self._check_md5_exists(md5):
            return {"success": False, "error": "文件已存在知识库中，请勿重复上传", "filename": filename}

        # 2. 解析文件
        documents = self._get_file_documents(filepath)
        if not documents:
            return {"success": False, "error": "文件无有效文本内容", "filename": filename}

        # 3. 分块
        split_docs = self.spliter.split_documents(documents)
        if not split_docs:
            return {"success": False, "error": "分片后无有效文本", "filename": filename}

        # 4. 向量化入库
        self.vector_store.add_documents(split_docs)

        # 5. 记录 MD5
        self._save_md5(md5)

        return {
            "success": True,
            "filename": filename,
            "chunks": len(split_docs),
            "characters": sum(len(d.page_content) for d in split_docs),
        }

if __name__ == '__main__':
    vs = VectorStoreService()

    vs.load_document()

    retriever = vs.get_retriever()

    res = retriever.invoke("迷路")
    for r in res:
        print(r.page_content)
        print("-"*20)


