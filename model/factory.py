# -*- coding: utf-8 -*-
"""
模型工厂：统一创建「对话模型」与「嵌入模型」，并按配置切换供应商。

配置见 config/rag.yml：
    chat_provider:      dashscope（默认，通义千问）| deepseek（OpenAI 兼容协议）
    embedding_provider: dashscope（默认，text-embedding-v4）| fastembed（本地 ONNX，免 API key）

为什么把供应商收敛到工厂这一层：
    换模型供应商本质上只是 base_url + model + key 三件事。收敛到工厂之后，
    Agent / RAG / API 各层完全无感——这也是「模型层不写死、可切换」的落点。
    供应商相关依赖采用**延迟导入**：用 A 家时不需要装 B 家的包。

⚠️ 两个必知前提（都是踩过的坑）：
    1. 无论哪家都必须显式 streaming=True。ChatTongyi 默认 streaming=False，
       此时它内部走非流式请求，整段生成完才返回一条完整消息；即使上层用
       LangGraph 的 stream_mode="messages" 也只能拿到「整条消息」，
       前端表现就是「一块一块蹦」而不是逐字输出。
       （实测：streaming=True → 10 个增量片段；默认 → 1 个整段片段）
    2. 切换 embedding 供应商会让**已有向量库失效**（维度与向量空间都不同），
       必须重新入库；所以 embedding_provider 一旦定下就不要随意改。
"""

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

# 导入RAG配置
from utils.config_handler import rag_conf
from utils.logger_handler import logger


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
    聊天模型工厂类（对话用，支持 dashscope / deepseek 切换）
    """

    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """
        生成聊天模型实例

        返回：
        - ChatTongyi 实例（provider=dashscope，通义千问）
        - ChatOpenAI 实例（provider=deepseek，OpenAI 兼容协议）

        streaming=True 的意义见模块开头说明。
        """
        provider = str(rag_conf.get("chat_provider", "dashscope")).lower()
        model_name = rag_conf["chat_model_name"]

        if provider == "deepseek":
            # 延迟导入：只有真的用 DeepSeek 时才需要 langchain-openai
            from langchain_openai import ChatOpenAI

            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "chat_provider=deepseek 需要设置环境变量 DEEPSEEK_API_KEY；"
                    "若想用通义千问，请把 config/rag.yml 的 chat_provider 改回 dashscope"
                )
            logger.info(f"[ModelFactory] 对话模型: DeepSeek({model_name}) streaming=True")
            return ChatOpenAI(
                model=model_name,
                base_url=rag_conf.get("deepseek_base_url", "https://api.deepseek.com"),
                api_key=api_key,
                streaming=True,
                temperature=0.7,
            )

        # 默认：通义千问（DashScope）
        from langchain_community.chat_models.tongyi import ChatTongyi

        logger.info(f"[ModelFactory] 对话模型: ChatTongyi({model_name}) streaming=True")
        return ChatTongyi(model=model_name, streaming=True)


class EmbeddingsFactory(BaseModelFactory):
    """
    嵌入模型工厂类（文本转向量用，支持 dashscope / fastembed 切换）
    """

    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """
        生成嵌入模型实例

        返回：
        - DashScopeEmbeddings（provider=dashscope，需 DASHSCOPE_API_KEY）
        - FastEmbedEmbeddings（provider=fastembed，本地 ONNX 推理，免 API key）
        """
        provider = str(rag_conf.get("embedding_provider", "dashscope")).lower()
        model_name = rag_conf["embedding_model_name"]

        if provider == "fastembed":
            # 本地 ONNX 推理，首次使用自动下载权重（Dockerfile 已配 HF 国内镜像）
            # 优点：不依赖外部 Embedding API、无额外 key、数据不出境、无 torch 大依赖
            from langchain_community.embeddings import FastEmbedEmbeddings

            logger.info(f"[ModelFactory] 嵌入模型: FastEmbed({model_name}) 本地推理")
            return FastEmbedEmbeddings(model_name=model_name)

        from langchain_community.embeddings import DashScopeEmbeddings

        logger.info(f"[ModelFactory] 嵌入模型: DashScope({model_name})")
        return DashScopeEmbeddings(model=model_name)


# 创建全局的聊天模型实例
# 这样其他模块可以直接导入使用，无需重复创建
chat_model = ChatModelFactory().generator()

# 创建全局的嵌入模型实例
embed_model = EmbeddingsFactory().generator()
