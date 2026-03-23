"""LangGraph 多智能体系统高层入口。

提供兼容原有 LeadAgent 接口的包装类，方便切换使用。
"""
import os
from typing import Dict, List, Optional, Callable, Generator
from dotenv import load_dotenv

load_dotenv()

from langgraph.graph import StateGraph

from robot.graph.state import MultiArmState
from robot.graph.builder import build_multi_arm_graph
from utils.logger_handler import logger


class LangGraphMultiArmAgent:
    """基于LangGraph的多臂协作智能体。

    包装编译好的LangGraph，提供兼容原有LeadAgent的接口。
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        model: Optional[str] = None,
        use_simulator: bool = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
        tasks_dir: Optional[str] = None,
        skills_dir: Optional[str] = None,
        safety_distance: float = 0.15,
        max_review_attempts: int = 3,
    ):
        """
        参数:
            config_path: 机械臂配置文件路径
            model: Claude模型名称
            use_simulator: 是否使用仿真模式
            api_key: Anthropic API密钥
            base_url: API基础URL
            stream_callback: 流式输出回调
            tasks_dir: 任务持久化目录
            skills_dir: 技能目录
            safety_distance: 双臂安全距离（米）
            max_review_attempts: 单个任务最大重试次数
        """
        self.config_path = config_path
        self.model = model or os.environ.get("MODEL_ID", "minimax-m2.5")
        self.use_simulator = use_simulator if use_simulator is not None else \
            os.environ.get("USE_SIMULATOR", "true").lower() == "true"
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        self.stream_callback = stream_callback
        self.tasks_dir = tasks_dir
        self.safety_distance = safety_distance
        self.max_review_attempts = max_review_attempts

        # 构建图和组件
        self.graph, self.components = build_multi_arm_graph(
            config_path=config_path,
            tasks_dir=tasks_dir,
            skills_dir=skills_dir,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            use_simulator=self.use_simulator,
            safety_distance=safety_distance,
            max_review_attempts=max_review_attempts,
            with_checkpointer=True,
        )

        self.manager = self.components["manager"]
        self.task_persistence = self.components["task_persistence"]

        logger.info(f"[LangGraphMultiArmAgent] Initialized with model: {self.model}")
        logger.info(f"[LangGraphMultiArmAgent] Reviewer enabled, safety_distance={safety_distance}m")

    def get_initial_state(self, user_input: str) -> MultiArmState:
        """获取初始状态。"""
        return {
            "user_input": user_input,
            "task_ids": [],
            "pending_left_task": None,
            "pending_right_task": None,
            "current_task_id": None,
            "current_arm_id": None,
            "scene_state": {},
            "review_result": None,
            "review_passed": True,
            "review_attempts": 0,
            "needs_adjustment": False,
            "adjustment_feedback": "",
            "adjustment_count": 0,
            "iteration_count": 0,
            "max_iterations": 100,
            "all_tasks_completed": False,
            "messages": [],
        }

    def chat(self, user_message: str, thread_id: str = "default") -> str:
        """同步对话入口。

        参数:
            user_message: 用户输入指令
            thread_id: 线程ID用于checkpointer

        返回:
            最终执行结果描述
        """
        initial_state = self.get_initial_state(user_message)
        config = {"configurable": {"thread_id": thread_id}}

        # 运行图直到结束
        result = self.graph.invoke(initial_state, config)

        # 收集执行结果
        summary = self._format_result(result)
        return summary

    def chat_stream(self, user_message: str, thread_id: str = "default") -> Generator[str, None, None]:
        """流式输出入口。

        逐步输出执行过程中的事件。
        """
        initial_state = self.get_initial_state(user_message)
        config = {"configurable": {"thread_id": thread_id}}

        yield "[starting] Starting LangGraph execution...[/starting]\n"

        step = 0
        for chunk in self.graph.stream(initial_state, config, stream_mode="updates"):
            step += 1
            for node_name, updates in chunk.items():
                yield f"[step][{step}] Node: {node_name}[/step]\n"
                if "review_result" in updates:
                    result = updates["review_result"]
                    passed = result.get("passed", False)
                    issues = result.get("issues", [])
                    if passed:
                        yield f"[review] ✓ Check passed[/review]\n"
                    else:
                        yield f"[review] ✗ Check failed, issues: {len(issues)}[/review]\n"
                        for issue in issues:
                            yield f"[review]   - {issue}[/review]\n"

        # 最终结果
        yield f"[completed] Execution finished[/completed]\n"
        final_config = {"configurable": {"thread_id": thread_id}}
        final_state = self.graph.get_state(final_config)
        summary = self._format_result(final_state.values)
        yield f"[result]{summary}[/result]\n"

    def _format_result(self, state: Dict) -> str:
        """格式化执行结果。"""
        summary = self.task_persistence.get_summary()
        task_summary = "\n".join([
            f"  - {status}: {count}"
            for status, count in summary.items()
        ])

        scene = self.manager.get_scene_summary()

        review_count = state.get("review_attempts", 0)
        adjust_count = state.get("adjustment_count", 0)
        iterations = state.get("iteration_count", 0)

        return f"""执行完成。

任务统计:
{task_summary}

审查检查: {review_count} 次，调整: {adjust_count} 次
总迭代: {iterations} 次

{scene}
"""

    def get_state(self) -> Dict:
        """获取当前系统状态。"""
        return {
            "scene": self.manager.get_all_states(),
            "tasks": self.task_persistence.get_summary(),
        }

    def reset(self):
        """重置系统状态。"""
        self.manager.reset()
        self.task_persistence.clear_all()
        logger.info("[LangGraphMultiArmAgent] Full reset complete")

    def disconnect(self):
        """断开连接。"""
        self.manager.disconnect_all()
        logger.info("[LangGraphMultiArmAgent] Disconnected")


def create_langgraph_agent(
    config_path: Optional[str] = None,
    model: Optional[str] = None,
    use_simulator: bool = None,
    api_key: Optional[str] = None,
    stream_callback: Optional[Callable[[str, str], None]] = None,
    tasks_dir: Optional[str] = None,
    skills_dir: Optional[str] = None,
) -> LangGraphMultiArmAgent:
    """工厂函数创建LangGraph多臂智能体。"""
    return LangGraphMultiArmAgent(
        config_path=config_path,
        model=model,
        use_simulator=use_simulator,
        api_key=api_key,
        stream_callback=stream_callback,
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
    )
