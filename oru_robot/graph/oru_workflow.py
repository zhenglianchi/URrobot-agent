
from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, END
from .state import ORUState, StepStatus, create_initial_state
from .object_manager import ObjectGraph, ObjectType, ObjectPosition
from utils.logger_handler import logger
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class ORUReplacementWorkflow:
    def __init__(self, object_graph, robot=None):
        self.object_graph = object_graph
        self.robot = robot
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(ORUState)
        
        workflow.add_node("initialize", self._initialize)
        workflow.add_node("execute_step", self._execute_step)
        workflow.add_node("handle_error", self._handle_error)
        workflow.add_node("check_complete", self._check_complete)
        
        workflow.set_entry_point("initialize")
        workflow.add_edge("initialize", "execute_step")
        workflow.add_conditional_edges(
            "execute_step",
            self._should_continue,
            {
                "continue": "execute_step",
                "error": "handle_error",
                "check_complete": "check_complete"
            }
        )
        workflow.add_edge("handle_error", "check_complete")
        workflow.add_edge("check_complete", END)
        
        return workflow.compile()

    def _initialize(self, state):
        logger.info("[Workflow] 初始化ORU更换流程")
        
        state["object_graph"] = self.object_graph
        state["execution_log"].append({
            "step": "initialize",
            "status": "completed",
            "timestamp": None
        })
        
        return state

    def _execute_step(self, state):
        step_index = state["current_step_index"]
        step = state["steps"][step_index]
        
        logger.info(f"[Workflow] 执行步骤 {step_index + 1}/{state['total_steps']}: {step['name']}")
        
        state["steps"][step_index]["status"] = StepStatus.IN_PROGRESS
        
        try:
            result = self._execute_skill(step["name"], state)
            
            state["steps"][step_index]["status"] = StepStatus.COMPLETED
            state["steps"][step_index]["result"] = result
            state["current_step_index"] += 1
            
            state["execution_log"].append({
                "step": step["name"],
                "status": "completed",
                "result": result,
                "timestamp": None
            })
            
            self._update_state_after_step(state, step["name"], result)
            
        except Exception as e:
            logger.error(f"[Workflow] 步骤 {step['name']} 执行失败: {str(e)}", exc_info=True)
            state["steps"][step_index]["status"] = StepStatus.FAILED
            state["errors"].append(f"{step['name']}: {str(e)}")
            
            state["execution_log"].append({
                "step": step["name"],
                "status": "failed",
                "error": str(e),
                "timestamp": None
            })
        
        return state

    def _execute_skill(self, skill_name, state):
        logger.info(f"[Skill] 执行技能: {skill_name}")
        
        params = self._get_skill_params(skill_name, state)
        
        if self.robot:
            result = self._call_robot_skill(skill_name, params)
        else:
            result = self._simulate_skill(skill_name, params)
        
        logger.info(f"[Skill] {skill_name} 执行完成，结果: {result}")
        return result

    def _get_skill_params(self, skill_name, state):
        params = {}
        
        if skill_name == "MoveToORUPickPoint":
            params["oru_id"] = state["oru_old_id"]
        elif skill_name == "MoveToStorageRack":
            params["storage_rack_id"] = state["storage_rack_id"]
        elif skill_name == "PickNewORU":
            params["storage_rack_id"] = state["storage_rack_id"]
            params["oru_id"] = state["oru_new_id"]
        elif skill_name == "MoveToAssemblyPosition":
            params["assembly_station_id"] = state["assembly_station_id"]
        elif skill_name == "PickScrewdriver":
            params["tool_rack_id"] = state["tool_rack_id"]
            params["screwdriver_id"] = state["screwdriver_id"]
        elif skill_name == "TightenScrews":
            params["screw_count"] = state["total_screws"]
        elif skill_name == "PlaceScrewdriver":
            params["tool_rack_id"] = state["tool_rack_id"]
            params["screwdriver_id"] = state["screwdriver_id"]
        
        return params

    def _call_robot_skill(self, skill_name, params):
        logger.warning(f"[Skill] 机器人技能调用尚未实现: {skill_name}")
        return {"success": True, "simulated": True}

    def _simulate_skill(self, skill_name, params):
        logger.info(f"[Skill] 模拟执行: {skill_name} with params: {params}")
        return {"success": True, "simulated": True}

    def _update_state_after_step(self, state, skill_name, result):
        if skill_name == "MoveToORUPickPoint":
            state["oru_picked"] = True
        elif skill_name == "MoveToStorageRack":
            state["oru_picked"] = False
        elif skill_name == "PickNewORU":
            state["oru_picked"] = True
        elif skill_name == "InsertORU":
            state["oru_installed"] = True
            state["oru_picked"] = False
        elif skill_name == "PickScrewdriver":
            state["tool_in_hand"] = "screwdriver"
        elif skill_name == "TightenScrews":
            state["screws_tightened"] = state["total_screws"]
        elif skill_name == "PlaceScrewdriver":
            state["tool_in_hand"] = None

    def _should_continue(self, state):
        if state["errors"]:
            return "error"
        
        if state["current_step_index"] >= state["total_steps"]:
            return "check_complete"
        
        return "continue"

    def _handle_error(self, state):
        logger.error(f"[Workflow] 处理错误: {state['errors']}")
        state["is_complete"] = True
        state["is_successful"] = False
        return state

    def _check_complete(self, state):
        all_completed = all(
            step["status"] == StepStatus.COMPLETED 
            for step in state["steps"]
        )
        
        state["is_complete"] = True
        state["is_successful"] = all_completed and not state["errors"]
        
        if state["is_successful"]:
            logger.info("[Workflow] ORU更换流程成功完成!")
        else:
            logger.warning("[Workflow] ORU更换流程未完全成功")
        
        return state

    def run(self, initial_state=None):
        if initial_state is None:
            initial_state = create_initial_state(
                oru_old_id="oru_001",
                oru_new_id="oru_002",
                storage_rack_id="rack_001",
                assembly_station_id="station_001",
                tool_rack_id="tool_rack_001",
                screwdriver_id="screwdriver_001"
            )
        
        logger.info("[Workflow] 开始执行ORU更换流程")
        final_state = self.graph.invoke(initial_state)
        logger.info("[Workflow] ORU更换流程结束")
        
        return final_state


if __name__ == '__main__':
    object_graph = ObjectGraph()
    
    workflow = ORUReplacementWorkflow(object_graph)
    final_state = workflow.run()
    
    print("\n=== 最终状态 ===")
    print(f"成功: {final_state['is_successful']}")
    print(f"当前步骤: {final_state['current_step_index']}/{final_state['total_steps']}")
    print(f"ORU已安装: {final_state['oru_installed']}")
    print(f"螺丝拧紧: {final_state['screws_tightened']}/{final_state['total_screws']}")
    
    if final_state['errors']:
        print("\n错误:")
        for err in final_state['errors']:
            print(f"  - {err}")

