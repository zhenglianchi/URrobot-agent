
from typing import TypedDict, List, Optional, Dict, Any
from enum import Enum


class StepStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ORUState(TypedDict):
    current_step_index: int
    total_steps: int
    steps: List[Dict[str, Any]]
    
    robot_pose: List[float]
    robot_joints: List[float]
    
    oru_old_id: Optional[str]
    oru_new_id: Optional[str]
    oru_picked: bool
    oru_installed: bool
    
    storage_rack_id: str
    assembly_station_id: str
    tool_rack_id: str
    screwdriver_id: str
    
    tool_in_hand: Optional[str]
    screws_tightened: int
    total_screws: int
    
    errors: List[str]
    warnings: List[str]
    
    object_graph: Optional[Any]
    
    execution_log: List[Dict[str, Any]]
    
    is_complete: bool
    is_successful: bool


def create_initial_state(
    oru_old_id,
    oru_new_id,
    storage_rack_id,
    assembly_station_id,
    tool_rack_id,
    screwdriver_id,
    total_screws=4
):
    return ORUState(
        current_step_index=0,
        total_steps=9,
        steps=[
            {"name": "MoveToORUPickPoint", "status": StepStatus.PENDING, "result": None},
            {"name": "PullOutORU", "status": StepStatus.PENDING, "result": None},
            {"name": "MoveToStorageRack", "status": StepStatus.PENDING, "result": None},
            {"name": "PickNewORU", "status": StepStatus.PENDING, "result": None},
            {"name": "MoveToAssemblyPosition", "status": StepStatus.PENDING, "result": None},
            {"name": "InsertORU", "status": StepStatus.PENDING, "result": None},
            {"name": "PickScrewdriver", "status": StepStatus.PENDING, "result": None},
            {"name": "TightenScrews", "status": StepStatus.PENDING, "result": None},
            {"name": "PlaceScrewdriver", "status": StepStatus.PENDING, "result": None},
        ],
        robot_pose=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        robot_joints=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        oru_old_id=oru_old_id,
        oru_new_id=oru_new_id,
        oru_picked=False,
        oru_installed=False,
        storage_rack_id=storage_rack_id,
        assembly_station_id=assembly_station_id,
        tool_rack_id=tool_rack_id,
        screwdriver_id=screwdriver_id,
        tool_in_hand=None,
        screws_tightened=0,
        total_screws=total_screws,
        errors=[],
        warnings=[],
        object_graph=None,
        execution_log=[],
        is_complete=False,
        is_successful=False,
    )

