"""
URRobot-Agent: 基于大语言模型的双臂机器人协作智能系统

项目架构：
- LeadAgent: 主协调智能体，分解任务规划流程
- ArmTeammate: 机械臂队友智能体，执行具体动作
- MultiArmManager: 多机械臂硬件管理
- MessageBus: 消息总线，队友间通信
- TaskPersistence: 任务持久化存储
- SkillLoader: 技能加载
- LangGraph: 新增基于LangGraph的重构版本，包含Reviewer审查agent

架构选择：
- 通过环境变量 USE_LANGGRAPH=true/false 选择使用哪个架构
- 默认使用原有架构，设置 USE_LANGGRAPH=true 启用LangGraph版本
"""

import os
import sys
import shutil
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 根据环境变量选择架构
USE_LANGGRAPH = os.environ.get("USE_LANGGRAPH", "false").lower() == "true"

if USE_LANGGRAPH:
    from robot.langgraph_agent import create_langgraph_agent
else:
    from robot.lead_agent import create_lead_agent


def clear_line():
    """清除终端当前行，用于覆盖式输出思考过程"""
    columns = shutil.get_terminal_size().columns
    print('\r' + ' ' * columns + '\r', end='', flush=True)


def stream_print(text: str, end=''):
    """流式输出文本，不自动换行，保持思考过程在一行"""
    print(text, end=end, flush=True)


def print_separator(char='=', length=60):
    """打印分隔线"""
    print(char * length)


def main():
    """命令行主入口，运行交互式对话"""
    print_separator()
    print("🤖 双臂机器人智能控制系统 - 命令行模式")
    if USE_LANGGRAPH:
        print("🏗️  架构: LangGraph (带Reviewer审查agent)")
    else:
        print("🏗️  架构: 传统多线程+消息总线")
    print_separator()

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "object_positions.json")

    # 创建stream_callback来实时输出子agent的思考
    def stream_callback(event_type: str, content: str):
        if "[thinking]" in content:
            if content.startswith("[thinking]"):
                clear_line()
                agent_name = event_type.split(']')[0] if ']' in event_type else "主智能体"
                stream_print(f"\n{agent_name} 思考中: ")
            return
        if "[/thinking]" in content:
            stream_print("\n")
            return
        if "[tool_call]" in content:
            stream_print(f"\n🔧 工具调用: {content.replace('[tool_call]', '').replace('[/tool_call]', '')}\n")
            return
        if "[tool_result]" in content:
            result = content.replace('[tool_result]', '').replace('[/tool_result]', '')
            stream_print(f"✅ 结果: {result}\n")
            return
        if "[error]" in content:
            error = content.replace('[error]', '').replace('[/error]', '')
            stream_print(f"\n❌ 错误: {error}\n")
            return
        # 普通思考内容，直接输出不换行
        stream_print(content)

    if USE_LANGGRAPH:
        agent = create_langgraph_agent(
            config_path=config_path,
            stream_callback=stream_callback
        )
    else:
        agent = create_lead_agent(
            config_path=config_path,
            stream_callback=stream_callback
        )

    print(f"\n✓ 已初始化智能体")
    print(f"  模型: {agent.model}")
    print(f"  机械臂: {list(agent.manager.arms.keys())}")
    print(f"  物体: {len(agent.manager.objects)} 个")

    print_separator('-')
    print("命令说明:")
    print("  quit / exit / q → 退出程序")
    print("  state / 状态 → 显示当前工作单元完整状态")
    print("  team / 队友 → 显示队友状态")
    print("  reset / 重置 → 重置所有机械臂和任务")
    print("  help / 帮助 → 显示帮助")
    print_separator('-')

    while True:
        try:
            user_input = input("\n> ").strip()

            if not user_input:
                continue

            if user_input.lower() in ["quit", "exit", "退出", "q"]:
                print("\n再见!")
                agent.disconnect()
                break

            if user_input.lower() in ["state", "状态"]:
                print_separator('-')
                print(agent.manager.get_scene_summary())
                print_separator('-')
                continue

            if user_input.lower() in ["team", "队友", "list"]:
                print_separator('-')
                if USE_LANGGRAPH:
                    print("LangGraph模式: 不使用独立队友智能体，任务由图节点直接执行")
                    print(f"机械臂: {list(agent.manager.arms.keys())}")
                else:
                    print(agent.teammate_manager.list_teammates())
                print_separator('-')
                continue

            if user_input.lower() in ["reset", "重置"]:
                agent.reset()
                print("✓ 智能体重置完成。")
                continue

            if user_input.lower() in ["help", "帮助"]:
                print_separator('-')
                print("命令说明:")
                print("  quit / exit / q → 退出程序")
                print("  state / 状态 → 显示当前工作单元完整状态")
                if not USE_LANGGRAPH:
                    print("  team / 队友 → 显示队友状态")
                print("  reset / 重置 → 重置所有机械臂和任务")
                print("  help / 帮助 → 显示帮助")
                print_separator('-')
                continue

            print()
            full_response = ""
            if USE_LANGGRAPH:
                # LangGraph流式输出格式不同
                for chunk in agent.chat_stream(user_input):
                    if chunk.startswith("[step]"):
                        content = chunk.replace('[step]', '').replace('[/step]', '')
                        stream_print(f"\n⚡ Step {content}\n")
                    elif chunk.startswith("[review]"):
                        content = chunk.replace('[review]', '').replace('[/review]', '')
                        stream_print(f"🔍 Review: {content}\n")
                    elif chunk.startswith("[completed]"):
                        content = chunk.replace('[completed]', '').replace('[/completed]', '')
                        stream_print(f"\n✅ {content}\n")
                    elif chunk.startswith("[result]"):
                        content = chunk.replace('[result]', '').replace('[/result]', '')
                        full_response = content
                    elif chunk.startswith("[error]"):
                        error = chunk.replace('[error]', '').replace('[/error]', '')
                        stream_print(f"\n❌ 错误: {error}\n")
                    elif chunk.startswith("[starting]"):
                        pass  # 忽略启动信息
                    else:
                        stream_print(chunk)
            else:
                # 原有格式
                for chunk in agent.chat_stream(user_input):
                    if "[thinking]" in chunk:
                        if chunk.startswith("[thinking]"):
                            clear_line()
                            stream_print("主智能体 思考中: ")
                    elif "[/thinking]" in chunk:
                        stream_print("\n")
                    elif "[tool_call]" in chunk:
                        content = chunk.replace('[tool_call]', '').replace('[/tool_call]', '')
                        stream_print(f"\n🔧 工具调用: {content}\n")
                    elif "[tool_result]" in chunk:
                        content = chunk.replace('[tool_result]', '').replace('[/tool_result]', '')
                        stream_print(f"✅ 结果: {content}\n")
                    elif "[response]" in chunk:
                        content = chunk.replace('[response]', '').replace('[/response]', '')
                        full_response = content
                    elif "[error]" in chunk:
                        error = chunk.replace('[error]', '').replace('[/error]', '')
                        stream_print(f"\n❌ 错误: {error}\n")
                    else:
                        # 流式输出思考内容，不换行
                        stream_print(chunk)

            if full_response:
                print_separator('-')
                print(f"📄 最终结果:\n{full_response}")

            # 任务完成后显示当前状态
            print_separator('-')
            print(agent.manager.get_scene_summary())
            print_separator()

        except KeyboardInterrupt:
            print("\n\n中断。再见!")
            agent.disconnect()
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
