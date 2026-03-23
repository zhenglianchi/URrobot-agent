"""Reviewer Agent 检查逻辑实现。

实现ReviewerChecker类，负责检查场景状态一致性，发现问题后报告给主agent。
检查清单：
1. 机械臂状态一致性检查
2. 物体持有状态一致性检查
3. 碰撞风险检查（双臂距离过近）
4. 任务进度一致性检查
"""
from dataclasses import dataclass
from typing import List, Optional, Dict
import math

from robot.multi_arm_manager import MultiArmManager, ArmStatus


@dataclass
class ReviewResult:
    """审查结果"""
    passed: bool                # 是否通过检查
    issues: List[str]           # 问题列表
    recommendation: str         # 建议: "continue", "adjust", "abort"
    scene_snapshot: Dict        # 场景状态快照
    max_retries_reached: bool = False  # 是否达到最大重试次数


class ReviewerChecker:
    """场景状态审查器。

    每次机械臂操作完成后，检查整个场景状态是否一致，是否存在问题。
    如果发现问题，建议主agent介入调整。
    """

    def __init__(self, safety_distance: float = 0.15, max_retries: int = 3):
        """
        参数:
            safety_distance: 双臂安全距离（米），小于此距离告警
            max_retries: 单个任务最大调整重试次数
        """
        self.safety_distance = safety_distance
        self.max_retries = max_retries

    def check_all(self, manager: MultiArmManager, current_task_id: Optional[str] = None,
                  review_attempts: int = 0) -> ReviewResult:
        """执行完整的场景状态检查。

        参数:
            manager: 多机械臂管理器
            current_task_id: 当前执行的任务ID（用于日志）
            review_attempts: 当前任务已经重试次数

        返回:
            ReviewResult: 检查结果
        """
        issues = []

        # 1. 检查机械臂状态一致性
        arm_issues = self._check_arm_state_consistency(manager)
        issues.extend(arm_issues)

        # 2. 检查物体持有状态一致性
        object_issues = self._check_object_consistency(manager)
        issues.extend(object_issues)

        # 3. 检查碰撞风险
        collision_issues = self._check_collision_risk(manager)
        issues.extend(collision_issues)

        # 4. 检查是否有错误状态的机械臂
        error_issues = self._check_error_states(manager)
        issues.extend(error_issues)

        # 获取场景快照
        scene_snapshot = manager.get_all_states()

        # 判断是否通过
        if not issues:
            return ReviewResult(
                passed=True,
                issues=[],
                recommendation="continue",
                scene_snapshot=scene_snapshot,
                max_retries_reached=False
            )

        # 检查是否达到最大重试次数
        max_retries_reached = review_attempts >= self.max_retries

        # 决定建议
        if max_retries_reached:
            recommendation = "abort"
        else:
            recommendation = "adjust"

        return ReviewResult(
            passed=False,
            issues=issues,
            recommendation=recommendation,
            scene_snapshot=scene_snapshot,
            max_retries_reached=max_retries_reached
        )

    def _check_arm_state_consistency(self, manager: MultiArmManager) -> List[str]:
        """检查机械臂状态一致性。

        检查:
        - 夹爪闭合但未持有物体
        - 夹爪打开但持有物体
        """
        issues = []
        for arm_id, arm in manager.arms.items():
            state = arm.state
            # 夹爪闭合但没有物体 → 不一致
            if state.gripper_closed and state.object_in_hand is None:
                issues.append(f"[{arm_id}] 夹爪闭合但未持有物体，状态不一致")
            # 夹爪打开但持有物体 → 不一致
            if not state.gripper_closed and state.object_in_hand is not None:
                issues.append(f"[{arm_id}] 夹爪打开但持有物体 '{state.object_in_hand}'，状态不一致")
        return issues

    def _check_object_consistency(self, manager: MultiArmManager) -> List[str]:
        """检查物体持有状态一致性。

        检查:
        - 物体标记为被某机械臂持有，但该机械臂并不持有它
        - 机械臂持有物体，但物体状态不匹配
        - 物体被多个机械臂持有（不可能）
        """
        issues = []

        # 检查物体 → 机械臂方向
        for obj_id, obj_state in manager.object_states.items():
            held_by = obj_state.get("held_by")
            if held_by:
                # 检查持有该物体的机械臂是否存在
                arm = manager.get_arm(held_by)
                if arm is None:
                    issues.append(f"[{obj_id}] 被不存在的机械臂 '{held_by}' 持有")
                    continue
                # 检查机械臂是否真的持有这个物体
                if arm.state.object_in_hand != obj_id:
                    issues.append(f"[{obj_id}] 标记为被 '{held_by}' 持有，但该机械臂不持有它")

        # 检查机械臂 → 物体方向
        for arm_id, arm in manager.arms.items():
            obj_in_hand = arm.state.object_in_hand
            if obj_in_hand:
                obj_state = manager.get_object_state(obj_in_hand)
                if obj_state is None:
                    issues.append(f"[{arm_id}] 持有不存在的物体 '{obj_in_hand}'")
                else:
                    if obj_state.get("held_by") != arm_id:
                        issues.append(f"[{arm_id}] 持有 '{obj_in_hand}'，但物体状态显示被 '{obj_state.get('held_by')}' 持有，不匹配")

        # 检查同一物体不被多个机械臂持有（通过计数）
        held_count: Dict[str, int] = {}
        for obj_id, obj_state in manager.object_states.items():
            held_by = obj_state.get("held_by")
            if held_by:
                held_count[held_by] = held_count.get(held_by, 0) + 1

        for arm_id, count in held_count.items():
            if count > 1:
                # 这不一定是错误，一个机械臂可以持有多个物体？不，通常一个夹爪只能抓一个
                issues.append(f"[{arm_id}] 持有 {count} 个物体，单个夹爪可能无法同时持有多个")

        return issues

    def _check_collision_risk(self, manager: MultiArmManager) -> List[str]:
        """检查碰撞风险，检查双臂TCP距离是否过近。"""
        issues = []
        arms = list(manager.arms.values())
        if len(arms) < 2:
            return issues

        # 两两比较机械臂TCP距离
        arm_ids = list(manager.arms.keys())
        for i in range(len(arms)):
            for j in range(i + 1, len(arms)):
                pos1 = arms[i].get_tcp()
                pos2 = arms[j].get_tcp()
                # 计算欧氏距离（只考虑xyz）
                dx = pos1[0] - pos2[0]
                dy = pos1[1] - pos2[1]
                dz = pos1[2] - pos2[2]
                distance = math.sqrt(dx * dx + dy * dy + dz * dz)
                if distance < self.safety_distance:
                    issues.append(
                        f"[碰撞风险] {arm_ids[i]} 和 {arm_ids[j]} TCP距离过近: "
                        f"{distance:.3f}m (安全阈值: {self.safety_distance}m)"
                    )
        return issues

    def _check_error_states(self, manager: MultiArmManager) -> List[str]:
        """检查是否有机械臂处于错误状态。"""
        issues = []
        for arm_id, arm in manager.arms.items():
            if arm.state.status == ArmStatus.ERROR:
                issues.append(f"[{arm_id}] 处于ERROR错误状态")
        return issues

    def format_issues(self, result: ReviewResult) -> str:
        """格式化问题列表为可读文本。"""
        if not result.issues:
            return "无问题，状态正常"
        lines = ["检查发现以下问题:"]
        for i, issue in enumerate(result.issues, 1):
            lines.append(f"  {i}. {issue}")
        lines.append(f"\n建议: {result.recommendation}")
        if result.max_retries_reached:
            lines.append("\n⚠️ 已达到最大重试次数，建议终止任务")
        return "\n".join(lines)
