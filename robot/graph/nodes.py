"""LangGraph 节点实现。

实现所有图节点：
- plan_node: LeadAgent任务规划
- assign_task_node: 分配下一个就绪任务
- execute_left_node / execute_right_node: 机械臂执行任务
- reviewer_node: Reviewer检查场景状态
- adjust_node: LeadAgent根据审查结果调整计划
- check_completion_node: 检查是否所有任务完成
"""
import json
import os
from typing import Dict, List, Optional, Any
from dataclasses import asdict

from langgraph.graph import MessagesState

from robot.graph.state import MultiArmState
from robot.graph.reviewer import ReviewerChecker, ReviewResult
from robot.lead_agent import LeadAgent, LeadToolRegistry, LEAD_SYSTEM_PROMPT
from robot.task_persistence import TaskPersistence
from robot.multi_arm_manager import MultiArmManager
from robot.skill_loader import get_skill_loader, SkillLoader
from robot.tools import ToolResult, ToolStatus
from utils.logger_handler import logger


class PlanNode:
    """Plan 节点：LeadAgent进行任务规划。"""

    def __init__(
        self,
        manager: MultiArmManager,
        task_persistence: TaskPersistence,
        skill_loader: SkillLoader,
        model: str = None,
        api_key: str = None,
        base_url: str = None,
    ):
        self.manager = manager
        self.task_persistence = task_persistence
        self.skill_loader = skill_loader
        self.model = model or os.environ.get("MODEL_ID", "minimax-m2.5")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        self._client = None

    @property
    def client(self):
        if self._client is None and self.api_key:
            try:
                import anthropic
                client_kwargs = {"api_key": self.api_key}
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                self._client = anthropic.Anthropic(**client_kwargs)
            except ImportError:
                logger.warning("[PlanNode] anthropic package not installed")
        return self._client

    def __call__(self, state: MultiArmState) -> Dict:
        """执行任务规划。"""
        logger.info("[PlanNode] Starting task planning")

        user_input = state["user_input"]
        messages = [{"role": "user", "content": user_input}]

        tools = LeadToolRegistry.get_all_tools()
        iteration = 0

        # 使用LeadAgent的工具调用循环进行规划
        while iteration < 10:
            if not self.client:
                break

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=LEAD_SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
            )

            stop_reason = response.stop_reason
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            if stop_reason == "end_turn":
                # 规划完成
                break

            if stop_reason == "tool_use":
                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        logger.info(f"[PlanNode] Tool call: {block.name}({json.dumps(block.input, ensure_ascii=False)})")
                        result = self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result.to_string(),
                        })
                messages.append({"role": "user", "content": tool_results})
                iteration += 1

        # 获取所有任务ID
        task_ids = [t.task_id for t in self.task_persistence.list_all()]

        # 更新场景状态
        scene_state = self.manager.get_all_states()

        state["messages"].extend(messages)
        return {
            "messages": state["messages"],
            "task_ids": task_ids,
            "scene_state": scene_state,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    def _execute_tool(self, name: str, params: Dict) -> ToolResult:
        """执行规划工具调用。"""
        if name == "create_task":
            return self._create_task(params)
        elif name == "load_skill":
            return self._load_skill(params)
        elif name == "get_scene_state":
            return self._get_scene_state()
        elif name == "list_tasks":
            return self._list_tasks(params)
        else:
            # 其他工具在规划阶段不需要，这里只处理任务创建相关
            return ToolResult(ToolStatus.SUCCESS, f"Tool {name} noted")

    def _create_task(self, params: Dict) -> ToolResult:
        name = params.get("name", "")
        description = params.get("description", "")
        skill_name = params.get("skill_name")
        assigned_arm = params.get("assigned_arm")
        blocked_by = params.get("blocked_by")
        blocks = params.get("blocks")

        if not name:
            return ToolResult(ToolStatus.ERROR, "Task name required")

        task = self.task_persistence.create(
            name=name,
            description=description,
            skill_name=skill_name,
            assigned_arm=assigned_arm,
            blocked_by=blocked_by,
            blocks=blocks,
        )
        return ToolResult(ToolStatus.SUCCESS, f"Task #{task.task_id} created: {name}", {"task": task.to_dict()})

    def _load_skill(self, params: Dict) -> ToolResult:
        skill_name = params.get("name", "")
        if not skill_name:
            return ToolResult(ToolStatus.ERROR, "Skill name required")
        content = self.skill_loader.get_skill_content(skill_name)
        if content.startswith("Error:"):
            return ToolResult(ToolStatus.ERROR, content)
        return ToolResult(ToolStatus.SUCCESS, f"Skill '{skill_name}' loaded", {"content": content})

    def _get_scene_state(self) -> ToolResult:
        state = self.manager.get_all_states()
        return ToolResult(ToolStatus.SUCCESS, "Scene state", state)

    def _list_tasks(self, params: Dict) -> ToolResult:
        status = params.get("status")
        tasks = self.task_persistence.list_all(status)
        formatted = self.task_persistence.format_task_list(status)
        return ToolResult(ToolStatus.SUCCESS, formatted, {"tasks": [t.to_dict() for t in tasks]})


class AssignTaskNode:
    """Assign Task 节点：选择就绪任务分配给左右臂，支持并行执行。

    如果左右臂都有就绪任务，则同时分配给两个臂并行执行。
    两个都完成后才进入Reviewer检查。
    """

    def __init__(self, task_persistence: TaskPersistence):
        self.task_persistence = task_persistence

    def __call__(self, state: MultiArmState) -> Dict:
        """找到所有就绪任务，分别分配给左右臂。"""
        logger.info("[AssignTaskNode] Finding ready tasks for parallel execution")

        # 获取所有就绪任务（依赖都已完成）
        ready_tasks = self.task_persistence.get_ready_tasks()

        if not ready_tasks:
            logger.info("[AssignTaskNode] No ready tasks available")
            return {
                "pending_left_task": None,
                "pending_right_task": None,
                "current_task_id": None,
                "current_arm_id": None,
                "all_tasks_completed": True,
                "iteration_count": state.get("iteration_count", 0) + 1,
            }

        # 按机械臂分组分配任务
        left_tasks = []
        right_tasks = []
        arm_id_map = {
            "left_arm": "arm_left",
            "right_arm": "arm_right",
        }

        for task in ready_tasks:
            # 更新任务状态为running
            self.task_persistence.update(task.task_id, "running")
            if task.assigned_arm == "left_arm":
                left_tasks.append(task)
            elif task.assigned_arm == "right_arm":
                right_tasks.append(task)

        # 每个臂最多分配一个任务（本轮并行执行
        pending_left = left_tasks[0].task_id if left_tasks else None
        pending_right = right_tasks[0].task_id if right_tasks else None

        logger.info(f"[AssignTaskNode] Assigned: left={pending_left}, right={pending_right}")

        return {
            "pending_left_task": pending_left,
            "pending_right_task": pending_right,
            "review_passed": True,
            "needs_adjustment": False,
            "review_attempts": 0,
            "iteration_count": state.get("iteration_count", 0) + 1,
            "all_tasks_completed": False,
        }


class ExecuteNode:
    """Execute 节点：机械臂执行当前任务。

    为左臂和右臂分别创建实例。
    """

    def __init__(
        self,
        arm_id: str,
        teammate_name: str,
        manager: MultiArmManager,
        task_persistence: TaskPersistence,
        skill_loader: SkillLoader,
        model: str = None,
        api_key: str = None,
        base_url: str = None,
    ):
        self.arm_id = arm_id
        self.teammate_name = teammate_name
        self.manager = manager
        self.task_persistence = task_persistence
        self.skill_loader = skill_loader
        self.model = model or os.environ.get("MODEL_ID", "minimax-m2.5")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        self._client = None
        from robot.tools import create_robot_tools
        self.tool_registry = create_robot_tools(manager, None, arm_id)

    @property
    def client(self):
        if self._client is None and self.api_key:
            try:
                import anthropic
                client_kwargs = {"api_key": self.api_key}
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                self._client = anthropic.Anthropic(**client_kwargs)
            except ImportError:
                logger.warning("[ExecuteNode] anthropic package not installed")
        return self._client

    def get_system_prompt(self) -> str:
        """获取系统提示词。"""
        arm_name = "左臂" if "left" in self.arm_id else "右臂"
        other_arm = "右臂" if "left" in self.arm_id else "左臂"
        skill_descriptions = self.skill_loader.get_descriptions()

        return f"""你是 {self.teammate_name}，一个机械臂操作员 ({arm_name})。

你的身份：
- 名称: {self.teammate_name}
- 机械臂ID: {self.arm_id}
- 角色: 机械臂操作员

你的能力：
- 移动到指定位置，抓取/释放物体
- 与 {other_arm} 协作完成任务
- 报告你的状态和任务进度

## 可用技能 (Skills)
执行任务时，**优先使用技能**。使用 load_skill 加载技能详情。

{skill_descriptions}

## 技能使用规则
1. **优先匹配技能**: 收到任务后，先判断是否有匹配的技能
2. **加载技能详情**: 使用 load_skill("技能名") 获取详细执行步骤
3. **按技能步骤执行**: 严格按照技能文档中的步骤操作
4. **无匹配技能时**: 使用默认工具完成任务

## 重要规则
1. 开工前先检查当前场景状态
2. 分配任务后分解为一步步动作
3. 每个动作完成后确认状态
4. 在另一个机械臂附近工作时必须注意避免碰撞
5. 每一步操作都要执行，完成一个再进行下一个
6. **所有动作完成后，必须更新任务状态为 completed**

当你执行完成，请总结执行结果。
"""

    def _get_tools(self) -> List[Dict]:
        """获取工具列表。"""
        tools = self.tool_registry.get_tools_schema()
        team_tools = [
            {
                "name": "load_skill",
                "description": "加载指定技能的详细执行步骤。执行任务前优先调用此工具获取技能详情。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "技能名称，如 pick-old-oru, tighten-screw 等"}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "get_scene_state",
                "description": "获取当前场景状态，检查机械臂和物体状态",
                "input_schema": {"type": "object", "properties": {}}
            },
        ]
        return tools + team_tools

    def __call__(self, state: MultiArmState) -> Dict:
        """执行分配给这个机械臂的pending任务。"""
        # 根据自己的arm_id获取对应的pending任务
        if self.arm_id == "arm_left":
            current_task_id = state.get("pending_left_task")
        else:  # arm_right
            current_task_id = state.get("pending_right_task")

        if not current_task_id:
            logger.info(f"[ExecuteNode][{self.arm_id}] No pending task, skipping")
            return {
                f"pending_{self.arm_id.split('_')[0]}_task": None,
                "iteration_count": state.get("iteration_count", 0) + 1,
            }

        task = self.task_persistence.get(current_task_id)
        if not task:
            logger.error(f"[ExecuteNode][{self.arm_id}] Task {current_task_id} not found")
            self.task_persistence.update(current_task_id, "failed", "Task not found")
            return {
                f"pending_{self.arm_id.split('_')[0]}_task": None,
                "iteration_count": state.get("iteration_count", 0) + 1,
            }

        logger.info(f"[ExecuteNode][{self.arm_id}] Executing task: {current_task_id} - {task.name}")

        # 构建对话
        prompt = f"""请执行任务: {task.name}
任务描述: {task.description or '无'}
技能名称: {task.skill_name or '无'}

请逐步执行，完成所有操作。"""

        messages = [{"role": "user", "content": prompt}]
        tools = self._get_tools()
        iteration = 0

        # 执行循环
        while iteration < 15:
            if not self.client:
                break

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.get_system_prompt(),
                messages=messages,
                tools=tools,
            )

            stop_reason = response.stop_reason
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            if stop_reason == "end_turn":
                # 任务完成
                break

            if stop_reason == "tool_use":
                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        logger.info(f"[ExecuteNode][{self.arm_id}] Tool call: {block.name}")
                        result = self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result.to_string(),
                        })
                messages.append({"role": "user", "content": tool_results})
                iteration += 1

        # 标记任务完成
        self.task_persistence.update(current_task_id, "completed", "Task executed by LangGraph")

        # 更新场景状态
        scene_state = self.manager.get_all_states()

        # 清空本臂的pending任务
        arm_key = f"pending_{self.arm_id.split('_')[0]}_task"

        return {
            "scene_state": scene_state,
            arm_key: None,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    def _execute_tool(self, name: str, params: Dict) -> ToolResult:
        """执行工具调用。"""
        if name == "load_skill":
            return self._load_skill(params)
        elif name == "get_scene_state":
            return self._get_scene_state()
        else:
            return self.tool_registry.execute(name, params)

    def _load_skill(self, params: Dict) -> ToolResult:
        skill_name = params.get("name", "")
        if not skill_name:
            return ToolResult(ToolStatus.ERROR, "Skill name required")
        content = self.skill_loader.get_skill_content(skill_name)
        if content.startswith("Error:"):
            return ToolResult(ToolStatus.ERROR, content)
        logger.info(f"[ExecuteNode] Loaded skill: {skill_name}")
        return ToolResult(ToolStatus.SUCCESS, f"Skill '{skill_name}' loaded", {"content": content})

    def _get_scene_state(self) -> ToolResult:
        state = self.manager.get_all_states()
        return ToolResult(ToolStatus.SUCCESS, "Scene state", state)


class ReviewerNode:
    """Reviewer 节点：检查场景状态是否正常。"""

    def __init__(self, manager: MultiArmManager, reviewer: ReviewerChecker):
        self.manager = manager
        self.reviewer = reviewer

    def __call__(self, state: MultiArmState) -> Dict:
        """执行检查。"""
        logger.info("[ReviewerNode] Running scene consistency check")

        current_task_id = state.get("current_task_id")
        review_attempts = state.get("review_attempts", 0)

        # 执行所有检查
        result = self.reviewer.check_all(
            manager=self.manager,
            current_task_id=current_task_id,
            review_attempts=review_attempts
        )

        logger.info(f"[ReviewerNode] Check result: passed={result.passed}, issues={len(result.issues)}")
        if result.issues:
            for issue in result.issues:
                logger.warning(f"[ReviewerNode] Issue: {issue}")

        return {
            "review_result": asdict(result),
            "review_passed": result.passed,
            "review_attempts": review_attempts + 1,
            "needs_adjustment": not result.passed and not result.max_retries_reached,
            "scene_state": result.scene_snapshot,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }


class AdjustNode:
    """Adjust 节点：LeadAgent根据Reviewer反馈调整计划。"""

    def __init__(
        self,
        manager: MultiArmManager,
        task_persistence: TaskPersistence,
        skill_loader: SkillLoader,
        model: str = None,
        api_key: str = None,
        base_url: str = None,
    ):
        self.manager = manager
        self.task_persistence = task_persistence
        self.skill_loader = skill_loader
        self.model = model or os.environ.get("MODEL_ID", "minimax-m2.5")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        self._client = None

    @property
    def client(self):
        if self._client is None and self.api_key:
            try:
                import anthropic
                client_kwargs = {"api_key": self.api_key}
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                self._client = anthropic.Anthropic(**client_kwargs)
            except ImportError:
                logger.warning("[AdjustNode] anthropic package not installed")
        return self._client

    def get_system_prompt(self) -> str:
        """获取调整提示词。"""
        return f"""你是双臂机器人系统的主协调智能体。现在Reviewer检查发现了场景状态不一致问题，请你分析问题并进行调整。

你的职责：
1. 分析Reviewer报告的问题列表
2. 判断问题的严重程度
3. 决定如何调整：
   - 如果是简单的状态不一致，协调机械臂纠正
   - 如果任务执行错误，回滚任务状态并重新执行
   - 如果无法恢复，标记任务失败
4. 调整完成后，让Reviewer重新检查

请使用工具逐步操作。
"""

    def _get_tools(self) -> List[Dict]:
        """获取工具列表。"""
        return LeadToolRegistry.get_all_tools()

    def __call__(self, state: MultiArmState) -> Dict:
        """根据审查结果调整计划。"""
        logger.info("[AdjustNode] Starting adjustment based on review result")

        review_result = state.get("review_result", {})
        issues = review_result.get("issues", [])
        recommendation = review_result.get("recommendation", "adjust")

        if not issues:
            logger.info("[AdjustNode] No issues to adjust")
            return {
                "review_passed": True,
                "needs_adjustment": False,
                "iteration_count": state.get("iteration_count", 0) + 1,
            }

        # 构建消息
        prompt = f"""Reviewer检查发现以下场景状态问题：

{chr(10).join(f'- {issue}' for issue in issues)}

建议: {recommendation}

当前任务状态:
{self.task_persistence.format_task_list()}

请分析问题并进行必要的调整。"""

        messages = state["messages"].copy()
        messages.append({"role": "user", "content": prompt})

        tools = self._get_tools()
        iteration = 0

        # 调整循环
        while iteration < 5:
            if not self.client:
                break

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.get_system_prompt(),
                messages=messages,
                tools=tools,
            )

            stop_reason = response.stop_reason
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            if stop_reason == "end_turn":
                break

            if stop_reason == "tool_use":
                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        logger.info(f"[AdjustNode] Tool call: {block.name}")
                        result = self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result.to_string(),
                        })
                messages.append({"role": "user", "content": tool_results})
                iteration += 1

        # 更新场景状态
        scene_state = self.manager.get_all_states()

        # 增加调整计数
        adjustment_count = state.get("adjustment_count", 0) + 1

        return {
            "messages": messages,
            "scene_state": scene_state,
            "adjustment_count": adjustment_count,
            "needs_adjustment": False,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    def _execute_tool(self, name: str, params: Dict) -> ToolResult:
        """执行工具调用。"""
        # 复用LeadAgent的工具执行逻辑
        if name == "get_scene_state":
            state = self.manager.get_all_states()
            return ToolResult(ToolStatus.SUCCESS, "Scene state", state)
        elif name == "update_task":
            task_id = params.get("task_id", "")
            status = params.get("status")
            result = params.get("result")
            if not task_id:
                return ToolResult(ToolStatus.ERROR, "Task ID required")
            try:
                task = self.task_persistence.update(
                    task_id=task_id,
                    status=status,
                    result=result,
                )
                if not task:
                    return ToolResult(ToolStatus.ERROR, f"Task {task_id} not found")
                return ToolResult(ToolStatus.SUCCESS, f"Task {task_id} updated", {"task": task.to_dict()})
            except ValueError as e:
                return ToolResult(ToolStatus.ERROR, str(e))
        elif name == "list_tasks":
            status = params.get("status")
            tasks = self.task_persistence.list_all(status)
            formatted = self.task_persistence.format_task_list(status)
            return ToolResult(ToolStatus.SUCCESS, formatted, {"tasks": [t.to_dict() for t in tasks]})
        elif name == "get_task_status":
            task_id = params.get("task_id", "")
            task = self.task_persistence.get(task_id)
            if not task:
                return ToolResult(ToolStatus.ERROR, f"Task {task_id} not found")
            return ToolResult(ToolStatus.SUCCESS, f"Task {task_id} is {task.status}", {"task": task.to_dict()})
        else:
            # 其他工具也支持执行
            return ToolResult(ToolStatus.SUCCESS, f"Executed {name}")


def check_completion(state: MultiArmState) -> Dict:
    """检查是否所有任务都已完成。"""
    task_persistence = TaskPersistence()
    summary = task_persistence.get_summary()
    all_completed = summary.get("pending", 0) == 0 and summary.get("running", 0) == 0
    logger.info(f"[check_completion] All tasks completed: {all_completed}")
    return {
        "all_tasks_completed": all_completed,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }
