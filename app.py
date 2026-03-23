"""
URRobot-Agent Streamlit 界面
实时显示任务列表、物体状态和机械臂状态
"""

import streamlit as st
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from robot.task_persistence import TaskPersistence, Task, TaskStatus
from robot.multi_arm_manager import MultiArmManager, ArmStatus
from robot.lead_agent import create_lead_agent, LeadAgent


TASKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tasks")
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "object_positions.json")


def get_task_persistence() -> TaskPersistence:
    if "task_persistence" not in st.session_state:
        st.session_state.task_persistence = TaskPersistence(TASKS_DIR)
    return st.session_state.task_persistence


def get_multi_arm_manager() -> MultiArmManager:
    if "multi_arm_manager" not in st.session_state:
        st.session_state.multi_arm_manager = MultiArmManager(CONFIG_PATH, use_simulator=True)
    return st.session_state.multi_arm_manager


def get_lead_agent() -> LeadAgent:
    if "lead_agent" not in st.session_state:
        st.session_state.lead_agent = create_lead_agent(
            config_path=CONFIG_PATH,
            stream_callback=None
        )
        st.session_state.chat_messages = []
    return st.session_state.lead_agent


def load_object_config() -> Dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"加载配置文件失败: {e}")
        return {"objects": {}, "robots": {}}


def get_status_color(status: str) -> str:
    colors = {
        "pending": "#9E9E9E",
        "ready": "#2196F3",
        "running": "#FF9800",
        "completed": "#4CAF50",
        "failed": "#F44336",
        "blocked": "#9C27B0",
        "idle": "#607D8B",
        "moving": "#FF9800",
        "working": "#2196F3",
        "error": "#F44336",
        "installed": "#4CAF50",
        "stored": "#2196F3",
        "ready": "#8BC34A",
        "available": "#607D8B",
        "in_use": "#FF9800",
    }
    return colors.get(status.lower(), "#9E9E9E")


def get_status_emoji(status: str) -> str:
    emojis = {
        "pending": "⏳",
        "ready": "🟢",
        "running": "🔄",
        "completed": "✅",
        "failed": "❌",
        "blocked": "🚫",
        "idle": "💤",
        "moving": "🏃",
        "working": "🔧",
        "error": "⚠️",
    }
    return emojis.get(status.lower(), "❓")


def render_task_card(task: Task):
    status_color = get_status_color(task.status)
    status_emoji = get_status_emoji(task.status)
    
    with st.container():
        cols = st.columns([0.1, 0.15, 0.5, 0.25])
        
        with cols[0]:
            st.markdown(f"<span style='font-size: 1.5em;'>{status_emoji}</span>", unsafe_allow_html=True)
        
        with cols[1]:
            st.markdown(f"<span style='color: {status_color}; font-weight: bold;'>{task.status.upper()}</span>", unsafe_allow_html=True)
        
        with cols[2]:
            st.markdown(f"**{task.name}**")
            if task.description:
                st.caption(task.description[:50] + "..." if len(task.description) > 50 else task.description)
        
        with cols[3]:
            if task.assigned_arm:
                st.caption(f"🤖 {task.assigned_arm}")
            if task.skill_name:
                st.caption(f"📋 {task.skill_name}")
        
        st.divider()


def render_tasks_section():
    st.subheader("📋 任务列表")
    
    tp = get_task_persistence()
    tasks = tp.list_all()
    
    if not tasks:
        st.info("暂无任务")
        return
    
    status_filter = st.multiselect(
        "筛选状态",
        options=["pending", "ready", "running", "completed", "failed", "blocked"],
        default=["pending", "ready", "running"],
        key="task_status_filter"
    )
    
    filtered_tasks = [t for t in tasks if t.status in status_filter] if status_filter else tasks
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总任务", len(tasks))
    with col2:
        completed = len([t for t in tasks if t.status == "completed"])
        st.metric("已完成", completed)
    with col3:
        running = len([t for t in tasks if t.status == "running"])
        st.metric("进行中", running)
    with col4:
        pending = len([t for t in tasks if t.status in ["pending", "ready", "blocked"]])
        st.metric("待处理", pending)
    
    st.divider()
    
    for task in filtered_tasks:
        render_task_card(task)


def render_object_card(obj_name: str, obj_data: Dict):
    status = obj_data.get("status", "unknown")
    obj_type = obj_data.get("type", "unknown")
    position = obj_data.get("position", [])
    status_color = get_status_color(status)
    
    type_icons = {
        "station": "🏭",
        "oru": "📦",
        "storage": "🗄️",
        "tool": "🔧",
    }
    type_icon = type_icons.get(obj_type, "📍")
    
    with st.container():
        cols = st.columns([0.1, 0.3, 0.3, 0.3])
        
        with cols[0]:
            st.markdown(f"<span style='font-size: 1.5em;'>{type_icon}</span>", unsafe_allow_html=True)
        
        with cols[1]:
            st.markdown(f"**{obj_name}**")
            st.caption(f"类型: {obj_type}")
        
        with cols[2]:
            st.markdown(f"<span style='color: {status_color}; font-weight: bold;'>{status}</span>", unsafe_allow_html=True)
        
        with cols[3]:
            if position and len(position) >= 3:
                st.caption(f"📍 ({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f})")


def render_objects_section():
    st.subheader("📦 物体状态")
    
    config = load_object_config()
    objects = config.get("objects", {})
    
    if not objects:
        st.info("暂无物体配置")
        return
    
    type_filter = st.multiselect(
        "筛选类型",
        options=list(set(obj.get("type", "unknown") for obj in objects.values())),
        default=None,
        key="object_type_filter"
    )
    
    filtered_objects = {k: v for k, v in objects.items() 
                       if not type_filter or v.get("type") in type_filter}
    
    cols = st.columns(4)
    status_counts = {}
    for obj in objects.values():
        status = obj.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    
    with cols[0]:
        st.metric("总物体", len(objects))
    with cols[1]:
        st.metric("已安装", status_counts.get("installed", 0))
    with cols[2]:
        st.metric("存储中", status_counts.get("stored", 0))
    with cols[3]:
        st.metric("可用", status_counts.get("available", 0))
    
    st.divider()
    
    for obj_name, obj_data in filtered_objects.items():
        render_object_card(obj_name, obj_data)
        st.divider()


def render_arm_card(arm_id: str, arm_state):
    status = arm_state.status.value if hasattr(arm_state.status, 'value') else str(arm_state.status)
    status_color = get_status_color(status)
    status_emoji = get_status_emoji(status)
    
    with st.container():
        cols = st.columns([0.1, 0.25, 0.35, 0.3])
        
        with cols[0]:
            st.markdown(f"<span style='font-size: 1.5em;'>🤖</span>", unsafe_allow_html=True)
        
        with cols[1]:
            st.markdown(f"**{arm_state.name}**")
            st.caption(f"ID: {arm_id}")
        
        with cols[2]:
            st.markdown(f"<span style='color: {status_color}; font-weight: bold;'>{status_emoji} {status.upper()}</span>", unsafe_allow_html=True)
            if arm_state.current_task:
                st.caption(f"当前任务: {arm_state.current_task}")
        
        with cols[3]:
            gripper_status = "闭合" if arm_state.gripper_closed else "打开"
            st.caption(f"🤏 夹爪: {gripper_status}")
            if arm_state.object_in_hand:
                st.caption(f"📦 持有: {arm_state.object_in_hand}")
            position = arm_state.position
            if position and len(position) >= 3:
                st.caption(f"📍 ({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f})")


def render_arms_section():
    st.subheader("🦾 机械臂状态")
    
    manager = get_multi_arm_manager()
    arms = manager.arms
    
    if not arms:
        st.info("暂无机械臂连接")
        return
    
    cols = st.columns(len(arms))
    for idx, (arm_id, arm) in enumerate(arms.items()):
        with cols[idx]:
            status = arm.state.status.value if hasattr(arm.state.status, 'value') else str(arm.state.status)
            if status == "idle":
                st.success(f"**{arm.state.name}**\n\n状态: {status}")
            elif status in ["moving", "working"]:
                st.warning(f"**{arm.state.name}**\n\n状态: {status}")
            else:
                st.error(f"**{arm.state.name}**\n\n状态: {status}")
    
    st.divider()
    
    for arm_id, arm in arms.items():
        render_arm_card(arm_id, arm.state)
        st.divider()


def render_control_section():
    st.subheader("🎮 控制面板")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("#### 任务控制")
        if st.button("🔄 刷新任务", use_container_width=True):
            st.session_state.task_persistence = TaskPersistence(TASKS_DIR)
            st.rerun()
        
        if st.button("🗑️ 清除已完成任务", use_container_width=True):
            tp = get_task_persistence()
            for task in tp.list_all():
                if task.status == "completed":
                    tp.delete(task.task_id)
            st.rerun()
    
    with col2:
        st.markdown("#### 机械臂控制")
        if st.button("🏠 所有机械臂回原点", use_container_width=True):
            manager = get_multi_arm_manager()
            for arm_id, arm in manager.arms.items():
                arm.go_home()
            st.success("已发送回原点指令")
        
        if st.button("🔓 打开所有夹爪", use_container_width=True):
            manager = get_multi_arm_manager()
            for arm_id, arm in manager.arms.items():
                arm.open_gripper()
            st.success("已打开所有夹爪")
    
    with col3:
        st.markdown("#### 系统控制")
        if st.button("🔄 重置系统", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        
        auto_refresh = st.checkbox("自动刷新", value=False, key="auto_refresh")
        if auto_refresh:
            refresh_interval = st.slider("刷新间隔(秒)", 1, 10, 3)
            time.sleep(refresh_interval)
            st.rerun()


def render_skill_section():
    st.subheader("📚 可用技能")
    
    skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
    if not os.path.exists(skills_dir):
        st.info("未找到技能目录")
        return
    
    skills = []
    for skill_folder in os.listdir(skills_dir):
        skill_md = os.path.join(skills_dir, skill_folder, "SKILL.md")
        if os.path.exists(skill_md):
            skills.append((skill_folder, skill_md))
    
    if not skills:
        st.info("暂无可用技能")
        return
    
    cols = st.columns(3)
    for idx, (skill_name, skill_path) in enumerate(skills):
        with cols[idx % 3]:
            with st.expander(f"🔧 {skill_name}"):
                try:
                    with open(skill_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    st.markdown(content)
                except Exception as e:
                    st.error(f"读取失败: {e}")


def render_chat_section():
    st.subheader("💬 智能对话")
    
    agent = get_lead_agent()
    
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    
    st.markdown("""
        <style>
        .chat-message {
            padding: 10px 15px;
            border-radius: 10px;
            margin: 5px 0;
        }
        .user-message {
            background-color: #e3f2fd;
            margin-left: 20%;
        }
        .assistant-message {
            background-color: #f5f5f5;
            margin-right: 20%;
        }
        .thinking-box {
            background-color: #fff3e0;
            padding: 10px;
            border-radius: 5px;
            font-family: monospace;
            font-size: 0.9em;
            margin: 5px 0;
        }
        .tool-call-box {
            background-color: #e8f5e9;
            padding: 8px;
            border-radius: 5px;
            font-family: monospace;
            font-size: 0.85em;
            margin: 3px 0;
        }
        </style>
    """, unsafe_allow_html=True)
    
    chat_container = st.container()
    
    with chat_container:
        for msg in st.session_state.chat_messages:
            if msg["role"] == "user":
                st.markdown(f"""
                    <div class="chat-message user-message">
                        <strong>👤 用户:</strong><br/>
                        {msg["content"]}
                    </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                    <div class="chat-message assistant-message">
                        <strong>🤖 智能体:</strong><br/>
                        {msg["content"]}
                    </div>
                """, unsafe_allow_html=True)
                
                if "thinking" in msg and msg["thinking"]:
                    with st.expander("🧠 思考过程", expanded=False):
                        st.code(msg["thinking"], language=None)
                
                if "tool_calls" in msg and msg["tool_calls"]:
                    with st.expander("🔧 工具调用", expanded=False):
                        for tc in msg["tool_calls"]:
                            st.markdown(f"**{tc['name']}**")
                            st.code(tc["input"], language="json")
                            st.caption(f"结果: {tc['result']}")
    
    st.divider()
    
    col1, col2 = st.columns([4, 1])
    
    with col2:
        st.markdown("#### 快捷命令")
        btn_state = st.button("📊 状态", use_container_width=True)
        btn_team = st.button("👥 队友", use_container_width=True)
        btn_reset = st.button("� 重置", use_container_width=True)
    
    default_input = ""
    if btn_state:
        default_input = "显示当前状态"
    elif btn_team:
        default_input = "显示队友状态"
    elif btn_reset:
        default_input = "重置系统"
    
    with col1:
        user_input = st.text_area(
            "输入指令:",
            value=default_input,
            height=80,
            placeholder="例如: 更换装配站上的ORU",
            key="chat_input"
        )
    
    col_send, col_clear = st.columns([3, 1])
    with col_send:
        send_button = st.button("📤 发送", use_container_width=True, type="primary")
    with col_clear:
        if st.button("🗑️ 清空对话", use_container_width=True):
            st.session_state.chat_messages = []
            st.rerun()
    
    if send_button and user_input.strip():
        st.session_state.chat_messages.append({
            "role": "user",
            "content": user_input.strip()
        })
        
        with st.spinner("🤔 思考中..."):
            thinking_content = ""
            tool_calls = []
            final_response = ""
            
            try:
                for chunk in agent.chat_stream(user_input.strip()):
                    if "[thinking]" in chunk:
                        if chunk.startswith("[thinking]"):
                            thinking_content = ""
                    elif "[/thinking]" in chunk:
                        pass
                    elif "[tool_call]" in chunk:
                        content = chunk.replace('[tool_call]', '').replace('[/tool_call]', '')
                        parts = content.split('(', 1)
                        tool_name = parts[0] if parts else content
                        tool_input = parts[1].rstrip(')') if len(parts) > 1 else ""
                        tool_calls.append({
                            "name": tool_name,
                            "input": tool_input,
                            "result": ""
                        })
                    elif "[tool_result]" in chunk:
                        content = chunk.replace('[tool_result]', '').replace('[/tool_result]', '')
                        if tool_calls:
                            tool_calls[-1]["result"] = content
                    elif "[response]" in chunk:
                        content = chunk.replace('[response]', '').replace('[/response]', '')
                        final_response = content
                    elif "[error]" in chunk:
                        content = chunk.replace('[error]', '').replace('[/error]', '')
                        final_response = f"❌ 错误: {content}"
                    else:
                        thinking_content += chunk
                
                if not final_response:
                    final_response = "任务已执行完成。"
                
                st.session_state.chat_messages.append({
                    "role": "assistant",
                    "content": final_response,
                    "thinking": thinking_content,
                    "tool_calls": tool_calls
                })
                
            except Exception as e:
                st.session_state.chat_messages.append({
                    "role": "assistant",
                    "content": f"❌ 发生错误: {str(e)}"
                })
        
        st.rerun()
    
    st.divider()
    
    with st.expander("ℹ️ 使用说明"):
        st.markdown("""
        **可用命令:**
        - `更换ORU` - 执行完整的ORU更换流程
        - `状态` / `state` - 显示当前场景状态
        - `队友` / `team` - 显示队友状态
        - `重置` / `reset` - 重置所有机械臂和任务
        - `帮助` / `help` - 显示帮助信息
        
        **提示:** 智能体会自动将任务分解为原子操作，并协调双臂协作执行。
        """)
    
    st.caption(f"模型: {agent.model} | 机械臂: {list(agent.manager.arms.keys())}")


def main():
    st.set_page_config(
        page_title="URRobot-Agent 控制面板",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.markdown("""
        <style>
        .stMetric > div {
            background-color: #f0f2f6;
            padding: 10px;
            border-radius: 10px;
        }
        div[data-testid="stHorizontalBlock"] > div {
            background-color: #ffffff;
            padding: 10px;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        </style>
    """, unsafe_allow_html=True)
    
    st.title("🤖 URRobot-Agent 控制面板")
    st.caption("双臂机器人智能协作系统 - 实时监控界面")
    
    with st.sidebar:
        st.header("导航")
        page = st.radio(
            "选择视图",
            ["💬 智能对话", "📊 总览", "📋 任务列表", "📦 物体状态", "🦾 机械臂状态", "📚 技能列表"],
            label_visibility="collapsed"
        )
        
        st.divider()
        render_control_section()
    
    if page == "💬 智能对话":
        render_chat_section()
    
    elif page == "📊 总览":
        col1, col2 = st.columns(2)
        with col1:
            render_tasks_section()
        with col2:
            render_objects_section()
        
        st.divider()
        render_arms_section()
    
    elif page == "📋 任务列表":
        render_tasks_section()
    
    elif page == "📦 物体状态":
        render_objects_section()
    
    elif page == "🦾 机械臂状态":
        render_arms_section()
    
    elif page == "📚 技能列表":
        render_skill_section()


if __name__ == "__main__":
    main()
