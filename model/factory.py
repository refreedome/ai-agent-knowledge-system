# 导入抽象基类和抽象方法装饰器
from abc import ABC, abstractmethod

# 导入Optional类型提示
from typing import Optional

# 导入嵌入模型的基类
from langchain_core.embeddings import Embeddings

# 导入聊天模型的基类
from langchain_community.chat_models.tongyi import BaseChatModel

# 导入DashScope（阿里云）的嵌入模型
from langchain_community.embeddings import DashScopeEmbeddings

# 导入通义千问聊天模型
from langchain_community.chat_models.tongyi import ChatTongyi

# 导入RAG配置
from utils.config_handler import rag_conf


class BaseModelFactory(ABC):
    """
    基础模型工厂类（抽象类）
    
    工厂模式：用于统一创建和管理模型实例
    ABC = Abstract Base Class（抽象基类）
    """
    
    @abstractmethod
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """
        抽象方法：生成模型实例
        
        子类必须实现这个方法
        
        返回：
        - 嵌入模型或聊天模型，或者None
        """
        pass


class ChatModelFactory(BaseModelFactory):
    """
    聊天模型工厂类
    
    负责创建聊天模型实例（用于对话）
    """
    
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """
        生成聊天模型实例

        返回：
        - ChatTongyi模型实例（通义千问）

        ⚠️ 必须显式开启 streaming=True：
        ChatTongyi 默认 streaming=False，此时它内部走非流式请求，
        整段生成完才返回一条完整消息——即使上层用 LangGraph 的
        stream_mode="messages" 也只能拿到「整条消息」而不是 token 增量，
        最终前端表现就是「一块一块蹦」而不是逐字输出。
        （实测：streaming=True → 10 个增量片段；默认 → 1 个整段片段）
        """
        # 从配置中读取模型名称，创建对应的聊天模型（开启流式）
        return ChatTongyi(model=rag_conf["chat_model_name"], streaming=True)


class EmbeddingsFactory(BaseModelFactory):
    """
    嵌入模型工厂类
    
    负责创建嵌入模型实例（用于将文本转为向量）
    """
    
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """
        生成嵌入模型实例
        
        返回：
        - DashScopeEmbeddings模型实例（阿里云文本嵌入模型）
        """
        # 从配置中读取嵌入模型名称，创建对应的嵌入模型
        return DashScopeEmbeddings(model=rag_conf["embedding_model_name"])


# 创建全局的聊天模型实例
# 这样其他模块可以直接导入使用，无需重复创建
chat_model = ChatModelFactory().generator()

# 创建全局的嵌入模型实例
embed_model = EmbeddingsFactory().generator()
