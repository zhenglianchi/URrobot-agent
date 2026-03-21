import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
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
    actions: List[Dict] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    priority: str = "normal"
    status: str = "pending"
    assigned_arm: Optional[str] = None
    required_arm: Optional[str] = None
    required_zone: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[str] = None
    skill_name: Optional[str] = None
    blocked_by: List[int] = field(default_factory=list)
    blocks: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        return cls(**data)


class TaskPersistence:
    def __init__(self, tasks_dir: str = None):
        if tasks_dir is None:
            tasks_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tasks")
        self.tasks_dir = Path(tasks_dir)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._next_id = self._get_max_id() + 1
        self._cache: Dict[str, Task] = {}
        self._load_all()
        logger.info(f"[TaskPersistence] Initialized at {self.tasks_dir}")

    def _get_max_id(self) -> int:
        max_id = 0
        for f in self.tasks_dir.glob("task_*.json"):
            try:
                task_id = f.stem.replace("task_", "")
                task_num = int(task_id)
                max_id = max(max_id, task_num)
            except ValueError:
                continue
        return max_id

    def _get_task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"task_{task_id}.json"

    def _load_all(self):
        for f in self.tasks_dir.glob("task_*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                task = Task.from_dict(data)
                self._cache[task.task_id] = task
            except Exception as e:
                logger.error(f"[TaskPersistence] Failed to load {f}: {e}")

    def _save(self, task: Task) -> bool:
        try:
            path = self._get_task_path(task.task_id)
            path.write_text(json.dumps(task.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"[TaskPersistence] Failed to save task {task.task_id}: {e}")
            return False

    def _delete_file(self, task_id: str) -> bool:
        try:
            path = self._get_task_path(task_id)
            if path.exists():
                path.unlink()
            return True
        except Exception as e:
            logger.error(f"[TaskPersistence] Failed to delete task {task_id}: {e}")
            return False

    def create(
        self,
        name: str,
        description: str = "",
        actions: List[Dict] = None,
        dependencies: List[str] = None,
        priority: str = "normal",
        required_arm: str = None,
        required_zone: str = None,
        skill_name: str = None,
        assigned_arm: str = None,
        blocked_by: List[int] = None,
        blocks: List[int] = None,
    ) -> Task:
        with self._lock:
            task_id = str(self._next_id)
            self._next_id += 1

            task = Task(
                task_id=task_id,
                name=name,
                description=description,
                actions=actions or [],
                dependencies=dependencies or [],
                priority=priority,
                status="pending",
                assigned_arm=assigned_arm,
                required_arm=required_arm,
                required_zone=required_zone,
                skill_name=skill_name,
                blocked_by=blocked_by or [],
                blocks=blocks or [],
            )

            self._save(task)
            self._cache[task_id] = task

            if task.blocks:
                for blocked_id in task.blocks:
                    blocked_task = self.get(str(blocked_id))
                    if blocked_task and task_id not in [str(x) for x in blocked_task.blocked_by]:
                        blocked_task.blocked_by.append(int(task_id))
                        self._save(blocked_task)

            logger.info(f"[TaskPersistence] Created task {task_id}: {name}")
            return task

    def get(self, task_id: str) -> Optional[Task]:
        return self._cache.get(task_id)

    def update(
        self,
        task_id: str,
        status: str = None,
        assigned_arm: str = None,
        result: str = None,
        add_blocked_by: List[int] = None,
        add_blocks: List[int] = None,
    ) -> Optional[Task]:
        with self._lock:
            task = self._cache.get(task_id)
            if not task:
                return None

            if status:
                valid_statuses = ["pending", "ready", "running", "completed", "failed", "blocked"]
                if status not in valid_statuses:
                    raise ValueError(f"Invalid status: {status}")
                task.status = status

                if status == "running" and task.started_at is None:
                    task.started_at = time.time()
                elif status == "completed":
                    task.completed_at = time.time()
                    self._clear_dependency(int(task_id))

            if assigned_arm is not None:
                task.assigned_arm = assigned_arm
            if result is not None:
                task.result = result

            if add_blocked_by:
                for bid in add_blocked_by:
                    if bid not in task.blocked_by:
                        task.blocked_by.append(bid)

            if add_blocks:
                for bid in add_blocks:
                    if bid not in task.blocks:
                        task.blocks.append(bid)
                    blocked_task = self.get(str(bid))
                    if blocked_task and int(task_id) not in blocked_task.blocked_by:
                        blocked_task.blocked_by.append(int(task_id))
                        self._save(blocked_task)

            self._save(task)
            logger.info(f"[TaskPersistence] Updated task {task_id}: status={task.status}")
            return task

    def _clear_dependency(self, completed_id: int):
        for task in self._cache.values():
            if completed_id in task.blocked_by:
                task.blocked_by.remove(completed_id)
                self._save(task)

    def delete(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._cache:
                del self._cache[task_id]
                self._delete_file(task_id)
                logger.info(f"[TaskPersistence] Deleted task {task_id}")
                return True
            return False

    def list_all(self, status: str = None) -> List[Task]:
        tasks = list(self._cache.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at)

    def list_pending(self) -> List[Task]:
        return [t for t in self._cache.values() if t.status == "pending"]

    def list_ready(self) -> List[Task]:
        return [t for t in self._cache.values() if t.status == "ready" or (t.status == "pending" and not t.blocked_by)]

    def list_running(self) -> List[Task]:
        return [t for t in self._cache.values() if t.status == "running"]

    def list_completed(self) -> List[Task]:
        return [t for t in self._cache.values() if t.status == "completed"]

    def clear_completed(self) -> int:
        count = 0
        for task in list(self._cache.values()):
            if task.status == "completed":
                self.delete(task.task_id)
                count += 1
        return count

    def clear_all(self) -> int:
        count = len(self._cache)
        for task_id in list(self._cache.keys()):
            self._delete_file(task_id)
        self._cache.clear()
        return count

    def get_summary(self) -> Dict:
        tasks = list(self._cache.values())
        return {
            "total": len(tasks),
            "pending": len([t for t in tasks if t.status == "pending"]),
            "ready": len([t for t in tasks if t.status == "ready"]),
            "running": len([t for t in tasks if t.status == "running"]),
            "completed": len([t for t in tasks if t.status == "completed"]),
            "failed": len([t for t in tasks if t.status == "failed"]),
            "blocked": len([t for t in tasks if t.status == "blocked"]),
        }

    def format_task_list(self, status: str = None) -> str:
        tasks = self.list_all(status)
        if not tasks:
            return "No tasks found."

        lines = []
        status_markers = {
            "pending": "[ ]",
            "ready": "[>]",
            "running": "[*]",
            "completed": "[x]",
            "failed": "[!]",
            "blocked": "[-]",
        }

        for t in tasks:
            marker = status_markers.get(t.status, "[?]")
            blocked_info = f" (blocked by: {t.blocked_by})" if t.blocked_by else ""
            arm_info = f" [{t.assigned_arm}]" if t.assigned_arm else ""
            skill_info = f" (skill: {t.skill_name})" if t.skill_name else ""
            lines.append(f"{marker} #{t.task_id}: {t.name}{arm_info}{skill_info}{blocked_info}")

        return "\n".join(lines)
