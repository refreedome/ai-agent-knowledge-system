# 导入抽象基类和抽象方法装饰器
from abc import ABC, abstractmethod

# 导入Optional类型提示
from typing import Optional

# 导入环境变量读取
import os

# 导入嵌入模型的基类
from langchain_core.embeddings import Embeddings

# 导入聊天模型的基类
from langchain_core.language_models.chat_models import BaseChatModel

# 导入OpenAI兼容聊天模型（DeepSeek 提供 OpenAI 兼容 API，只需指定 base_url）
from langchain_openai import ChatOpenAI

# 导入本地 ONNX 嵌入模型（FastEmbed：本地推理，无需外部 Embedding API / 额外 key）
from langchain_community.embeddings import FastEmbedEmbeddings

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
        - ChatOpenAI 实例（DeepSeek，OpenAI 兼容协议）
        """
        # DeepSeek 提供 OpenAI 兼容的 API，直接用 ChatOpenAI + base_url 即可无缝切换
        # （换回通义/智谱/Kimi 等也只是改 base_url + model + key 的事）
        # streaming=True：开启 token 级流式输出，支撑 SSE / 打字机效果
        return ChatOpenAI(
            model=rag_conf["chat_model_name"],
            base_url="https://api.deepseek.com",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            streaming=True,
            temperature=0.7,
        )


class EmbeddingsFactory(BaseModelFactory):
    """
    嵌入模型工厂类

    负责创建嵌入模型实例（用于将文本转为向量）
    """

    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """
        生成嵌入模型实例

        返回：
        - FastEmbedEmbeddings 实例（本地 BGE ONNX，免 API key）
        """
        # FastEmbed：本地 ONNX 推理，首次使用时自动从 HuggingFace 下载模型
        # （Dockerfile 已设置 HF_ENDPOINT=https://hf-mirror.com 走国内镜像）
        # 优点：① 不依赖外部 Embedding API，无额外 key；② 数据不出境；③ 无 torch 大依赖
        return FastEmbedEmbeddings(model_name=rag_conf["embedding_model_name"])


# 创建全局的聊天模型实例
# 这样其他模块可以直接导入使用，无需重复创建
chat_model = ChatModelFactory().generator()

# 创建全局的嵌入模型实例
embed_model = EmbeddingsFactory().generator()
