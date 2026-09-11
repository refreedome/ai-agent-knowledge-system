import sys
import os
# 将项目根目录加入模块搜索路径（防止直接运行子模块时 ImportError）
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agent.tools.registry import registry
from langchain.agents import create_agent
from model.factory import chat_model
from utils.prompt_loader import load_system_prompts
from agent.tools.middleware import create_default_middleware
from database.session_manager import session_manager
from database.long_term_memory import long_term_memory
from utils.qa_cache import qa_cache
from utils.logger_handler import logger
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage


class ReactAgent:
    def __init__(self):
        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompts(),
            tools=registry.get_all_tools(),
            middleware=create_default_middleware(),
        )

    def execute_stream(self, query: str, session_id: str = None, user_id: str = "default"):
        if not session_id:
            session_id = session_manager.create_session(user_id=user_id)

        # 短期记忆：滑动窗口 + 字符级裁剪后的历史（上下文裁剪）
        history = session_manager.get_context_window(session_id)

        # 会话已过期 → 自动重建
        if not history and session_id not in session_manager._sessions:
            session_id = session_manager.create_session(user_id=user_id)
            history = []

        # 长期记忆：跨会话的偏好事实（按用户隔离），注入为系统消息
        memories = long_term_memory.recall(user_id)
        messages = []
        if memories:
            mem_text = "；".join(m["fact"] for m in memories)
            messages.append({
                "role": "system",
                "content": f"【用户长期记忆】{mem_text}。回答时可结合这些用户偏好。",
            })
        messages.extend(history)
        messages.append({"role": "user", "content": query})

        input_dict = {"messages": messages}

        # ── 热点问题缓存：命中直接回放，跳过 LLM 调用 ──
        # 缓存键带上 user_id：回答里包含【用户长期记忆】个性化内容与角色相关工具结果，
        # 若只按问题文本缓存，会把 A 用户的个性化答案串给 B 用户。
        cache_key = f"{user_id}::{query}"
        cached_answer = qa_cache.get(cache_key)
        if cached_answer is not None:
            session_manager.add_pair(session_id, query, cached_answer)
            logger.info(f"[QACache] 命中缓存: {query[:30]}... (size={qa_cache.stats()['size']})")
            # 命中缓存同样要走事件协议，前端才拿得到 token 事件（分片回放保留打字机观感）
            for piece in qa_cache.iter_chunks(cached_answer):
                yield {"type": "token", "content": piece, "turn": 0}
            return

        full_response = ""
        final_answer = ""
        turn = 0  # 第几轮模型输出（ReAct 会多轮：思考+调工具 → 再思考 → 最终回答）
        try:
            # 同时订阅两种流（LangGraph 多模式，产出 (mode, payload) 元组）：
            #   - "messages"：LLM 逐 token 增量 → **真流式的唯一来源**
            #   - "values"  ：节点结束后的完整 state 快照 → 取最终答案 + 判断本轮是否调了工具
            #
            # 事件协议（前端按此渲染「思考折叠区 + 答案区」）：
            #   {"type":"token","content":str,"turn":N}  模型文本增量
            #   {"type":"tool","turn":N,"name":str}      第 N 轮调用了工具 → N 轮属于「思考」
            #   {"type":"error","content":str}           异常
            for mode, chunk in self.agent.stream(
                input_dict,
                stream_mode=["messages", "values"],
                context={"report": False},
            ):
                if mode == "messages":
                    # payload 是 (message_chunk, metadata)
                    msg_chunk = chunk[0] if isinstance(chunk, tuple) else chunk
                    # 只转发「模型产出的文本增量」，跳过工具结果（ToolMessage）等
                    if isinstance(msg_chunk, AIMessageChunk):
                        text = msg_chunk.content
                        if text:
                            yield {"type": "token", "content": str(text), "turn": turn}

                elif mode == "values":
                    msgs = chunk.get("messages") or []
                    # 最后一条模型消息的完整内容 = 最终答案候选（比拼接增量更可靠）
                    for m in reversed(msgs):
                        if isinstance(m, AIMessage) and m.content:
                            final_answer = str(m.content).strip()
                            break
                    # 快照最后一条是工具结果 → 本轮模型输出其实是在「思考并调工具」，
                    # 通知前端把本轮文本归入思考区，然后进入下一轮
                    if msgs and isinstance(msgs[-1], ToolMessage):
                        yield {
                            "type": "tool",
                            "turn": turn,
                            "name": getattr(msgs[-1], "name", "") or "tool",
                        }
                        turn += 1

            full_response = final_answer or ""
            session_manager.add_pair(session_id, query, full_response)

            # 长期记忆：从用户输入中抽取偏好事实并持久化（按用户隔离）
            for fact in long_term_memory.extract_facts(query):
                long_term_memory.remember(user_id, fact)

            # ── 热点问题缓存：写入（同一用户 + 同一问题在 TTL 内直接命中）──
            if full_response.strip():
                qa_cache.put(cache_key, full_response.strip())
                logger.info(f"[QACache] 已缓存: {query[:30]}... (size={qa_cache.stats()['size']})")

        except Exception as e:
            logger.error(f"[ReactAgent] 执行失败: {str(e)}", exc_info=True)
            yield {"type": "error", "content": f"处理异常: {str(e)}"}


if __name__ == '__main__':
    agent = ReactAgent()
    session_id = session_manager.create_session()
    print(f"会话ID: {session_id}\n")
    print("=" * 50)
    print("智能客服已启动，输入问题开始对话（输入 'exit' 退出）")
    print("=" * 50)

    while True:
        try:
            q = input("\n用户: ").strip()
            if not q:
                continue
            if q.lower() in ("exit", "quit", "q"):
                print("再见！")
                break

            print("助手: ", end="", flush=True)
            for event in agent.execute_stream(q, session_id=session_id):
                if isinstance(event, dict):
                    if event.get("type") == "token":
                        print(event.get("content", ""), end="", flush=True)
                else:
                    print(event, end="", flush=True)
            print()

        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break
