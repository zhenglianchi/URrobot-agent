"""LangGraph 图状态定义。

定义了多臂协作的图状态结构，继承MessagesState并添加任务和场景相关字段。
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from langgraph.graph import MessagesState


@dataclass
class MultiArmState(MessagesState):
    """多臂协作图状态。

    继承MessagesState以支持消息历史，添加任务管理和场景状态字段。
    """
    # 用户原始输入
    user_input: str = ""

    # 任务规划管理（由TaskPersistence维护，这里只保存ID列表）
    task_ids: List[str] = field(default_factory=list)
    # 待执行任务：分配给左右臂的任务（支持并行）
    pending_left_task: Optional[str] = None   # 左臂待执行任务
    pending_right_task: Optional[str] = None  # 右臂待执行任务
    current_task_id: Optional[str] = None
    current_arm_id: Optional[str] = None  # 当前执行任务的机械臂

    # 场景状态快照（从MultiArmManager同步）
    scene_state: Dict = field(default_factory=dict)

    # Reviewer检查结果
    review_result: Optional[Dict] = None
    review_passed: bool = True
    review_attempts: int = 0  # 当前回合的重试次数
    max_review_attempts: int = 3  # 最大重试次数

    # 调整信息
    needs_adjustment: bool = False
    adjustment_feedback: str = ""
    adjustment_count: int = 0

    # 执行统计
    iteration_count: int = 0
    max_iterations: int = 100

    # 任务完成状态
    all_tasks_completed: bool = False

    def increment_iteration(self) -> None:
        """增加迭代计数。"""
        self.iteration_count += 1

    def reset_review(self) -> None:
        """重置review状态，准备下一次检查。"""
        self.review_passed = True
        self.review_result = None
        self.needs_adjustment = False

    def has_pending_tasks(self) -> bool:
        """是否有等待执行的任务（左右任一）。"""
        return self.pending_left_task is not None or self.pending_right_task is not None
