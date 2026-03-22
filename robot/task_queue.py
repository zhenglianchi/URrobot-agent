from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import threading
import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger_handler import logger


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"        # 等待中（依赖未满足）
    READY = "ready"            # 就绪（依赖满足，等待分配）
    RUNNING = "running"        # 正在执行
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 执行失败
    BLOCKED = "blocked"        # 被阻塞


class TaskPriority(Enum):
    """任务优先级枚举"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Task:
    """任务数据类，保存一个原子操作任务的所有信息"""
    task_id: str                               # 任务唯一ID
    name: str                                  # 任务名称
    description: str                           # 任务描述
    actions: List[Dict]                        # 动作列表
    dependencies: List[str] = field(default_factory=list)  # 依赖任务ID列表
    priority: TaskPriority = TaskPriority.NORMAL  # 优先级
    status: TaskStatus = TaskStatus.PENDING    # 当前状态
    assigned_arm: Optional[str] = None         # 分配执行的机械臂ID
    required_arm: Optional[str] = None         # 要求特定机械臂
    required_zone: Optional[str] = None       # 要求可达工作区
    created_at: float = field(default_factory=time.time)  # 创建时间戳
    started_at: Optional[float] = None         # 开始时间戳
    completed_at: Optional[float] = None       # 完成时间戳
    result: Optional[str] = None               # 执行结果

    def is_ready(self) -> bool:
        """检查任务是否就绪"""
        return self.status == TaskStatus.READY

    def is_running(self) -> bool:
        """检查任务是否正在执行"""
        return self.status == TaskStatus.RUNNING

    def is_completed(self) -> bool:
        """检查任务是否已完成"""
        return self.status == TaskStatus.COMPLETED

    def to_dict(self) -> Dict:
        """转换为字典用于序列化"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "dependencies": self.dependencies,
            "assigned_arm": self.assigned_arm,
            "required_arm": self.required_arm,
            "required_zone": self.required_zone,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
        }


class TaskQueue:
    """线程安全的任务队列，支持依赖管理和优先级排序

    特性：
    - 支持任务依赖：只有当所有依赖任务完成后，当前任务才变为就绪
    - 优先级排序：高优先级任务先执行
    - 线程安全：使用互斥锁保护并发访问
    """
    def __init__(self):
        self.tasks: Dict[str, Task] = {}           # 所有任务映射
        self.completed_ids: Set[str] = set()        # 已完成任务ID集合
        self._lock = threading.Lock()               # 线程安全锁
        self._task_counter = 0                      # 任务ID计数器
        logger.info("[TaskQueue] Initialized")

    def add_task(
        self,
        name: str,
        description: str,
        actions: List[Dict],
        dependencies: List[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        required_arm: str = None,
        required_zone: str = None,
    ) -> str:
        """添加新任务到队列

        参数:
            name: 任务名称
            description: 任务描述
            actions: 动作列表
            dependencies: 依赖的任务ID列表
            priority: 任务优先级
            required_arm: 要求特定机械臂
            required_zone: 要求可达工作区

        返回:
            新任务ID
        """
        with self._lock:
            self._task_counter += 1
            task_id = f"task_{self._task_counter:03d}"

            task = Task(
                task_id=task_id,
                name=name,
                description=description,
                actions=actions,
                dependencies=dependencies or [],
                priority=priority,
                required_arm=required_arm,
                required_zone=required_zone,
            )

            # 检查依赖是否满足，如果满足直接设为就绪
            if self._check_dependencies_met(task):
                task.status = TaskStatus.READY

            self.tasks[task_id] = task
            logger.info(f"[TaskQueue] Added task: {task_id} - {name}")
            return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.tasks.get(task_id)

    def get_ready_tasks(self) -> List[Task]:
        """获取所有就绪任务，按优先级降序排序"""
        with self._lock:
            ready = []
            for task in self.tasks.values():
                if task.status == TaskStatus.READY:
                    ready.append(task)
            # 高优先级优先
            ready.sort(key=lambda t: t.priority.value, reverse=True)
            return ready

    def get_pending_tasks(self) -> List[Task]:
        """获取所有等待中的任务"""
        with self._lock:
            return [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]

    def get_running_tasks(self) -> List[Task]:
        """获取所有正在执行的任务"""
        with self._lock:
            return [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]

    def start_task(self, task_id: str, arm_id: str) -> bool:
        """标记任务开始执行

        参数:
            task_id: 任务ID
            arm_id: 执行的机械臂ID

        返回:
            是否成功开始
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            if task.status != TaskStatus.READY:
                return False
            task.status = TaskStatus.RUNNING
            task.assigned_arm = arm_id
            task.started_at = time.time()
            logger.info(f"[TaskQueue] Started: {task_id} on {arm_id}")
            return True

    def complete_task(self, task_id: str, result: str = None) -> bool:
        """标记任务完成，更新依赖任务状态

        参数:
            task_id: 任务ID
            result: 结果描述

        返回:
            是否成功完成
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.result = result or "completed"
            self.completed_ids.add(task_id)
            # 更新所有依赖此任务的任务状态
            self._update_dependent_tasks(task_id)
            logger.info(f"[TaskQueue] Completed: {task_id}")
            return True

    def fail_task(self, task_id: str, error: str = None) -> bool:
        """标记任务失败

        参数:
            task_id: 任务ID
            error: 错误信息

        返回:
            是否成功标记
        """
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            task.status = TaskStatus.FAILED
            task.result = error or "failed"
            logger.error(f"[TaskQueue] Failed: {task_id} - {error}")
            return True

    def _check_dependencies_met(self, task: Task) -> bool:
        """检查任务的所有依赖是否都已完成"""
        for dep_id in task.dependencies:
            if dep_id not in self.completed_ids:
                return False
        return True

    def _update_dependent_tasks(self, completed_task_id: str):
        """当一个任务完成后，更新所有依赖它的任务状态

        如果依赖全部满足，则将任务状态改为就绪
        """
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING and completed_task_id in task.dependencies:
                if self._check_dependencies_met(task):
                    task.status = TaskStatus.READY
                    logger.info(f"[TaskQueue] Task {task.task_id} now ready")

    def get_all_status(self) -> Dict:
        """获取各状态任务统计"""
        with self._lock:
            return {
                "total": len(self.tasks),
                "pending": len([t for t in self.tasks.values() if t.status == TaskStatus.PENDING]),
                "ready": len([t for t in self.tasks.values() if t.status == TaskStatus.READY]),
                "running": len([t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]),
                "completed": len([t for t in self.tasks.values() if t.status == TaskStatus.COMPLETED]),
                "failed": len([t for t in self.tasks.values() if t.status == TaskStatus.FAILED]),
            }

    def get_task_summary(self) -> str:
        status = self.get_all_status()
        lines = [
            "## Task Queue Summary",
            f"- Total: {status['total']}",
            f"- Pending: {status['pending']}",
            f"- Ready: {status['ready']}",
            f"- Running: {status['running']}",
            f"- Completed: {status['completed']}",
            f"- Failed: {status['failed']}",
            "",
            "### Ready Tasks:",
        ]
        for task in self.get_ready_tasks():
            lines.append(f"  - {task.task_id}: {task.name} (priority={task.priority.name})")
        lines.append("\n### Running Tasks:")
        for task in self.get_running_tasks():
            lines.append(f"  - {task.task_id}: {task.name} on {task.assigned_arm}")
        return "\n".join(lines)

    def clear_completed(self):
        with self._lock:
            to_remove = [tid for tid, t in self.tasks.items() if t.status == TaskStatus.COMPLETED]
            for tid in to_remove:
                del self.tasks[tid]
            logger.info(f"[TaskQueue] Cleared {len(to_remove)} completed tasks")

    def reset(self):
        with self._lock:
            self.tasks.clear()
            self.completed_ids.clear()
            self._task_counter = 0
            logger.info("[TaskQueue] Reset complete")
