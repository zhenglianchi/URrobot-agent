from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import threading
import time
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger_handler import logger


class ArmStatus(Enum):
    """机械臂状态枚举"""
    IDLE = "idle"         # 空闲
    MOVING = "moving"     # 移动中
    WORKING = "working"   # 工作中
    ERROR = "error"       # 错误


@dataclass
class ArmState:
    """机械臂状态数据结构"""
    arm_id: str
    name: str
    host: str = ""
    status: ArmStatus = ArmStatus.IDLE
    position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    gripper_closed: bool = False
    object_in_hand: Optional[str] = None
    current_task: Optional[str] = None
    reachable_zones: List[str] = field(default_factory=list)
    home_position: List[float] = field(default_factory=lambda: [0.3, 0.0, 0.4, 0.0, 3.14159, 0.0])
    use_simulator: bool = True
    
    def is_busy(self) -> bool:
        return self.status not in [ArmStatus.IDLE, ArmStatus.ERROR]
    
    def to_dict(self) -> Dict:
        return {
            "arm_id": self.arm_id,
            "name": self.name,
            "host": self.host,
            "status": self.status.value,
            "position": self.position,
            "gripper_closed": self.gripper_closed,
            "object_in_hand": self.object_in_hand,
            "current_task": self.current_task,
            "reachable_zones": self.reachable_zones,
            "use_simulator": self.use_simulator,
        }


class RobotArm:
    """单个机械臂控制器，支持仿真模式和真实UR机械臂连接

    通过 RTDE 协议连接真实 Universal Robots 机械臂。
    仿真模式下只模拟移动，不实际发送指令。
    """
    def __init__(self, arm_id: str, name: str, home_position: List[float],
                 reachable_zones: List[str], host: str = "", use_simulator: bool = True):
        """
        参数:
            arm_id: 机械臂唯一ID
            name: 机械臂名称
            home_position: 初始原点位置
            reachable_zones: 可到达的工作区列表
            host: 真实机械臂IP地址
            use_simulator: 是否使用仿真模式
        """
        self.state = ArmState(
            arm_id=arm_id,
            name=name,
            host=host,
            position=home_position.copy(),
            home_position=home_position.copy(),
            reachable_zones=reachable_zones,
            use_simulator=use_simulator
        )
        self._position = home_position.copy()
        self._gripper_closed = False
        self._lock = threading.Lock()  # 线程安全锁
        self._real_robot = None  # RTDE 客户端

        if not use_simulator and host:
            self._connect_real_robot(host)

        mode = "simulator" if use_simulator else f"real({host})"
        logger.info(f"[Arm] {name} initialized ({mode})")

    def _connect_real_robot(self, host: str):
        """连接真实 UR 机械臂通过 RTDE 协议"""
        try:
            import rtde_control
            import rtde_receive
            self._rtde_c = rtde_control.RTDEControlInterface(host)
            self._rtde_r = rtde_receive.RTDEReceiveInterface(host)
            self._real_robot = True
            logger.info(f"[Arm] {self.state.name} connected to {host}")
        except Exception as e:
            logger.error(f"[Arm] Failed to connect to {host}: {e}")
            self._real_robot = False
            self.state.use_simulator = True

    def get_tcp(self) -> List[float]:
        """获取当前工具中心点(TCP)位姿 [x, y, z, rx, ry, rz]

        返回:
            6维位姿列表
        """
        with self._lock:
            if self._real_robot:
                return list(self._rtde_r.getActualTCPPose())
            return self._position.copy()

    def moveL(self, position: List[float], speed: float = 0.05) -> bool:
        """直线移动到目标位姿

        参数:
            position: 目标位姿 [x, y, z, rx, ry, rz] (米, 弧度)
            speed: 移动速度 (m/s)

        返回:
            是否移动成功
        """
        with self._lock:
            self.state.status = ArmStatus.MOVING
            
            if self._real_robot:
                try:
                    self._rtde_c.moveL(position, speed, 0.2)
                    self.state.position = position.copy()
                    self.state.status = ArmStatus.IDLE
                    return True
                except Exception as e:
                    logger.error(f"[Arm] moveL error: {e}")
                    self.state.status = ArmStatus.ERROR
                    return False
            else:
                time.sleep(0.3)
                self._position = position.copy()
                self.state.position = position.copy()
                self.state.status = ArmStatus.IDLE
                return True
    
    def move_relative(self, dx: float = 0, dy: float = 0, dz: float = 0) -> bool:
        with self._lock:
            self.state.status = ArmStatus.MOVING
            
            if self._real_robot:
                try:
                    current = list(self._rtde_r.getActualTCPPose())
                    target = [current[0] + dx, current[1] + dy, current[2] + dz,
                              current[3], current[4], current[5]]
                    self._rtde_c.moveL(target, 0.05, 0.2)
                    self.state.position = target
                    self.state.status = ArmStatus.IDLE
                    return True
                except Exception as e:
                    logger.error(f"[Arm] move_relative error: {e}")
                    self.state.status = ArmStatus.ERROR
                    return False
            else:
                time.sleep(0.2)
                self._position[0] += dx
                self._position[1] += dy
                self._position[2] += dz
                self.state.position = self._position.copy()
                self.state.status = ArmStatus.IDLE
                return True
    
    def open_gripper(self):
        with self._lock:
            if self._real_robot:
                try:
                    self._rtde_c.setToolDigitalOut(0, False)
                except Exception as e:
                    logger.error(f"[Arm] open_gripper error: {e}")
            else:
                time.sleep(0.1)
            
            self._gripper_closed = False
            self.state.gripper_closed = False
            self.state.object_in_hand = None
            logger.info(f"[Arm] {self.state.name} gripper opened")
    
    def close_gripper(self):
        with self._lock:
            if self._real_robot:
                try:
                    self._rtde_c.setToolDigitalOut(0, True)
                except Exception as e:
                    logger.error(f"[Arm] close_gripper error: {e}")
            else:
                time.sleep(0.1)
            
            self._gripper_closed = True
            self.state.gripper_closed = True
            logger.info(f"[Arm] {self.state.name} gripper closed")
    
    def stop(self):
        with self._lock:
            if self._real_robot:
                try:
                    self._rtde_c.stopL()
                except:
                    pass
            self.state.status = ArmStatus.IDLE
            logger.info(f"[Arm] {self.state.name} stopped")
    
    def set_object_in_hand(self, object_id: Optional[str]):
        with self._lock:
            self.state.object_in_hand = object_id
    
    def set_current_task(self, task_id: Optional[str]):
        with self._lock:
            self.state.current_task = task_id
    
    def can_reach(self, zone: str) -> bool:
        return zone in self.state.reachable_zones
    
    def disconnect(self):
        if self._real_robot:
            try:
                self._rtde_c.disconnect()
                logger.info(f"[Arm] {self.state.name} disconnected")
            except:
                pass


class MultiArmManager:
    """多机械臂管理器，统一管理多个机械臂和场景物体

    职责：
    - 从配置文件加载机械臂和物体
    - 提供查询空闲机械臂、获取物体位置等接口
    - 维护物体状态（谁持有物体、位置等）
    - 统一重置和断开连接
    """
    def __init__(self, config_path: Optional[str] = None, use_simulator: bool = True):
        self.arms: Dict[str, RobotArm] = {}          # 机械臂字典 {arm_id: RobotArm}
        self.objects: Dict[str, Dict] = {}           # 物体定义（从配置加载）
        self.object_states: Dict[str, Dict] = {}     # 物体当前状态
        self._lock = threading.Lock()                # 线程安全锁
        self.use_simulator = use_simulator

        if config_path:
            self.load_config(config_path)

        logger.info(f"[MultiArmManager] Initialized with {len(self.arms)} arms")

    def load_config(self, config_path: str):
        """从JSON配置文件加载机械臂和物体定义"""
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        for arm_id, arm_config in config.get("robots", {}).items():
            arm = RobotArm(
                arm_id=arm_id,
                name=arm_config.get("name", arm_id),
                host=arm_config.get("host", ""),
                home_position=arm_config.get("home_position", [0.3, 0.0, 0.4, 0.0, 3.14159, 0.0]),
                reachable_zones=arm_config.get("reachable_zones", []),
                use_simulator=self.use_simulator
            )
            self.arms[arm_id] = arm
        
        self.objects = config.get("objects", {})

        for obj_id, obj_data in self.objects.items():
            self.object_states[obj_id] = {
                "status": obj_data.get("status", "unknown"),
                "held_by": None,
                "position": obj_data.get("position", [0, 0, 0])
            }

        logger.info(f"[MultiArmManager] Loaded: {len(self.arms)} arms, {len(self.objects)} objects")

    def get_arm(self, arm_id: str) -> Optional[RobotArm]:
        """按ID获取机械臂实例"""
        return self.arms.get(arm_id)

    def get_available_arm(self, zone: Optional[str] = None) -> Optional[str]:
        """获取一个空闲机械臂

        参数:
            zone: 如果指定，只返回能到达该工作区的机械臂

        返回:
            空闲机械臂ID，如果没有返回 None
        """
        with self._lock:
            for arm_id, arm in self.arms.items():
                if not arm.state.is_busy():
                    if zone is None or arm.can_reach(zone):
                        return arm_id
            return None

    def get_available_arms(self) -> List[str]:
        """获取所有空闲机械臂ID列表"""
        with self._lock:
            return [arm_id for arm_id, arm in self.arms.items() if not arm.state.is_busy()]

    def get_object_position(self, object_id: str) -> Optional[List[float]]:
        """获取物体的初始位置"""
        obj = self.objects.get(object_id)
        if obj:
            return obj.get("position", [0, 0, 0])
        return None

    def get_object_info(self, object_id: str) -> Optional[Dict]:
        """获取物体完整信息（从配置）"""
        return self.objects.get(object_id)

    def get_approach_position(self, object_id: str) -> Optional[List[float]]:
        """计算物体的接近位置（物体位置加上接近偏移）

        抓取前先移动到接近位置，再直线移动到目标位置
        """
        obj = self.objects.get(object_id)
        if obj:
            pos = obj.get("position", [0, 0, 0])
            offset = obj.get("approach_offset", [0, 0, 0.1])
            if len(pos) < 6:
                pos = list(pos) + [0, 3.14159, 0]
            return [pos[0] + offset[0], pos[1] + offset[1], pos[2] + offset[2],
                    pos[3], pos[4], pos[5]]
        return None

    def update_object_state(self, object_id: str, status: str = None,
                           held_by: str = None, position: List[float] = None):
        """更新物体状态

        参数:
            object_id: 物体ID
            status: 新状态
            held_by: 持有该物体的机械臂ID
            position: 新位置
        """
        with self._lock:
            if object_id in self.object_states:
                if status is not None:
                    self.object_states[object_id]["status"] = status
                if held_by is not None:
                    self.object_states[object_id]["held_by"] = held_by
                if position is not None:
                    self.object_states[object_id]["position"] = position

    def get_object_state(self, object_id: str) -> Optional[Dict]:
        """获取物体当前状态"""
        return self.object_states.get(object_id)

    def get_all_states(self) -> Dict:
        """获取完整场景状态（所有机械臂+所有物体）"""
        with self._lock:
            available_arms = [arm_id for arm_id, arm in self.arms.items() if not arm.state.is_busy()]
            return {
                "arms": {arm_id: arm.state.to_dict() for arm_id, arm in self.arms.items()},
                "objects": self.object_states,
                "available_arms": available_arms,
            }

    def get_scene_summary(self) -> str:
        """获取场景状态的可读文本摘要"""
        with self._lock:
            lines = ["## Workcell State", ""]
            lines.append("### Arms:")
            for arm_id, arm in self.arms.items():
                status = arm.state.status.value
                task = arm.state.current_task or "idle"
                obj = arm.state.object_in_hand or "none"
                lines.append(f"  - {arm.state.name}: {status}, task={task}, holding={obj}")

            lines.append("\n### Objects:")
            for obj_id, state in self.object_states.items():
                status = state.get("status", "unknown")
                held = state.get("held_by", "none")
                lines.append(f"  - {obj_id}: {status}, held_by={held}")

            return "\n".join(lines)

    def reset(self):
        """重置所有机械臂到原点，打开夹爪，重置物体状态"""
        with self._lock:
            for arm in self.arms.values():
                arm.moveL(arm.state.home_position)
                arm.open_gripper()
                arm.set_current_task(None)
                arm.set_object_in_hand(None)

            # 重置所有物体状态到初始值
            for obj_id, obj_data in self.objects.items():
                self.object_states[obj_id] = {
                    "status": obj_data.get("status", "unknown"),
                    "held_by": None,
                    "position": obj_data.get("position", [0, 0, 0])
                }

        logger.info("[MultiArmManager] All arms reset")

    def disconnect_all(self):
        """断开所有机械臂连接"""
        for arm in self.arms.values():
            arm.disconnect()
        logger.info("[MultiArmManager] All arms disconnected")
