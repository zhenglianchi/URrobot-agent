import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class MessageType(Enum):
    """团队消息类型枚举"""
    MESSAGE = "message"              # 普通消息
    BROADCAST = "broadcast"          # 广播
    TASK_ASSIGNMENT = "task_assignment"  # 任务分配
    TASK_STATUS = "task_status"      # 任务状态更新
    COORDINATION = "coordination"    # 协作请求
    SHUTDOWN_REQUEST = "shutdown_request"  # 关闭请求
    SHUTDOWN_RESPONSE = "shutdown_response"  # 关闭响应
    PLAN_SUBMISSION = "plan_submission"    # 计划提交
    PLAN_APPROVAL = "plan_approval"  # 计划批准


@dataclass
class TeamMessage:
    """团队消息结构，用于队友之间的通信"""
    msg_type: str               # 消息类型
    sender: str                  # 发送者名称
    receiver: str                # 接收者名称
    content: str                 # 消息内容
    timestamp: float = field(default_factory=time.time)  # 时间戳
    extra: Dict = field(default_factory=dict)  # 额外字段

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "msg_type": self.msg_type,
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "timestamp": self.timestamp,
            **self.extra
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "TeamMessage":
        """从字典创建消息"""
        return cls(
            msg_type=data.get("msg_type", "message"),
            sender=data.get("sender", ""),
            receiver=data.get("receiver", ""),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", time.time()),
            extra={k: v for k, v in data.items()
                   if k not in ["msg_type", "sender", "receiver", "content", "timestamp"]}
        )


class MessageBus:
    """消息总线，负责队友之间的消息传递

    支持：
    - 点对点发送
    - 广播
    - 持久化到文件
    - 回调注册
    线程安全
    """
    def __init__(self, inbox_dir: Optional[Path] = None):
        """
        参数:
            inbox_dir: 收件箱持久化目录，None 不持久化
        """
        self.inbox_dir = inbox_dir
        if inbox_dir:
            self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self._inboxes: Dict[str, List[TeamMessage]] = {}  # 每个接收者的收件箱
        self._lock = threading.Lock()                       # 线程安全锁
        self._callbacks: Dict[str, List[callable]] = {}    # 每个接收者的回调列表

    def register_callback(self, name: str, callback: callable):
        """注册消息回调，当收到消息时会调用

        参数:
            name: 接收者名称
            callback: 回调函数，参数是 TeamMessage
        """
        with self._lock:
            if name not in self._callbacks:
                self._callbacks[name] = []
            self._callbacks[name].append(callback)

    def send(self, sender: str, receiver: str, content: str,
             msg_type: str = "message", extra: Dict = None) -> str:
        """发送消息到指定接收者

        参数:
            sender: 发送者名称
            receiver: 接收者名称
            content: 消息内容
            msg_type: 消息类型
            extra: 额外字段

        返回:
            确认信息
        """
        msg = TeamMessage(
            msg_type=msg_type,
            sender=sender,
            receiver=receiver,
            content=content,
            extra=extra or {}
        )

        with self._lock:
            if receiver not in self._inboxes:
                self._inboxes[receiver] = []
            self._inboxes[receiver].append(msg)

        # 持久化到文件
        if self.inbox_dir:
            inbox_path = self.inbox_dir / f"{receiver}.jsonl"
            with open(inbox_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")

        # 触发回调
        with self._lock:
            callbacks = self._callbacks.get(receiver, [])
            for callback in callbacks:
                try:
                    callback(msg)
                except Exception:
                    pass

        return f"Sent {msg_type} from {sender} to {receiver}"

    def read_inbox(self, name: str) -> List[TeamMessage]:
        """读取并清空收件箱

        参数:
            name: 接收者名称

        返回:
            消息列表
        """
        messages = []
        
        with self._lock:
            if name in self._inboxes:
                messages = self._inboxes[name].copy()
                self._inboxes[name] = []
        
        if self.inbox_dir:
            inbox_path = self.inbox_dir / f"{name}.jsonl"
            if inbox_path.exists():
                for line in inbox_path.read_text(encoding="utf-8").strip().splitlines():
                    if line:
                        try:
                            msg_dict = json.loads(line)
                            messages.append(TeamMessage.from_dict(msg_dict))
                        except json.JSONDecodeError:
                            continue
                inbox_path.write_text("", encoding="utf-8")
        
        return messages
    
    def broadcast(self, sender: str, content: str, teammates: List[str], 
                  msg_type: str = "broadcast") -> str:
        count = 0
        for name in teammates:
            if name != sender:
                self.send(sender, name, content, msg_type)
                count += 1
        return f"Broadcast to {count} teammates"
    
    def get_pending_count(self, name: str) -> int:
        """获取待处理消息数量"""
        with self._lock:
            return len(self._inboxes.get(name, []))


class CoordinationProtocol:
    """协调协议，定义了 lead 和队友之间的任务协调交互"""
    def __init__(self, bus: MessageBus):
        self.bus = bus                          # 消息总线
        self._task_requests: Dict[str, Dict] = {}    # 任务请求记录
        self._plan_requests: Dict[str, Dict] = {}    # 计划请求记录
        self._lock = threading.Lock()         # 线程安全锁

    def assign_task(self, lead: str, teammate: str, task: Dict, task_id: str = None) -> str:
        """lead 给队友分配任务"""
        import uuid
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]
        task["task_id"] = task_id
        task["status"] = "assigned"
        
        with self._lock:
            self._task_requests[task_id] = {
                "lead": lead,
                "teammate": teammate,
                "task": task,
                "status": "pending"
            }
        
        self.bus.send(
            lead, teammate,
            json.dumps(task, ensure_ascii=False),
            "task_assignment",
            {"task_id": task_id}
        )
        
        return task_id
    
    def report_task_status(self, teammate: str, lead: str, 
                           task_id: str, status: str, result: str = "") -> str:
        with self._lock:
            if task_id in self._task_requests:
                self._task_requests[task_id]["status"] = status
                self._task_requests[task_id]["result"] = result
        
        self.bus.send(
            teammate, lead,
            result,
            "task_status",
            {"task_id": task_id, "status": status}
        )
        
        return f"Task {task_id} status: {status}"
    
    def request_coordination(self, requester: str, target: str, 
                            action: str, params: Dict) -> str:
        import uuid
        coord_id = str(uuid.uuid4())[:8]
        
        self.bus.send(
            requester, target,
            f"Coordination request: {action}",
            "coordination",
            {"coord_id": coord_id, "action": action, "params": params}
        )
        
        return coord_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            return self._task_requests.get(task_id)
    
    def submit_plan(self, teammate: str, lead: str, plan: str) -> str:
        import uuid
        plan_id = str(uuid.uuid4())[:8]
        
        with self._lock:
            self._plan_requests[plan_id] = {
                "from": teammate,
                "plan": plan,
                "status": "pending"
            }
        
        self.bus.send(
            teammate, lead, plan,
            "plan_submission",
            {"plan_id": plan_id}
        )
        
        return plan_id
    
    def approve_plan(self, lead: str, teammate: str, 
                     plan_id: str, approve: bool, feedback: str = "") -> str:
        with self._lock:
            if plan_id in self._plan_requests:
                self._plan_requests[plan_id]["status"] = "approved" if approve else "rejected"
        
        self.bus.send(
            lead, teammate, feedback,
            "plan_approval",
            {"plan_id": plan_id, "approve": approve}
        )
        
        return f"Plan {plan_id} {'approved' if approve else 'rejected'}"
    
    def get_plan_status(self, plan_id: str) -> Optional[Dict]:
        with self._lock:
            return self._plan_requests.get(plan_id)


class TeamState:
    def __init__(self):
        self.members: Dict[str, Dict] = {}
        self._lock = threading.Lock()
    
    def add_member(self, name: str, role: str, capabilities: List[str] = None):
        with self._lock:
            self.members[name] = {
                "name": name,
                "role": role,
                "status": "idle",
                "capabilities": capabilities or [],
                "current_task": None,
                "message_count": 0
            }
    
    def update_status(self, name: str, status: str, task: str = None):
        with self._lock:
            if name in self.members:
                self.members[name]["status"] = status
                if task is not None:
                    self.members[name]["current_task"] = task
    
    def get_member(self, name: str) -> Optional[Dict]:
        with self._lock:
            return self.members.get(name)
    
    def get_all_members(self) -> Dict:
        with self._lock:
            return self.members.copy()
    
    def get_available_members(self) -> List[str]:
        with self._lock:
            return [name for name, info in self.members.items() 
                    if info["status"] == "idle"]
    
    def increment_message_count(self, name: str):
        with self._lock:
            if name in self.members:
                self.members[name]["message_count"] += 1
