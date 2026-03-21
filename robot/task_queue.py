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
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Task:
    task_id: str
    name: str
    description: str
    actions: List[Dict]
    dependencies: List[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    assigned_arm: Optional[str] = None
    required_arm: Optional[str] = None
    required_zone: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[str] = None

    def is_ready(self) -> bool:
        return self.status == TaskStatus.READY

    def is_running(self) -> bool:
        return self.status == TaskStatus.RUNNING

    def is_completed(self) -> bool:
        return self.status == TaskStatus.COMPLETED

    def to_dict(self) -> Dict:
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
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.completed_ids: Set[str] = set()
        self._lock = threading.Lock()
        self._task_counter = 0
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
            
            if self._check_dependencies_met(task):
                task.status = TaskStatus.READY
            
            self.tasks[task_id] = task
            logger.info(f"[TaskQueue] Added task: {task_id} - {name}")
            return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def get_ready_tasks(self) -> List[Task]:
        with self._lock:
            ready = []
            for task in self.tasks.values():
                if task.status == TaskStatus.READY:
                    ready.append(task)
            ready.sort(key=lambda t: t.priority.value, reverse=True)
            return ready

    def get_pending_tasks(self) -> List[Task]:
        with self._lock:
            return [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]

    def get_running_tasks(self) -> List[Task]:
        with self._lock:
            return [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]

    def start_task(self, task_id: str, arm_id: str) -> bool:
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
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.result = result or "completed"
            self.completed_ids.add(task_id)
            self._update_dependent_tasks(task_id)
            logger.info(f"[TaskQueue] Completed: {task_id}")
            return True

    def fail_task(self, task_id: str, error: str = None) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            task.status = TaskStatus.FAILED
            task.result = error or "failed"
            logger.error(f"[TaskQueue] Failed: {task_id} - {error}")
            return True

    def _check_dependencies_met(self, task: Task) -> bool:
        for dep_id in task.dependencies:
            if dep_id not in self.completed_ids:
                return False
        return True

    def _update_dependent_tasks(self, completed_task_id: str):
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING and completed_task_id in task.dependencies:
                if self._check_dependencies_met(task):
                    task.status = TaskStatus.READY
                    logger.info(f"[TaskQueue] Task {task.task_id} now ready")

    def get_all_status(self) -> Dict:
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
