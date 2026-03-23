import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger_handler import logger


def get_current_time_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def timestamp_to_str(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def str_to_timestamp(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()
    except ValueError:
        return None


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
    description: str = ""
    priority: str = "normal"
    status: str = "pending"
    assigned_arm: Optional[str] = None
    created_at: str = field(default_factory=get_current_time_str)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    skill_name: Optional[str] = None
    blocked_by: List[int] = field(default_factory=list)
    blocks: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "assigned_arm": self.assigned_arm,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "skill_name": self.skill_name,
            "blocked_by": self.blocked_by,
            "blocks": self.blocks,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        created_at = data.get("created_at")
        if created_at is None:
            created_at = get_current_time_str()
        elif isinstance(created_at, (int, float)):
            created_at = timestamp_to_str(created_at)
        
        started_at = data.get("started_at")
        if isinstance(started_at, (int, float)):
            started_at = timestamp_to_str(started_at)
        
        completed_at = data.get("completed_at")
        if isinstance(completed_at, (int, float)):
            completed_at = timestamp_to_str(completed_at)
        
        return cls(
            task_id=data.get("task_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            priority=data.get("priority", "normal"),
            status=data.get("status", "pending"),
            assigned_arm=data.get("assigned_arm"),
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            result=data.get("result"),
            skill_name=data.get("skill_name"),
            blocked_by=data.get("blocked_by", []),
            blocks=data.get("blocks", []),
        )


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
        priority: str = "normal",
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
                priority=priority,
                status="pending",
                assigned_arm=assigned_arm,
                skill_name=skill_name,
                blocked_by=blocked_by or [],
                blocks=blocks or [],
            )

            self._save(task)
            self._cache[task_id] = task

            for blocker_id in task.blocked_by:
                blocker_task = self.get(str(blocker_id))
                if blocker_task:
                    if int(task_id) not in blocker_task.blocks:
                        blocker_task.blocks.append(int(task_id))
                        self._save(blocker_task)

            for blocked_id in task.blocks:
                blocked_task = self.get(str(blocked_id))
                if blocked_task:
                    if int(task_id) not in blocked_task.blocked_by:
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
                    task.started_at = get_current_time_str()
                elif status == "completed":
                    task.completed_at = get_current_time_str()
                    self._clear_dependency(int(task_id))

            if assigned_arm is not None:
                task.assigned_arm = assigned_arm
            if result is not None:
                task.result = result

            if add_blocked_by:
                for bid in add_blocked_by:
                    if bid not in task.blocked_by:
                        task.blocked_by.append(bid)
                        blocker_task = self.get(str(bid))
                        if blocker_task and int(task_id) not in blocker_task.blocks:
                            blocker_task.blocks.append(int(task_id))
                            self._save(blocker_task)

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
        completed_task = self._cache.get(str(completed_id))
        for task in self._cache.values():
            if completed_id in task.blocked_by:
                task.blocked_by.remove(completed_id)
                self._save(task)
            if completed_task and int(task.task_id) in completed_task.blocks:
                completed_task.blocks.remove(int(task.task_id))
        if completed_task:
            self._save(completed_task)

    def delete(self, task_id: str) -> bool:
        with self._lock:
            if task_id not in self._cache:
                return False
            
            task = self._cache[task_id]
            
            for blocker_id in task.blocked_by:
                blocker_task = self.get(str(blocker_id))
                if blocker_task and int(task_id) in blocker_task.blocks:
                    blocker_task.blocks.remove(int(task_id))
                    self._save(blocker_task)
            
            for blocked_id in task.blocks:
                blocked_task = self.get(str(blocked_id))
                if blocked_task and int(task_id) in blocked_task.blocked_by:
                    blocked_task.blocked_by.remove(int(task_id))
                    self._save(blocked_task)
            
            del self._cache[task_id]
            self._delete_file(task_id)
            logger.info(f"[TaskPersistence] Deleted task {task_id}")
            return True

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
