import json
import os
import sys
import threading
import time
from typing import Dict, List, Optional, Callable, Generator
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger_handler import logger
from robot.team import MessageBus, CoordinationProtocol, TeamState, TeamMessage
from robot.multi_arm_manager import MultiArmManager
from robot.task_queue import TaskQueue
from robot.tools import create_robot_tools, ToolResult, ToolStatus
from robot.skill_loader import get_skill_loader, SkillLoader


class ArmTeammate:
    def __init__(
        self,
        name: str,
        arm_id: str,
        manager: MultiArmManager,
        bus: MessageBus,
        protocol: CoordinationProtocol,
        team_state: TeamState,
        model: str = None,
        api_key: str = None,
        base_url: str = None,
        stream_callback: Callable = None,
        skill_loader: SkillLoader = None,
    ):
        self.name = name
        self.arm_id = arm_id
        self.manager = manager
        self.bus = bus
        self.protocol = protocol
        self.team_state = team_state
        self.model = model or os.environ.get("MODEL_ID", "minimax-m2.5")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        self.stream_callback = stream_callback
        self.skill_loader = skill_loader or get_skill_loader()
        
        self.task_queue = TaskQueue()
        self.tool_registry = create_robot_tools(manager, self.task_queue, arm_id)
        
        self.messages: List[Dict] = []
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._client = None
        self.stream_callback = stream_callback
        self._loaded_skills: Dict[str, str] = {}

        self.team_state.add_member(
            name,
            f"robot_arm_{arm_id}",
            ["move", "grip", "release", "coordinate"]
        )
    
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
                logger.warning(f"[{self.name}] anthropic package not installed")
        return self._client
    
    def get_system_prompt(self) -> str:
        arm_name = "左臂" if "left" in self.arm_id else "右臂"
        other_arm = "右臂" if "left" in self.arm_id else "左臂"
        
        skill_descriptions = self.skill_loader.get_descriptions()

        return f"""你是 {self.name}，一个机械臂队友 ({arm_name})。

你的身份：
- 名称: {self.name}
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

## ⚠️ 任务完成报告（必须执行）
**每个任务完成后，必须调用 report_task_status 工具向 leader 报告：**
```
report_task_status(
    task_id="任务ID",      # 从任务分配消息中获取
    status="completed",    # 或 "failed"
    result="执行结果描述"
)
```
**不报告状态会导致任务无法正确标记完成！**

通信规则：
- 使用工具发送消息给lead或其他队友
- 使用工具检查收件箱新消息
- 报告任务进度
- 需要其他机械臂帮助时请求协调

重要规则：
1. 开工前一定要检查收件箱
2. 分配任务后分解为一步步动作
3. 每个动作完成后报告进度
4. 在另一个机械臂附近工作时必须请求协调避免碰撞
5. 共享 workspace 操作前等待协调批准
6. 每一步操作都要执行，完成一个再进行下一个
7. **所有任务完成后，必须移动回自己的初始home位置待命**
8. **任务完成后必须调用 report_task_status 报告状态**

当你收到任务分配消息：
1. 解析任务细节（注意提取 task_id）
2. **检查是否有匹配的技能**
3. 如有匹配技能，加载并按步骤执行
4. 如无匹配技能，使用默认工具规划动作
5. 执行任务
6. **调用 report_task_status 报告完成状态**
"""

    def start(self, initial_prompt: str = None):
        if self.running:
            return f"{self.name} is already running"
        
        self.running = True
        self.team_state.update_status(self.name, "working")
        
        self.thread = threading.Thread(
            target=self._teammate_loop,
            args=(initial_prompt,),
            daemon=True
        )
        self.thread.start()
        
        logger.info(f"[{self.name}] Started")
        return f"{self.name} started"
    
    def stop(self):
        self.running = False
        self.team_state.update_status(self.name, "shutdown")
        logger.info(f"[{self.name}] Stopped")
    
    def _teammate_loop(self, initial_prompt: str = None):
        if not self.client:
            logger.error(f"[{self.name}] No API client available")
            return
        
        if initial_prompt:
            self.messages.append({"role": "user", "content": initial_prompt})
        
        while self.running:
            try:
                inbox = self.bus.read_inbox(self.name)
                for msg in inbox:
                    self._handle_message(msg)
                
                if not self.messages:
                    time.sleep(0.5)
                    continue
                
                self.team_state.update_status(self.name, "working")

                if self.stream_callback:
                    # 流式输出思考过程
                    full_content = []
                    with self.client.messages.stream(
                        model=self.model,
                        max_tokens=4096,
                        system=self.get_system_prompt(),
                        messages=self.messages,
                        tools=self._get_tools(),
                    ) as stream:
                        self.stream_callback(f"[{self.name}] thinking", "[thinking]")
                        for event in stream:
                            if event.type == "content_block_delta":
                                if hasattr(event.delta, "type") and event.delta.type == "text_delta":
                                    text = event.delta.text
                                    self.stream_callback(f"[{self.name}] thinking", text)
                        self.stream_callback(f"[{self.name}] thinking", "[/thinking]")

                        response = stream.get_final_message()
                else:
                    # 非流式输出
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=4096,
                        system=self.get_system_prompt(),
                        messages=self.messages,
                        tools=self._get_tools(),
                    )

                self.messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason == "tool_use":
                    if self.stream_callback:
                        for block in response.content:
                            if block.type == "tool_use":
                                msg = f"[{self.name}] tool_call: {block.name}"
                                self.stream_callback(f"[{self.name}] tool_call", f"[tool_call]{msg}[/tool_call]")
                    self._handle_tool_calls(response.content)
                elif response.stop_reason == "end_turn":
                    self.team_state.update_status(self.name, "idle")
                    self.messages = []
                
            except Exception as e:
                logger.error(f"[{self.name}] Error: {e}")
                time.sleep(1)
        
        self.team_state.update_status(self.name, "shutdown")
    
    def _handle_message(self, msg: TeamMessage):
        content = f"Message from {msg.sender} ({msg.msg_type}): {msg.content}"
        self.messages.append({"role": "user", "content": content})
        self.team_state.increment_message_count(self.name)
        
        if msg.msg_type == "task_assignment":
            extra = msg.extra
            task_id = extra.get("task_id")
            self.team_state.update_status(self.name, "working", task_id)
    
    def _handle_tool_calls(self, content: List):
        results = []
        for block in content:
            if block.type == "tool_use":
                output = self._execute_tool(block.name, block.input)
                logger.info(f"[{self.name}] Tool {block.name}: {str(output)[:100]}")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output.to_string() if isinstance(output, ToolResult) else str(output),
                })
        self.messages.append({"role": "user", "content": results})
    
    def _execute_tool(self, name: str, params: Dict) -> ToolResult:
        if name == "send_message":
            return self._tool_send_message(params)
        elif name == "read_inbox":
            return self._tool_read_inbox()
        elif name == "report_task_status":
            return self._tool_report_status(params)
        elif name == "request_coordination":
            return self._tool_request_coordination(params)
        elif name == "get_my_state":
            return self._tool_get_state()
        elif name == "load_skill":
            return self._tool_load_skill(params)
        else:
            return self.tool_registry.execute(name, params)
    
    def _tool_load_skill(self, params: Dict) -> ToolResult:
        skill_name = params.get("name", "")
        if not skill_name:
            return ToolResult(ToolStatus.FAILED, "Skill name required")
        
        skill_content = self.skill_loader.get_skill_content(skill_name)
        if skill_content.startswith("Error:"):
            return ToolResult(ToolStatus.FAILED, skill_content)
        
        self._loaded_skills[skill_name] = skill_content
        logger.info(f"[{self.name}] Loaded skill: {skill_name}")
        
        return ToolResult(ToolStatus.SUCCESS, f"Skill '{skill_name}' loaded", {"content": skill_content})
    
    def _tool_send_message(self, params: Dict) -> ToolResult:
        to = params.get("to", "lead")
        content = params.get("content", "")
        msg_type = params.get("msg_type", "message")
        
        self.bus.send(self.name, to, content, msg_type)
        return ToolResult(ToolStatus.SUCCESS, f"Message sent to {to}")
    
    def _tool_read_inbox(self) -> ToolResult:
        inbox = self.bus.read_inbox(self.name)
        messages = [msg.to_dict() for msg in inbox]
        return ToolResult(ToolStatus.SUCCESS, "Inbox read", {"messages": messages})
    
    def _tool_report_status(self, params: Dict) -> ToolResult:
        task_id = params.get("task_id", "")
        status = params.get("status", "unknown")
        result = params.get("result", "")
        
        self.protocol.report_task_status(self.name, "lead", task_id, status, result)
        self.team_state.update_status(self.name, "idle" if status == "completed" else "working")
        
        return ToolResult(ToolStatus.SUCCESS, f"Task {task_id} status: {status}")
    
    def _tool_request_coordination(self, params: Dict) -> ToolResult:
        target = params.get("target", "")
        action = params.get("action", "")
        coord_params = params.get("params", {})
        
        coord_id = self.protocol.request_coordination(self.name, target, action, coord_params)
        return ToolResult(ToolStatus.SUCCESS, f"Coordination request {coord_id} sent to {target}")
    
    def _tool_get_state(self) -> ToolResult:
        arm = self.manager.get_arm(self.arm_id)
        state = arm.state.to_dict()
        return ToolResult(ToolStatus.SUCCESS, "Arm state", state)
    
    def _get_tools(self) -> List[Dict]:
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
                "name": "send_message",
                "description": "Send a message to another teammate or lead",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient name"},
                        "content": {"type": "string", "description": "Message content"},
                        "msg_type": {"type": "string", "enum": ["message", "coordination"]}
                    },
                    "required": ["to", "content"]
                }
            },
            {
                "name": "read_inbox",
                "description": "Read and clear your inbox messages",
                "input_schema": {"type": "object", "properties": {}}
            },
            {
                "name": "report_task_status",
                "description": "Report status of an assigned task",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["in_progress", "completed", "failed"]},
                        "result": {"type": "string"}
                    },
                    "required": ["task_id", "status"]
                }
            },
            {
                "name": "request_coordination",
                "description": "Request coordination with another arm for collision avoidance",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "Target arm name"},
                        "action": {"type": "string", "description": "Action requiring coordination"},
                        "params": {"type": "object", "description": "Additional parameters"}
                    },
                    "required": ["target", "action"]
                }
            },
            {
                "name": "get_my_state",
                "description": "Get current state of this arm",
                "input_schema": {"type": "object", "properties": {}}
            }
        ]
        
        return tools + team_tools


class TeammateManager:
    def __init__(
        self,
        manager: MultiArmManager,
        bus: MessageBus,
        protocol: CoordinationProtocol,
        team_state: TeamState,
        model: str = None,
        api_key: str = None,
        base_url: str = None,
        stream_callback: Callable = None,
        skill_loader: SkillLoader = None,
    ):
        self.manager = manager
        self.bus = bus
        self.protocol = protocol
        self.team_state = team_state
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.stream_callback = stream_callback
        self.skill_loader = skill_loader or get_skill_loader()

        self.teammates: Dict[str, ArmTeammate] = {}
    
    def spawn_arm_teammate(
        self,
        name: str,
        arm_id: str,
        initial_prompt: str = None,
        stream_callback: Callable = None,
    ) -> str:
        if name in self.teammates:
            teammate = self.teammates[name]
            if teammate.running:
                return f"Error: {name} is already running"
        
        teammate = ArmTeammate(
            name=name,
            arm_id=arm_id,
            manager=self.manager,
            bus=self.bus,
            protocol=self.protocol,
            team_state=self.team_state,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            stream_callback=stream_callback or self.stream_callback,
            skill_loader=self.skill_loader,
        )
        
        self.teammates[name] = teammate
        teammate.start(initial_prompt)
        
        return f"Spawned {name} (arm: {arm_id})"
    
    def stop_teammate(self, name: str) -> str:
        if name not in self.teammates:
            return f"Error: {name} not found"
        
        self.teammates[name].stop()
        return f"Stopped {name}"
    
    def stop_all(self):
        for name, teammate in self.teammates.items():
            teammate.stop()
    
    def get_teammate(self, name: str) -> Optional[ArmTeammate]:
        return self.teammates.get(name)
    
    def list_teammates(self) -> str:
        members = self.team_state.get_all_members()
        if not members:
            return "No teammates"
        
        lines = ["Team Members:"]
        for name, info in members.items():
            lines.append(f"  {name} ({info['role']}): {info['status']}")
            if info.get('current_task'):
                lines.append(f"    Task: {info['current_task']}")
        
        return "\n".join(lines)
    
    def get_team_status(self) -> Dict:
        return {
            "members": self.team_state.get_all_members(),
            "pending_messages": {
                name: self.bus.get_pending_count(name)
                for name in self.teammates.keys()
            }
        }
