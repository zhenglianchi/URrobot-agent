from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger_handler import logger


class ToolStatus(Enum):
    """工具执行状态枚举"""
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class ToolResult:
    """工具执行结果"""
    status: ToolStatus       # 执行状态
    message: str             # 结果消息
    data: Optional[Dict[str, Any]] = None  # 返回数据
    error: Optional[str] = None  # 错误信息

    def to_string(self, max_length: int = 3000) -> str:
        """转换为字符串，截断过长内容"""
        result = {"status": self.status.value, "message": self.message}
        if self.data:
            result["data"] = self.data
        if self.error:
            result["error"] = self.error
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if len(text) > max_length:
            text = text[:max_length] + "\n... (truncated)"
        return text


class ToolRegistry:
    """工具注册表，管理所有可用工具，支持注册和执行"""
    def __init__(self):
        self.tools: Dict[str, Dict] = {}       # 工具定义
        self.handlers: Dict[str, Callable] = {}  # 工具处理函数

    def register(self, name: str, description: str, input_schema: Dict, handler: Callable):
        """注册一个新工具

        参数:
            name: 工具名称
            description: 工具描述（给 AI 看）
            input_schema: 输入参数 schema
            handler: 处理函数
        """
        self.tools[name] = {"name": name, "description": description, "input_schema": input_schema}
        self.handlers[name] = handler

    def get_tools_schema(self) -> List[Dict]:
        """获取所有工具的 schema，给 Claude API"""
        return list(self.tools.values())

    def execute(self, name: str, params: Dict) -> ToolResult:
        """执行工具调用

        参数:
            name: 工具名称
            params: 输入参数字典

        返回:
            工具执行结果
        """
        if name not in self.handlers:
            return ToolResult(status=ToolStatus.FAILED, message=f"Unknown tool: {name}", error="TOOL_NOT_FOUND")
        try:
            return self.handlers[name](**params)
        except Exception as e:
            return ToolResult(status=ToolStatus.FAILED, message=f"Tool error: {str(e)}", error=str(e))


def create_robot_tools(manager, task_queue, arm_id: str = None) -> ToolRegistry:
    """创建机器人工具注册表

    如果 arm_id 指定，则创建受限工具集（只能操作指定机械臂）
    否则创建全局工具集（可以操作任意机械臂）
    """
    registry = ToolRegistry()
    restricted_arm = arm_id

    registry.register(
        name="get_scene_state",
        description="获取完整的工作单元状态，包括所有机械臂和物体。",
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=lambda: _get_scene_state(manager)
    )

    if restricted_arm:
        registry.register(
            name="get_my_state",
            description="获取当前机械臂的状态。",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: _get_arm_state(manager, restricted_arm)
        )
    else:
        registry.register(
            name="get_arm_state",
            description="获取指定机械臂的状态。",
            input_schema={
                "type": "object",
                "properties": {"arm_id": {"type": "string", "description": "机械臂ID: 'arm_left' 或 'arm_right'"}},
                "required": ["arm_id"]
            },
            handler=lambda arm_id: _get_arm_state(manager, arm_id)
        )

    registry.register(
        name="get_object_info",
        description="获取指定物体的信息。",
        input_schema={
            "type": "object",
            "properties": {"object_id": {"type": "string", "description": "物体ID"}},
            "required": ["object_id"]
        },
        handler=lambda object_id: _get_object_info(manager, object_id)
    )

    registry.register(
        name="get_available_arms",
        description="获取可分配任务的空闲机械臂列表。",
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=lambda: _get_available_arms(manager)
    )

    if restricted_arm:
        registry.register(
            name="move_to_position",
            description="移动当前机械臂到目标位置 [x, y, z, rx, ry, rz]。",
            input_schema={
                "type": "object",
                "properties": {
                    "position": {"type": "array", "items": {"type": "number"}, "description": "目标位置 [x,y,z,rx,ry,rz]"}
                },
                "required": ["position"]
            },
            handler=lambda position: _move_arm_to_position(manager, restricted_arm, position)
        )

        registry.register(
            name="move_to_object",
            description="移动当前机械臂到物体位置。",
            input_schema={
                "type": "object",
                "properties": {
                    "object_id": {"type": "string", "description": "目标物体ID"},
                    "phase": {"type": "string", "enum": ["approach", "grasp", "place"], "description": "移动阶段"}
                },
                "required": ["object_id", "phase"]
            },
            handler=lambda object_id, phase: _move_arm_to_object(manager, restricted_arm, object_id, phase)
        )

        registry.register(
            name="move_relative",
            description="相对于当前位置移动机械臂。",
            input_schema={
                "type": "object",
                "properties": {
                    "dx": {"type": "number", "description": "X轴偏移量 (米)"},
                    "dy": {"type": "number", "description": "Y轴偏移量 (米)"},
                    "dz": {"type": "number", "description": "Z轴偏移量 (米)"}
                },
                "required": []
            },
            handler=lambda dx=0, dy=0, dz=0: _move_arm_relative(manager, restricted_arm, dx, dy, dz)
        )

        registry.register(
            name="open_gripper",
            description="打开当前机械臂的夹爪。",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: _open_gripper(manager, restricted_arm)
        )

        registry.register(
            name="close_gripper",
            description="闭合夹爪以抓取物体。",
            input_schema={
                "type": "object",
                "properties": {
                    "object_id": {"type": "string", "description": "被抓取的物体ID（可选）"}
                },
                "required": []
            },
            handler=lambda object_id=None: _close_gripper(manager, restricted_arm, object_id)
        )

        registry.register(
            name="pick_object",
            description="执行完整的拾取操作：接近、抓取、闭合夹爪、撤回。",
            input_schema={
                "type": "object",
                "properties": {
                    "object_id": {"type": "string", "description": "要拾取的物体"}
                },
                "required": ["object_id"]
            },
            handler=lambda object_id: _pick_object(manager, restricted_arm, object_id)
        )

        registry.register(
            name="place_object",
            description="执行完整的放置操作：接近、打开夹爪、撤回。",
            input_schema={
                "type": "object",
                "properties": {
                    "target_id": {"type": "string", "description": "目标位置ID"}
                },
                "required": ["target_id"]
            },
            handler=lambda target_id: _place_object(manager, restricted_arm, target_id)
        )

        registry.register(
            name="stop",
            description="紧急停止当前机械臂。",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: _stop_arm(manager, restricted_arm)
        )

        registry.register(
            name="toggle_screw",
            description="使用螺丝刀操作装配站的螺丝：拧松或拧紧。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["loosen", "tighten"], "description": "loosen=拧松螺丝（拆卸），tighten=拧紧螺丝（安装）"}
                },
                "required": ["action"]
            },
            handler=lambda action: _toggle_screw(manager, restricted_arm, action)
        )

        registry.register(
            name="reset",
            description="重置当前机械臂到原点位置，打开夹爪清空状态。",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: _reset_arm(manager, restricted_arm)
        )

        registry.register(
            name="move_home",
            description="移动当前机械臂回到初始home位置。任务完成后调用此工具。",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: _move_home(manager, restricted_arm)
        )
    else:
        registry.register(
            name="move_arm_to_position",
            description="移动机械臂到目标位置 [x, y, z, rx, ry, rz]。",
            input_schema={
                "type": "object",
                "properties": {
                    "arm_id": {"type": "string", "description": "要移动的机械臂"},
                    "position": {"type": "array", "items": {"type": "number"}, "description": "目标位置 [x,y,z,rx,ry,rz]"}
                },
                "required": ["arm_id", "position"]
            },
            handler=lambda arm_id, position: _move_arm_to_position(manager, arm_id, position)
        )

        registry.register(
            name="move_arm_to_object",
            description="移动机械臂到物体位置。",
            input_schema={
                "type": "object",
                "properties": {
                    "arm_id": {"type": "string", "description": "要移动的机械臂"},
                    "object_id": {"type": "string", "description": "目标物体ID"},
                    "phase": {"type": "string", "enum": ["approach", "grasp", "place"], "description": "移动阶段"}
                },
                "required": ["arm_id", "object_id", "phase"]
            },
            handler=lambda arm_id, object_id, phase: _move_arm_to_object(manager, arm_id, object_id, phase)
        )

        registry.register(
            name="move_arm_relative",
            description="相对于当前位置移动机械臂。",
            input_schema={
                "type": "object",
                "properties": {
                    "arm_id": {"type": "string", "description": "要移动的机械臂"},
                    "dx": {"type": "number", "description": "X轴偏移量 (米)"},
                    "dy": {"type": "number", "description": "Y轴偏移量 (米)"},
                    "dz": {"type": "number", "description": "Z轴偏移量 (米)"}
                },
                "required": ["arm_id"]
            },
            handler=lambda arm_id, dx=0, dy=0, dz=0: _move_arm_relative(manager, arm_id, dx, dy, dz)
        )

        registry.register(
            name="open_gripper",
            description="打开指定机械臂的夹爪。",
            input_schema={
                "type": "object",
                "properties": {"arm_id": {"type": "string", "description": "机械臂ID"}},
                "required": ["arm_id"]
            },
            handler=lambda arm_id: _open_gripper(manager, arm_id)
        )

        registry.register(
            name="close_gripper",
            description="闭合夹爪以抓取物体。",
            input_schema={
                "type": "object",
                "properties": {
                    "arm_id": {"type": "string", "description": "机械臂ID"},
                    "object_id": {"type": "string", "description": "被抓取的物体ID（可选）"}
                },
                "required": ["arm_id"]
            },
            handler=lambda arm_id, object_id=None: _close_gripper(manager, arm_id, object_id)
        )

        registry.register(
            name="pick_object",
            description="执行完整的拾取操作：接近、抓取、闭合夹爪、撤回。",
            input_schema={
                "type": "object",
                "properties": {
                    "arm_id": {"type": "string", "description": "使用的机械臂"},
                    "object_id": {"type": "string", "description": "要拾取的物体"}
                },
                "required": ["arm_id", "object_id"]
            },
            handler=lambda arm_id, object_id: _pick_object(manager, arm_id, object_id)
        )

        registry.register(
            name="place_object",
            description="执行完整的放置操作：接近、打开夹爪、撤回。",
            input_schema={
                "type": "object",
                "properties": {
                    "arm_id": {"type": "string", "description": "使用的机械臂"},
                    "target_id": {"type": "string", "description": "目标位置ID"}
                },
                "required": ["arm_id", "target_id"]
            },
            handler=lambda arm_id, target_id: _place_object(manager, arm_id, target_id)
        )

        registry.register(
            name="stop_arm",
            description="紧急停止指定机械臂。",
            input_schema={
                "type": "object",
                "properties": {"arm_id": {"type": "string", "description": "要停止的机械臂"}},
                "required": ["arm_id"]
            },
            handler=lambda arm_id: _stop_arm(manager, arm_id)
        )

        registry.register(
            name="toggle_screw",
            description="使用螺丝刀操作装配站的螺丝：拧松或拧紧。",
            input_schema={
                "type": "object",
                "properties": {
                    "arm_id": {"type": "string", "description": "使用的机械臂"},
                    "action": {"type": "string", "enum": ["loosen", "tighten"], "description": "loosen=拧松螺丝（拆卸），tighten=拧紧螺丝（安装）"}
                },
                "required": ["arm_id", "action"]
            },
            handler=lambda arm_id, action: _toggle_screw(manager, arm_id, action)
        )

        registry.register(
            name="reset_arm",
            description="重置机械臂到原点位置。",
            input_schema={
                "type": "object",
                "properties": {"arm_id": {"type": "string", "description": "要重置的机械臂"}},
                "required": ["arm_id"]
            },
            handler=lambda arm_id: _reset_arm(manager, arm_id)
        )

    registry.register(
        name="get_task_status",
        description="获取当前任务队列状态。",
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=lambda: _get_task_status(task_queue)
    )

    registry.register(
        name="get_ready_tasks",
        description="获取准备执行的任务。",
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=lambda: _get_ready_tasks(task_queue)
    )

    registry.register(
        name="start_task",
        description="在指定机械臂上开始任务。",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
                "arm_id": {"type": "string", "description": "分配的机械臂"}
            },
            "required": ["task_id", "arm_id"]
        },
        handler=lambda task_id, arm_id: _start_task(task_queue, manager, task_id, arm_id)
    )

    registry.register(
        name="complete_task",
        description="标记任务已完成。",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "任务ID"}},
            "required": ["task_id"]
        },
        handler=lambda task_id: _complete_task(task_queue, manager, task_id)
    )

    return registry


def _get_scene_state(manager) -> ToolResult:
    return ToolResult(status=ToolStatus.SUCCESS, message="Workcell state", data=manager.get_all_states())

def _get_arm_state(manager, arm_id: str) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    return ToolResult(status=ToolStatus.SUCCESS, message=f"State of {arm_id}", data=arm.state.to_dict())

def _get_object_info(manager, object_id: str) -> ToolResult:
    obj_info = manager.get_object_info(object_id)
    obj_state = manager.get_object_state(object_id)
    if not obj_info:
        return ToolResult(status=ToolStatus.FAILED, message=f"Object not found: {object_id}", error="OBJECT_NOT_FOUND")
    return ToolResult(status=ToolStatus.SUCCESS, message=f"Info for {object_id}", data={"info": obj_info, "state": obj_state})

def _get_available_arms(manager) -> ToolResult:
    return ToolResult(status=ToolStatus.SUCCESS, message="Available arms", data={"available_arms": manager.get_available_arms()})

def _move_arm_to_position(manager, arm_id: str, position: List[float]) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    if arm.state.is_busy():
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm {arm_id} is busy", error="ARM_BUSY")
    success = arm.moveL(position)
    if success:
        return ToolResult(status=ToolStatus.SUCCESS, message=f"Arm {arm_id} moved", data={"position": position})
    return ToolResult(status=ToolStatus.FAILED, message="Move failed", error="MOVE_FAILED")

def _move_arm_to_object(manager, arm_id: str, object_id: str, phase: str) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    if arm.state.is_busy():
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm {arm_id} is busy", error="ARM_BUSY")
    
    obj_info = manager.get_object_info(object_id)
    if not obj_info:
        return ToolResult(status=ToolStatus.FAILED, message=f"Object not found: {object_id}", error="OBJECT_NOT_FOUND")
    
    pos = obj_info.get("position", [0, 0, 0])
    offset = obj_info.get("approach_offset", [0, 0, 0.1])
    if len(pos) < 6:
        pos = list(pos) + [0, 3.14159, 0]
    
    if phase == "approach":
        target = [pos[0] + offset[0], pos[1] + offset[1], pos[2] + offset[2], pos[3], pos[4], pos[5]]
    else:
        target = pos.copy()
    
    success = arm.moveL(target)
    if success:
        return ToolResult(status=ToolStatus.SUCCESS, message=f"Arm {arm_id} moved to {object_id} ({phase})", data={"position": target})
    return ToolResult(status=ToolStatus.FAILED, message="Move failed", error="MOVE_FAILED")

def _move_arm_relative(manager, arm_id: str, dx: float, dy: float, dz: float) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    if arm.state.is_busy():
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm {arm_id} is busy", error="ARM_BUSY")
    success = arm.move_relative(dx, dy, dz)
    if success:
        return ToolResult(status=ToolStatus.SUCCESS, message=f"Arm {arm_id} moved relative", data={"new_position": arm.get_tcp()})
    return ToolResult(status=ToolStatus.FAILED, message="Move failed", error="MOVE_FAILED")

def _open_gripper(manager, arm_id: str) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    
    held_object = arm.state.object_in_hand
    arm.open_gripper()
    if held_object:
        manager.update_object_state(held_object, clear_held_by=True)
    return ToolResult(status=ToolStatus.SUCCESS, message=f"Arm {arm_id} gripper opened")

def _close_gripper(manager, arm_id: str, object_id: Optional[str]) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    arm.close_gripper()
    if object_id:
        arm.set_object_in_hand(object_id)
        manager.update_object_state(object_id, held_by=arm_id, status="held")
    return ToolResult(status=ToolStatus.SUCCESS, message=f"Arm {arm_id} gripper closed", data={"holding": object_id})

def _pick_object(manager, arm_id: str, object_id: str) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    if arm.state.is_busy():
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm {arm_id} is busy", error="ARM_BUSY")
    
    obj_info = manager.get_object_info(object_id)
    if not obj_info:
        return ToolResult(status=ToolStatus.FAILED, message=f"Object not found: {object_id}", error="OBJECT_NOT_FOUND")
    
    pos = obj_info.get("position", [0, 0, 0])
    offset = obj_info.get("approach_offset", [0, 0, 0.1])
    if len(pos) < 6:
        pos = list(pos) + [0, 3.14159, 0]
    
    approach = [pos[0] + offset[0], pos[1] + offset[1], pos[2] + offset[2], pos[3], pos[4], pos[5]]
    
    arm.moveL(approach)
    arm.moveL(pos)
    arm.close_gripper()
    arm.set_object_in_hand(object_id)
    manager.update_object_state(object_id, held_by=arm_id, status="held")
    arm.moveL(approach)
    
    return ToolResult(status=ToolStatus.SUCCESS, message=f"Arm {arm_id} picked {object_id}", data={"object_id": object_id})

def _place_object(manager, arm_id: str, target_id: str) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    if arm.state.is_busy():
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm {arm_id} is busy", error="ARM_BUSY")
    if not arm.state.object_in_hand:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm {arm_id} not holding anything", error="NO_OBJECT")
    
    held_object = arm.state.object_in_hand
    
    target_info = manager.get_object_info(target_id)
    if not target_info:
        return ToolResult(status=ToolStatus.FAILED, message=f"Target not found: {target_id}", error="TARGET_NOT_FOUND")
    
    pos = target_info.get("position", [0, 0, 0])
    offset = target_info.get("approach_offset", [0, 0, 0.1])
    if len(pos) < 6:
        pos = list(pos) + [0, 3.14159, 0]
    
    approach = [pos[0] + offset[0], pos[1] + offset[1], pos[2] + offset[2], pos[3], pos[4], pos[5]]
    
    arm.moveL(approach)
    arm.moveL(pos)
    manager.update_object_state(held_object, clear_held_by=True, status=f"placed_at_{target_id}")
    arm.open_gripper()
    arm.moveL(approach)
    
    return ToolResult(status=ToolStatus.SUCCESS, message=f"Arm {arm_id} placed {held_object} at {target_id}")

def _stop_arm(manager, arm_id: str) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    arm.stop()
    return ToolResult(status=ToolStatus.SUCCESS, message=f"Arm {arm_id} stopped")

def _reset_arm(manager, arm_id: str) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    arm.moveL(arm.state.home_position)
    arm.open_gripper()
    arm.set_object_in_hand(None)
    arm.set_current_task(None)
    return ToolResult(status=ToolStatus.SUCCESS, message=f"Arm {arm_id} reset to home")


def _move_home(manager, arm_id: str) -> ToolResult:
    """移动回初始home位置"""
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"机械臂未找到: {arm_id}", error="ARM_NOT_FOUND")
    if arm.state.is_busy():
        return ToolResult(status=ToolStatus.FAILED, message=f"机械臂 {arm_id} 繁忙", error="ARM_BUSY")
    success = arm.moveL(arm.state.home_position)
    if success:
        return ToolResult(status=ToolStatus.SUCCESS, message=f"机械臂 {arm_id} 已回到初始位置")
    return ToolResult(status=ToolStatus.FAILED, message=f"移动失败", error="MOVE_FAILED")

def _get_task_status(task_queue) -> ToolResult:
    return ToolResult(status=ToolStatus.SUCCESS, message="Task status", data=task_queue.get_all_status())

def _get_ready_tasks(task_queue) -> ToolResult:
    ready = task_queue.get_ready_tasks()
    return ToolResult(status=ToolStatus.SUCCESS, message="Ready tasks", data={"tasks": [t.to_dict() for t in ready]})

def _start_task(task_queue, manager, task_id: str, arm_id: str) -> ToolResult:
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm not found: {arm_id}", error="ARM_NOT_FOUND")
    if arm.state.is_busy():
        return ToolResult(status=ToolStatus.FAILED, message=f"Arm {arm_id} is busy", error="ARM_BUSY")
    success = task_queue.start_task(task_id, arm_id)
    if success:
        arm.set_current_task(task_id)
        return ToolResult(status=ToolStatus.SUCCESS, message=f"Task {task_id} started on {arm_id}")
    return ToolResult(status=ToolStatus.FAILED, message=f"Failed to start task {task_id}")

def _complete_task(task_queue, manager, task_id: str) -> ToolResult:
    task = task_queue.get_task(task_id)
    if not task:
        return ToolResult(status=ToolStatus.FAILED, message=f"Task not found: {task_id}", error="TASK_NOT_FOUND")
    arm_id = task.assigned_arm
    success = task_queue.complete_task(task_id)
    if success and arm_id:
        arm = manager.get_arm(arm_id)
        if arm:
            arm.set_current_task(None)
    if success:
        return ToolResult(status=ToolStatus.SUCCESS, message=f"Task {task_id} completed")
    return ToolResult(status=ToolStatus.FAILED, message=f"Failed to complete task {task_id}")


def _toggle_screw(manager, arm_id: str, action: str) -> ToolResult:
    """拧螺丝操作：拧松或拧紧装配站的螺丝"""
    arm = manager.get_arm(arm_id)
    if not arm:
        return ToolResult(status=ToolStatus.FAILED, message=f"机械臂未找到: {arm_id}", error="ARM_NOT_FOUND")
    if arm.state.is_busy():
        return ToolResult(status=ToolStatus.FAILED, message=f"机械臂 {arm_id} 繁忙", error="ARM_BUSY")

    # 检查是否拿着螺丝刀
    if arm.state.object_in_hand != "screwdriver":
        return ToolResult(status=ToolStatus.FAILED,
                          message=f"操作需要手持螺丝刀，当前机械臂拿着 {arm.state.object_in_hand}",
                          error="REQUIRE_SCREWDRIVER")

    # 获取装配站位置
    screw_position = manager.get_object_position("assembly_station")
    if not screw_position:
        return ToolResult(status=ToolStatus.FAILED, message=f"装配站未找到", error="STATION_NOT_FOUND")

    # 补全为6维坐标
    pos = list(screw_position)
    if len(pos) < 6:
        pos += [0, 3.14159, 0][len(pos)-3:]

    # 根据操作移动到螺丝位置进行操作
    offset = [0, 0, 0.05]
    approach_pos = [pos[0]+offset[0], pos[1]+offset[1], pos[2]+offset[2], pos[3], pos[4], pos[5]]

    arm.moveL(approach_pos)
    arm.moveL(pos)

    # 模拟螺丝操作
    if action == "loosen":
        message = "螺丝已拧松，可以拆卸ORU"
    else:
        message = "螺丝已拧紧，ORU安装完成"

    arm.moveL(approach_pos)
    return ToolResult(status=ToolStatus.SUCCESS, message=message, data={"action": action})
