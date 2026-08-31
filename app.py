import time

import streamlit as st

from agent.react_agent import ReactAgent

st.set_page_config(page_title="智扫通机器人智能客服", page_icon="🤖")

# 标题
st.title("🤖 智扫通机器人智能客服")
st.divider()

# 会话级单例：Agent 与消息历史
if "agent" not in st.session_state:
    st.session_state["agent"] = ReactAgent()

if "messages" not in st.session_state:
    st.session_state["messages"] = []

# 渲染历史消息
for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 用户输入提示词
if prompt := st.chat_input("请输入您的问题…"):
    # 追加用户消息
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 流式生成回答：占位符节流增量更新
    # 节流原因：每次更新需重渲染累积全文，回答越长单次渲染越慢，
    # 若 LLM 输出快于前端渲染会积压 delta，导致"卡顿后突然跳变"
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        last_render = 0.0
        for chunk in st.session_state["agent"].execute_stream(prompt):
            full_response += chunk
            now = time.time()
            # 最多每 0.15s 渲染一次：视觉仍流畅，渲染压力可控
            if now - last_render >= 0.15:
                placeholder.markdown(full_response + "▌")
                last_render = now
        # 最终完整渲染（去掉光标）
        placeholder.markdown(full_response)

    # 保存完整回答（下次脚本重跑时从历史渲染）
    st.session_state["messages"].append({"role": "assistant", "content": full_response})
