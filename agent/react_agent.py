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
from utils.logger_handler import logger
from langchain_core.messages import AIMessage


class ReactAgent:
    def __init__(self):
        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompts(),
            tools=registry.get_all_tools(),
            middleware=create_default_middleware(),
        )

    def execute_stream(self, query: str, session_id: str = None):
        if not session_id:
            session_id = session_manager.create_session()

        history = session_manager.get_messages(session_id)

        # 会话已过期 → 自动重建
        if not history and session_id not in session_manager._sessions:
            session_id = session_manager.create_session()
            history = []

        input_dict = {
            "messages": [
                *history,
                {"role": "user", "content": query},
            ]
        }

        full_response = ""
        try:
            for chunk in self.agent.stream(input_dict, stream_mode="values", context={"report": False}):
                latest_message = chunk["messages"][-1]

                if not isinstance(latest_message, AIMessage):
                    continue

                if latest_message.content:
                    content = latest_message.content.strip() + "\n"
                    full_response += content
                    yield content

            session_manager.add_pair(session_id, query, full_response.strip())

        except Exception as e:
            logger.error(f"[ReactAgent] 执行失败: {str(e)}", exc_info=True)
            yield f"处理异常: {str(e)}"


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
            for chunk in agent.execute_stream(q, session_id=session_id):
                print(chunk, end="", flush=True)
            print()

        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break
