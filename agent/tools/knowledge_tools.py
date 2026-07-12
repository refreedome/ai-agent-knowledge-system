"""
知识库相关工具

包含：
1. 知识检索工具 - 从向量库搜索相关信息
2. 文档上传工具 - 上传新文档到知识库
"""

# 添加项目根目录到Python路径（必须在项目导入之前！）
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from utils.logger_handler import logger

from rag.vector_store import VectorStoreService
from utils.config_handler import chroma_conf
from utils.file_handler import get_file_size_mb

from agent.tools.base_tool import BaseTool, ToolResult
from rag.rag_service import RagSummarizeService


class KnowledgeSearchTool(BaseTool):
    """
    知识检索工具

    从企业知识库中检索与问题相关的资料
    """

    def __init__(self):
        """初始化工具"""
        super().__init__(
            name="knowledge_search",
            description="从企业知识库中检索专业资料，用于回答产品、技术、政策等专业问题"
        )
        # 创建RAG服务实例
        self.rag_service = RagSummarizeService()

    def execute(self, query: str, top_k: int = None, **kwargs) -> ToolResult:
        """
        执行知识检索

        参数：
        - query: 检索词（用户的问题）
        - top_k: 返回的参考来源数量（默认从 config/chroma.yml 读取）

        返回：
        - ToolResult，包含 answer（LLM回答）和 sources（参考来源列表）
        """
        try:
            # 参数验证
            if not query or not query.strip():
                return ToolResult.fail("检索词不能为空")
            if len(query) > 500:
                return ToolResult.fail("检索词过长，请控制在500字以内")

            # 从配置文件读取 top_k，调用方也可覆盖
            if top_k is None:
                top_k = chroma_conf["k"]
            if not isinstance(top_k, int) or top_k < 1 or top_k > 10:
                return ToolResult.fail("top_k 必须是1~10之间的整数")

            query = query.strip()

            # 1. 获取 LLM 生成的回答
            answer = self.rag_service.rag_summarize(query)

            # 2. 获取来源文档（统一使用 search_with_scores）
            docs_with_scores = self.rag_service.vector_store.search_with_scores(query, k=top_k)
            logger.info(f"[KnowledgeSearchTool] 检索到 {len(docs_with_scores)} 条参考来源")

            sources = []
            for doc, score in docs_with_scores:
                source_name = doc.metadata.get("source", "未知来源")
                logger.info(f"[KnowledgeSearchTool] 来源: {source_name}, 分数: {score:.4f}")
                sources.append({
                    "content": doc.page_content[:200],
                    "source": source_name,
                    "score": round(score, 4),
                })

            return ToolResult.ok({
                "answer": answer,
                "sources": sources
            })

        except Exception as e:
            logger.error(f"[KnowledgeSearchTool] 检索失败: {str(e)}", exc_info=True)
            return ToolResult.fail(f"检索失败: {str(e)}")

    def validate_params(self, **kwargs) -> bool:
        """验证参数"""
        query = kwargs.get("query", "")
        return isinstance(query, str) and len(query) > 0


class DocumentUploadTool(BaseTool):
    """
    文档上传工具

    支持 TXT / PDF / DOCX / CSV / 图片(JPG/PNG)
    自动完成：格式校验 → 解析 → 分块 → 向量化入库
    """

    def __init__(self):
        """初始化工具"""
        super().__init__(
            name="document_upload",
            description="上传文档到企业知识库（支持 txt/pdf/docx/csv/jpg/png），自动解析并入库"
        )
        self.vector_service = VectorStoreService()
        # 支持的文件类型从配置读取
        self.allowed_types = chroma_conf["allow_knowledge_file_type"]
        self.max_size_mb = chroma_conf.get("max_file_size_mb", 10)

    def execute(self, file_path: str, **kwargs) -> ToolResult:
        """
        执行文档上传

        参数：
        - file_path: 文件路径（绝对路径或相对路径）

        返回：
        - ToolResult，包含处理结果统计
        """
        try:
            # 1. 参数验证
            if not file_path or not file_path.strip():
                return ToolResult.fail("文件路径不能为空")

            file_path = os.path.abspath(file_path.strip())

            # 2. 文件存在性验证
            if not os.path.exists(file_path):
                return ToolResult.fail(f"文件不存在: {file_path}")
            if not os.path.isfile(file_path):
                return ToolResult.fail(f"路径不是文件: {file_path}")

            # 3. 文件格式验证
            ext = os.path.splitext(file_path)[1].lower().lstrip(".")
            if ext not in self.allowed_types:
                return ToolResult.fail(
                    f"不支持的文件格式: .{ext}，支持: {', '.join(self.allowed_types)}"
                )

            # 4. 文件大小验证
            file_size_mb = get_file_size_mb(file_path)
            if file_size_mb > self.max_size_mb:
                return ToolResult.fail(
                    f"文件过大 ({file_size_mb:.1f}MB)，超过限制 {self.max_size_mb}MB"
                )

            # 5. 入库处理
            result = self.vector_service.add_document(file_path)

            if result["success"]:
                return ToolResult.ok({
                    "filename": result["filename"],
                    "chunks": result["chunks"],
                    "characters": result["characters"],
                    "file_size_mb": round(file_size_mb, 2),
                    "format": ext,
                })
            else:
                return ToolResult.fail(result["error"])

        except Exception as e:
            logger.error(f"[DocumentUploadTool] 上传失败: {str(e)}", exc_info=True)
            return ToolResult.fail(f"文档上传处理异常: {str(e)}")

    def validate_params(self, **kwargs) -> bool:
        """验证参数"""
        file_path = kwargs.get("file_path", "")
        return isinstance(file_path, str) and len(file_path.strip()) > 0

# 自动注册工具
def register_knowledge_tools():
    """注册知识库相关工具"""
    from .registry import registry

    registry.register(KnowledgeSearchTool(), required_role="user")
    registry.register(DocumentUploadTool(), required_role="admin")


# 测试代码
if __name__ == '__main__':
    # 注册工具
    register_knowledge_tools()

    # 列出工具
    from .registry import registry
    tools = registry.list_tools("user")
    print("可用工具:")
    for tool in tools:
        print(f"  - {tool['name']}: {tool['description']}")

    # 测试知识检索
    search_tool = registry.get_tool("knowledge_search")
    if search_tool:
        print("\n测试知识检索...")
        result = search_tool.execute("什么是RAG技术？")
        print(f"结果: {result.to_string()[:200]}...")
