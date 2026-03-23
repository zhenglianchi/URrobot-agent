"""LangGraph 图构建器。

创建并编译多臂协作图，定义节点和边的连接关系以及条件路由。
"""
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from robot.graph.state import MultiArmState
from robot.graph.reviewer import ReviewerChecker
from robot.graph.nodes import (
    PlanNode,
    AssignTaskNode,
    ExecuteNode,
    ReviewerNode,
    AdjustNode,
    check_completion,
)
from robot.multi_arm_manager import MultiArmManager
from robot.task_persistence import TaskPersistence
from robot.skill_loader import get_skill_loader, SkillLoader


def should_continue_review(state: MultiArmState) -> Literal["adjust", "check_completion"]:
    """Review之后的条件路由：是否通过，是否需要调整。"""
    if state["review_passed"]:
        return "check_completion"
    else:
        return "adjust"


def should_continue_assign(state: MultiArmState) -> Literal["assign", "end"]:
    """检查完成后的条件路由：是否还有更多任务。"""
    if state.get("all_tasks_completed", False):
        return "end"
    else:
        return "assign"


def build_multi_arm_graph(
    config_path: str = None,
    tasks_dir: str = None,
    skills_dir: str = None,
    model: str = None,
    api_key: str = None,
    base_url: str = None,
    use_simulator: bool = True,
    safety_distance: float = 0.15,
    max_review_attempts: int = 3,
    with_checkpointer: bool = True,
):
    """构建多臂协作LangGraph。

    参数:
        config_path: 机械臂配置文件路径
        tasks_dir: 任务持久化目录
        skills_dir: 技能目录
        model: Claude模型名称
        api_key: API密钥
        base_url: API基础URL
        use_simulator: 是否使用仿真模式
        safety_distance: 双臂安全距离（米）
        max_review_attempts: 单个任务最大重试次数
        with_checkpointer: 是否启用checkpointer持久化

    返回:
        compiled graph: 编译好的LangGraph
        components: 各组件实例字典
    """
    # 初始化基础设施组件（这些保持不变）
    manager = MultiArmManager(config_path, use_simulator=use_simulator)
    task_persistence = TaskPersistence(tasks_dir)
    skill_loader = get_skill_loader(skills_dir)
    reviewer_checker = ReviewerChecker(
        safety_distance=safety_distance,
        max_retries=max_review_attempts
    )

    # 创建各个节点
    plan_node = PlanNode(
        manager=manager,
        task_persistence=task_persistence,
        skill_loader=skill_loader,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    assign_node = AssignTaskNode(task_persistence)
    execute_left = ExecuteNode(
        arm_id="arm_left",
        teammate_name="left_arm",
        manager=manager,
        task_persistence=task_persistence,
        skill_loader=skill_loader,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    execute_right = ExecuteNode(
        arm_id="arm_right",
        teammate_name="right_arm",
        manager=manager,
        task_persistence=task_persistence,
        skill_loader=skill_loader,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    reviewer_node = ReviewerNode(
        manager=manager,
        reviewer=reviewer_checker,
    )
    adjust_node = AdjustNode(
        manager=manager,
        task_persistence=task_persistence,
        skill_loader=skill_loader,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )

    # 构建图
    builder = StateGraph(MultiArmState)

    # 添加节点
    builder.add_node("plan", plan_node)
    builder.add_node("assign_task", assign_node)
    builder.add_node("execute_left", execute_left)
    builder.add_node("execute_right", execute_right)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("adjust", adjust_node)
    builder.add_node("check_completion", check_completion)

    # 设置入口
    builder.set_entry_point("plan")

    # 定义边
    # 规划完成后去分配任务
    builder.add_edge("plan", "assign_task")

    # 【并行执行】assign_task分配完成后，同时启动左右臂
    # LangGraph会自动并行执行两个节点，等待全部完成才继续
    builder.add_edge("assign_task", "execute_left")
    builder.add_edge("assign_task", "execute_right")

    # 左右臂都执行完成后，都进入reviewer
    # LangGraph等待两个分支都完成才会继续到reviewer
    builder.add_edge("execute_left", "reviewer")
    builder.add_edge("execute_right", "reviewer")

    # 检查后根据结果选择：通过去检查完成，不通过去调整
    builder.add_conditional_edges(
        "reviewer",
        should_continue_review,
        {
            "adjust": "adjust",
            "check_completion": "check_completion",
        }
    )

    # 调整完成后重新去检查
    builder.add_edge("adjust", "reviewer")

    # 检查完成后根据是否还有任务，决定继续分配还是结束
    builder.add_conditional_edges(
        "check_completion",
        should_continue_assign,
        {
            "assign": "assign_task",
            "end": END,
        }
    )

    # 编译
    if with_checkpointer:
        memory = MemorySaver()
        graph = builder.compile(checkpointer=memory)
    else:
        graph = builder.compile()

    components = {
        "manager": manager,
        "task_persistence": task_persistence,
        "skill_loader": skill_loader,
        "reviewer_checker": reviewer_checker,
    }

    return graph, components
