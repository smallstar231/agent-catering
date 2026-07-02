# Streamlit 入口模块
# 功能：构建 Web 聊天界面，连接 ReactAgent，处理用户输入和流式输出
# 设计参考 DeepSeek Web 端会话管理：自动存档、历史加载、当前会话名展示
# 运行：`streamlit run app.py`
# 依赖：agent/react_agent.py（Agent）、utils/file_handler.py（会话存档）

import streamlit as st                  # Streamlit Web 框架
from agent.react_agent import ReactAgent  # ReAct Agent
from utils.file_handler import save_session_to_disk, load_saved_sessions, load_session_messages  # 会话存档

# ---- 页面配置 ----
st.set_page_config(page_title="智扫通 · 智能客服", page_icon="🤖")
st.title("🤖 智扫通机器人智能客服")
st.caption("基于 LangChain ReAct Agent + RAG 检索增强")
st.divider()

# ---- 初始化会话状态 ----
if "agent" not in st.session_state:
    st.session_state["agent"] = ReactAgent()

if "messages" not in st.session_state:
    st.session_state["messages"] = []

if "round_count" not in st.session_state:
    st.session_state["round_count"] = 0

# current_session_id：当前会话的唯一 ID
# - None 表示全新未保存的会话
# - 有值表示已有存档，后续保存会覆盖更新同一文件
if "current_session_id" not in st.session_state:
    st.session_state["current_session_id"] = None

# session_title：当前会话的显示名称，取自第一条用户消息
if "session_title" not in st.session_state:
    st.session_state["session_title"] = "新对话"


# ========== 自动保存当前会话 ==========
def auto_save_current_session():
    """
    将当前会话保存到磁盘（覆盖更新模式）
    新会话（无 session_id）会生成新 ID，后续使用同一 ID 覆盖更新
    """
    if not st.session_state["messages"]:
        return

    filepath, sid = save_session_to_disk(
        st.session_state["messages"],
        st.session_state["round_count"],
        session_id=st.session_state.get("current_session_id"),
    )

    # 新会话首次保存时，记录生成的 session_id
    if sid and not st.session_state.get("current_session_id"):
        st.session_state["current_session_id"] = sid

    # 从第一条用户消息提取标题（仅首次设置）
    if st.session_state.get("session_title") in (None, "新对话"):
        for msg in st.session_state["messages"]:
            if msg["role"] == "user":
                title = msg["content"][:30]
                if len(msg["content"]) > 30:
                    title += "..."
                st.session_state["session_title"] = title
                break


# ========== 加载历史会话到当前页面 ==========
def load_session(session_data: dict):
    """将历史会话加载到当前聊天区，覆盖当前内容"""
    # 先自动保存当前会话
    auto_save_current_session()

    # 读取历史会话的完整消息
    messages = load_session_messages(session_data["filepath"])
    if messages is None:
        st.error("无法加载此会话")
        return

    # 替换当前聊天内容
    st.session_state["messages"] = messages
    st.session_state["round_count"] = session_data["round_count"]
    st.session_state["current_session_id"] = session_data["id"]
    st.session_state["session_title"] = session_data["title"]
    st.rerun()


# ---- 侧边栏 ----
with st.sidebar:
    st.markdown("## 💬 会话状态")

    # ---- 当前会话名称框 ----
    session_title_display = st.session_state.get("session_title", "新对话")
    st.markdown(
        f"<div style='border:1px solid #555; border-radius:8px; padding:10px 12px; "
        f"margin-bottom:12px; font-size:14px;'>"
        f"📄 {session_title_display}</div>",
        unsafe_allow_html=True,
    )

    # ---- 轮数 + 进度条 ----
    st.markdown(f"**轮数：{st.session_state['round_count']}**")
    progress = min(st.session_state["round_count"] / 30, 1.0)
    st.progress(progress, text=f"{st.session_state['round_count']} / 30")

    # ---- 状态提示 ----
    if st.session_state["round_count"] >= 30:
        st.warning("🚨 对话过长，强烈建议开启新对话")
    elif st.session_state["round_count"] >= 10:
        st.info("💡 建议开启新对话以保持最佳效果")

    st.divider()

    # ---- 新对话按钮 ----
    if st.button("🔄 新对话", use_container_width=True):
        # 先存档当前会话
        auto_save_current_session()
        # 清空当前会话
        st.session_state["messages"] = []
        st.session_state["round_count"] = 0
        st.session_state["current_session_id"] = None
        st.session_state["session_title"] = "新对话"
        st.rerun()

    st.divider()

    # ---- 历史会话列表（可点击加载）----
    st.markdown("## 📂 历史会话")
    saved_sessions = load_saved_sessions()

    if not saved_sessions:
        st.caption("暂无历史会话记录")

    for session in saved_sessions:
        # 跳过当前正在编辑的会话（避免在历史中重复显示自己）
        if session["id"] == st.session_state.get("current_session_id"):
            continue

        # 每个历史会话是一个可点击的按钮
        display_time = session.get("updated_at", session["created_at"])
        btn_label = (f"{session['title']}\n"
                     f"🕐 {display_time}  ·  {session['round_count']}轮")
        if st.button(btn_label, key=f"hist_{session['id']}", use_container_width=True):
            load_session(session)


# ---- 多轮警告（inline，聊天区域顶部）----
round_count_before = st.session_state["round_count"]
if round_count_before >= 10 and round_count_before % 10 == 0:
    if round_count_before >= 30:
        st.warning(f"🚨 当前对话已进行 {round_count_before} 轮，强烈建议开启新对话。")
    else:
        st.info(f"💡 当前对话已进行 {round_count_before} 轮，建议开启新对话。")

# ---- 渲染历史消息 ----
for message in st.session_state["messages"]:
    st.chat_message(message["role"]).write(message["content"])

# ---- 接收用户输入 ----
prompt = st.chat_input()

# ---- 处理用户输入 ----
if prompt:
    # 显示用户消息
    st.chat_message("user").write(prompt)
    st.session_state["messages"].append({"role": "user", "content": prompt})

    response_messages: list[str] = []

    with st.spinner("智能客服思考中..."):
        history = st.session_state["messages"][:-1]

        res_stream = st.session_state["agent"].execute_stream(
            prompt,
            history=history,
        )

        def stream_generator(generator, cache_list):
            for chunk in generator:
                cache_list.append(chunk)
                for char in chunk:
                    yield char

        st.chat_message("assistant").write_stream(
            stream_generator(res_stream, response_messages)
        )

        st.session_state["messages"].append(
            {"role": "assistant", "content": "".join(response_messages)}
        )
        st.session_state["round_count"] += 1

        # ★ 每轮对话后自动保存到磁盘
        auto_save_current_session()

        st.rerun()
