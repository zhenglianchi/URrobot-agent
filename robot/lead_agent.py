import json
import os
import sys
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
from robot.teammate import TeammateManager, ArmTeammate
from robot.tools import ToolResult, ToolStatus
from robot.skill_loader import get_skill_loader, SkillLoader
from robot.task_persistence import TaskPersistence, Task


class LeadToolRegistry:
    """Lead Agent 工具注册表，集中管理所有工具定义"""
    
    _tools: Dict[str, Dict] = {}
    _initialized = False
    
    @classmethod
    def _init_tools(cls):
        if cls._initialized:
            return
        
        cls._tools = {
            "spawn_teammate": {
                "description": "生成一个机械臂队友智能体。分配任务前必须先调用此工具创建队友。单臂任务生成一个，双臂协作生成两个。**只能生成 left_arm 和 right_arm 两个队友**。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "队友名称 (必须是 left_arm 或 right_arm)"},
                        "arm_id": {"type": "string", "enum": ["arm_left", "arm_right"], "description": "要控制的机械臂ID"},
                        "prompt": {"type": "string", "description": "给队友的初始指令"}
                    },
                    "required": ["name", "arm_id"]
                }
            },
            "assign_task": {
                "description": "给已生成的队友分配一个任务。**必须包含 task_id 字段**，用于关联持久化任务。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "teammate": {"type": "string", "description": "要分配任务的队友名称"},
                        "task": {"type": "object", "description": "任务详情: {task_id, skill, action, params}"}
                    },
                    "required": ["teammate", "task"]
                }
            },
            "broadcast": {
                "description": "给所有已生成的队友发送广播消息",
                "input_schema": {
                    "type": "object",
                    "properties": {"content": {"type": "string", "description": "消息内容"}},
                    "required": ["content"]
                }
            },
            "send_message": {
                "description": "给指定的队友发送消息",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "接收消息的队友名称"},
                        "content": {"type": "string", "description": "消息内容"},
                        "msg_type": {"type": "string", "enum": ["message", "coordination"]}
                    },
                    "required": ["to", "content"]
                }
            },
            "read_inbox": {
                "description": "读取队友发来的消息（任务更新、协调请求等）",
                "input_schema": {"type": "object", "properties": {}}
            },
            "list_teammates": {
                "description": "列出所有已生成队友和它们的当前状态",
                "input_schema": {"type": "object", "properties": {}}
            },
            "get_scene_state": {
                "description": "获取完整工作单元状态：机械臂位置、物体位置、夹爪状态",
                "input_schema": {"type": "object", "properties": {}}
            },
            "get_task_status": {
                "description": "通过task_id检查已分配任务的状态",
                "input_schema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string", "description": "要检查的任务ID"}},
                    "required": ["task_id"]
                }
            },
            "shutdown_teammate": {
                "description": "任务完成后关闭指定队友",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "要关闭的队友名称"}},
                    "required": ["name"]
                }
            },
            "shutdown_all": {
                "description": "关闭所有队友",
                "input_schema": {"type": "object", "properties": {}}
            },
            "create_task": {
                "description": "创建持久化任务。任务会保存到文件，重启后仍可恢复。**每个原子操作创建一个任务**。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "任务名称（如：抓取螺丝刀、拧松螺丝）"},
                        "description": {"type": "string", "description": "任务描述"},
                        "skill_name": {"type": "string", "description": "关联的技能名称（如：pick-screwdriver, loosen-screw）"},
                        "assigned_arm": {"type": "string", "enum": ["left_arm", "right_arm"], "description": "分配给哪个机械臂执行"},
                        "blocked_by": {"type": "array", "items": {"type": "integer"}, "description": "前置任务ID列表（此任务必须等待这些任务完成）"},
                        "blocks": {"type": "array", "items": {"type": "integer"}, "description": "后置任务ID列表（此任务完成后这些任务才能开始）"}
                    },
                    "required": ["name"]
                }
            },
            "update_task": {
                "description": "更新任务状态。任务完成时调用此工具标记完成。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "任务ID"},
                        "status": {"type": "string", "enum": ["pending", "ready", "running", "completed", "failed", "blocked"], "description": "新状态"},
                        "result": {"type": "string", "description": "任务结果描述"}
                    },
                    "required": ["task_id"]
                }
            },
            "list_tasks": {
                "description": "列出所有持久化任务",
                "input_schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string", "description": "按状态筛选（可选）"}}
                }
            },
            "get_task": {
                "description": "获取指定任务的详情",
                "input_schema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string", "description": "任务ID"}},
                    "required": ["task_id"]
                }
            },
            "load_skill": {
                "description": "加载指定技能的详细执行步骤。了解技能的具体操作流程。",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "技能名称，如 pick-old-oru, tighten-screw 等"}},
                    "required": ["name"]
                }
            }
        }
        cls._initialized = True
    
    @classmethod
    def register(cls, name: str, description: str, input_schema: Dict):
        """注册新工具"""
        cls._init_tools()
        cls._tools[name] = {"description": description, "input_schema": input_schema}
    
    @classmethod
    def unregister(cls, name: str):
        """注销工具"""
        cls._init_tools()
        cls._tools.pop(name, None)
    
    @classmethod
    def get_tool(cls, name: str) -> Optional[Dict]:
        """获取单个工具定义"""
        cls._init_tools()
        tool = cls._tools.get(name)
        if tool:
            return {"name": name, **tool}
        return None
    
    @classmethod
    def get_all_tools(cls) -> List[Dict]:
        """获取所有工具定义（用于 API 调用）"""
        cls._init_tools()
        return [{"name": name, **tool} for name, tool in cls._tools.items()]
    
    @classmethod
    def get_tools_description(cls) -> str:
        """获取工具描述列表（用于系统提示词）"""
        cls._init_tools()
        lines = []
        for name, tool in cls._tools.items():
            lines.append(f"  - {name}: {tool['description'].split('。')[0]}")
        return "\n".join(lines)


def build_system_prompt(skill_loader: SkillLoader) -> str:
    skills_desc = skill_loader.get_descriptions()
    tools_desc = LeadToolRegistry.get_tools_description()
    
    return f"""你是双臂机器人系统的Lead智能体，负责**规划任务链**并协调双臂协作执行。

## 核心职责
1. **任务分解**：将用户目标分解为一系列原子操作，每个操作对应一个技能
2. **任务持久化**：使用 `create_task` 为每个原子操作创建独立任务
3. **依赖管理**：设置任务间的 `blocked_by` 和 `blocks` 双向依赖关系
4. **协调执行**：按依赖顺序分配任务给机械臂，等待完成后再分配下一个

## 固定团队
- **left_arm**: 左侧UR5机械臂 (arm_id: arm_left)
- **right_arm**: 右侧UR5机械臂 (arm_id: arm_right)

## 可用技能
{skills_desc}

使用 `load_skill` 工具可获取技能的详细执行步骤。

## 可用工具
{tools_desc}

## ⚠️ 关键状态约束（必须遵守）

### 物体状态依赖
| 操作 | 前置状态 | 违反后果 |
|-----|---------|---------|
| loosen-screw | 机械臂必须持有 screwdriver | 无法拧松，任务失败 |
| pick-old-oru | 机械臂夹爪必须打开 | 无法抓取，任务失败 |
| pull-out-oru | 螺丝必须已拧松（oru_old 状态为 "loose"），机械臂持有 oru_old | 无法拔出，任务卡死 |
| insert-oru | 机械臂必须持有 oru_new | 无法插入，任务失败 |
| tighten-screw | 机械臂必须持有 screwdriver | 无法拧紧，任务失败 |

### 双臂协作约束
- **同一物体只能被一个机械臂持有**：如果 left_arm 持有 oru_old，right_arm 不能再抓取它
- **夹爪状态**：抓取前夹爪必须打开，抓取后夹爪必须闭合
- **位置冲突**：两个机械臂不能同时操作同一位置的物体

### 任务阻塞规则
- `blocked_by`: 当前任务依赖的前置任务列表（必须等这些任务完成）
- `blocks`: 当前任务阻塞的后继任务列表（当前任务完成后这些任务才能开始）
- **双向同步**：如果任务A blocked_by 任务B，则任务B blocks 任务A（系统自动维护）

## 任务规划流程

### Step 1: 分析目标 → 规划任务链
根据用户目标，分析需要哪些技能，确定执行顺序和依赖关系：
- 识别前置依赖：哪些操作必须在其他操作之前完成？
- 识别并行机会：哪些操作可以同时由不同机械臂执行？
- 设置阻塞关系：使用 `blocked_by` 标记依赖

### Step 2: 创建任务
```python
create_task(
    name="任务名称",
    skill_name="技能名称",
    assigned_arm="left_arm",  # 或 "right_arm"
    blocked_by=[1, 2]  # 依赖的任务ID列表
)
```

### Step 3: 生成队友
```python
spawn_teammate(name="left_arm", arm_id="arm_left")
spawn_teammate(name="right_arm", arm_id="arm_right")
```

### Step 4: 执行任务
```python
assign_task(teammate="left_arm", task={{"skill": "技能名", "action": "动作描述", "task_id": "1"}})
read_inbox  # 等待结果，会收到 task_status 类型的消息
# 收到状态报告后，自动更新持久化任务
update_task(task_id="1", status="completed")  # 更新状态
```

## 处理队友状态报告
当 `read_inbox` 收到 `task_status` 类型消息时：
```json
{{"sender": "left_arm", "msg_type": "task_status", "content": "执行结果", "extra": {{"task_id": "1", "status": "completed"}}}}
```
**必须调用 `update_task` 更新持久化任务状态！**

## 执行原则
1. **先规划后执行**：先用 `create_task` 创建所有任务，再开始执行
2. **检查状态**：执行前用 `get_scene_state` 确认前置条件满足
3. **等待完成**：每次 `assign_task` 后必须 `read_inbox` 等待结果
4. **更新状态**：收到队友状态报告后立即 `update_task` 更新状态
5. **处理错误**：如果任务失败，分析原因并调整计划

## 常见错误及处理
| 错误 | 原因 | 处理方法 |
|-----|------|---------|
| "ORU状态不是loose" | 螺丝未拧松就尝试抓取 | 先执行 loosen-screw |
| "机械臂未持有工具" | 未抓取工具就执行操作 | 先执行对应的 pick 技能 |
| "夹爪已闭合" | 抓取前夹爪未打开 | 检查机械臂状态 |
| "位置冲突" | 两臂同时操作同一区域 | 调整任务顺序，避免并行 |
"""


LEAD_SYSTEM_PROMPT = build_system_prompt(get_skill_loader())


class LeadAgent:
    """主协调智能体（Lead Agent），负责任务规划和多机械臂协调

    核心职责：
    1. 将用户目标分解为细粒度任务链
    2. 创建持久化任务，设置依赖关系
    3. 生成机械臂队友智能体
    4. 按依赖顺序分配任务给队友
    5. 协调双臂协作

    架构：Lead Agent -> 多个 ArmTeammate -> 控制机械臂
    """
    def __init__(
        self,
        config_path: Optional[str] = None,
        model: Optional[str] = None,
        use_simulator: bool = None,
        api_key: Optional[str] = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
        tasks_dir: Optional[str] = None,
        skills_dir: Optional[str] = None,
    ):
        """
        参数:
            config_path: 机械臂配置文件路径
            model: Claude 模型名称
            use_simulator: 是否仿真模式
            api_key: Anthropic API 密钥
            stream_callback: 流式输出回调
            tasks_dir: 任务持久化目录
            skills_dir: 技能定义目录
        """
        self.config_path = config_path
        self.model = model or os.environ.get("MODEL_ID", "minimax-m2.5")
        self.use_simulator = use_simulator if use_simulator is not None else os.environ.get("USE_SIMULATOR", "true").lower() == "true"
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = os.environ.get("ANTHROPIC_BASE_URL")
        self.stream_callback = stream_callback

        # 初始化多机械臂管理器
        self.manager = MultiArmManager(config_path, use_simulator=self.use_simulator)
        # 初始化消息总线
        self.bus = MessageBus()
        # 初始化协调协议
        self.protocol = CoordinationProtocol(self.bus)
        # 初始化团队状态
        self.team_state = TeamState()

        # 技能加载器
        self.skill_loader = get_skill_loader(skills_dir)
        # 任务持久化
        self.task_persistence = TaskPersistence(tasks_dir)

        # 添加自己作为协调成员
        self.team_state.add_member("lead", "coordinator", ["spawn", "assign", "coordinate", "monitor"])

        # 初始化队友管理器（管理机械臂队友智能体）
        self.teammate_manager = TeammateManager(
            manager=self.manager,
            bus=self.bus,
            protocol=self.protocol,
            team_state=self.team_state,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            stream_callback=self.stream_callback,
            skill_loader=self.skill_loader,
        )

        self.messages: List[Dict] = []           # 对话消息历史
        self.max_iterations = 100                 # 最大工具调用迭代次数
        self._client = None                      # 延迟初始化 Anthropic 客户端

        logger.info(f"[LeadAgent] Initialized with model: {self.model}")
        logger.info(f"[LeadAgent] Skills loaded: {', '.join(self.skill_loader.list_skills())}")
        logger.info(f"[LeadAgent] Tasks directory: {self.task_persistence.tasks_dir}")

    @property
    def client(self):
        """懒加载获取 Anthropic API 客户端"""
        if self._client is None and self.api_key:
            try:
                import anthropic
                client_kwargs = {"api_key": self.api_key}
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                self._client = anthropic.Anthropic(**client_kwargs)
            except ImportError:
                logger.warning("[LeadAgent] anthropic package not installed")
        return self._client

    def _emit(self, event_type: str, content: str):
        """发送事件到流回调并记录日志"""
        if self.stream_callback:
            self.stream_callback(event_type, content)
        # 只记录非thinking事件，避免日志爆炸
        if event_type != "thinking":
            logger.info(f"[LeadAgent][{event_type}] {content[:200]}...")

    def chat(self, user_message: str) -> str:
        """非流式对话入口"""
        self.messages.append({"role": "user", "content": user_message})

        if not self.client:
            return self._handle_offline(user_message)

        try:
            return self._run_agent_loop()
        except Exception as e:
            logger.error(f"[LeadAgent] Error: {e}")
            return f"Error: {str(e)}"

    def chat_stream(self, user_message: str) -> Generator[str, None, None]:
        """流式对话入口，生成器方式输出思考过程和结果"""
        self.messages.append({"role": "user", "content": user_message})

        if not self.client:
            yield self._handle_offline(user_message)
            return

        messages = self._build_messages()
        tools = self._get_tools()

        for iteration in range(self.max_iterations):
            self._emit("iteration", f"Starting iteration {iteration + 1}")

            try:
                with self.client.messages.stream(
                    model=self.model,
                    max_tokens=4096,
                    system=LEAD_SYSTEM_PROMPT,
                    messages=messages,
                    tools=tools,
                ) as stream:
                    # 流式输出thinking，只包裹一次标签
                    yield "[thinking]"
                    for event in stream:
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "type") and event.delta.type == "text_delta":
                                text = event.delta.text
                                # 不在_emit中输出thinking，避免重复，因为yield已经输出了
                                yield text
                    yield "[/thinking]"

                    final_message = stream.get_final_message()
                    stop_reason = final_message.stop_reason
                    assistant_content = final_message.content

                    messages.append({"role": "assistant", "content": assistant_content})

                    if stop_reason == "end_turn":
                        final_text = self._extract_text(assistant_content)
                        yield f"[response]{final_text}[/response]"
                        return

                    if stop_reason == "tool_use":
                        tool_results = []
                        for block in assistant_content:
                            if block.type == "tool_use":
                                self._emit("tool_call", f"{block.name}({json.dumps(block.input, ensure_ascii=False)})")
                                yield f"[tool_call]{block.name}({json.dumps(block.input, ensure_ascii=False)})[/tool_call]"

                                result = self._execute_tool(block.name, block.input)

                                self._emit("tool_result", f"{result.status.value}: {result.message}")
                                yield f"[tool_result]{result.status.value}: {result.message}[/tool_result]"

                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result.to_string(),
                                })
                        
                        messages.append({"role": "user", "content": tool_results})
                        continue
                    
                    yield f"[error]Unexpected stop condition: {stop_reason}[/error]"
                    return
                    
            except Exception as e:
                error_msg = f"Error in iteration {iteration + 1}: {str(e)}"
                self._emit("error", error_msg)
                yield f"[error]{error_msg}[/error]"
                return
        
        yield "[error]Max iterations reached without completion.[/error]"
    
    def _run_agent_loop(self) -> str:
        messages = self._build_messages()
        tools = self._get_tools()
        
        for iteration in range(self.max_iterations):
            self._emit("iteration", f"Starting iteration {iteration + 1}")
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=LEAD_SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
            )
            
            stop_reason = response.stop_reason
            assistant_content = response.content
            
            messages.append({"role": "assistant", "content": assistant_content})
            
            if stop_reason == "end_turn":
                final_text = self._extract_text(assistant_content)
                return final_text
            
            if stop_reason == "tool_use":
                tool_results = []
                for block in assistant_content:
                    if block.type == "tool_use":
                        self._emit("tool_call", f"{block.name}({json.dumps(block.input, ensure_ascii=False)})")
                        result = self._execute_tool(block.name, block.input)
                        self._emit("tool_result", f"{result.status.value}: {result.message}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result.to_string(),
                        })
                
                messages.append({"role": "user", "content": tool_results})
                continue
            
            return "Unexpected stop condition."
        
        return "Max iterations reached without completion."

    def _build_messages(self) -> List[Dict]:
        """构建发送给 Claude 的消息列表

        读取队友发来的新消息，放入 inbox 标签追加到对话
        """
        inbox = self.bus.read_inbox("lead")
        messages = list(self.messages)

        if inbox:
            inbox_content = "\n".join([
                f"From {msg.sender}: {msg.content}"
                for msg in inbox
            ])
            messages.append({
                "role": "user",
                "content": f"<inbox>\n{inbox_content}\n</inbox>"
            })

        return messages

    def _execute_tool(self, name: str, params: Dict) -> ToolResult:
        """分发工具执行到对应的处理函数"""
        logger.info(f"[LeadAgent] Tool call: {name}({params})")

        if name == "spawn_teammate":
            return self._tool_spawn_teammate(params)
        elif name == "assign_task":
            return self._tool_assign_task(params)
        elif name == "broadcast":
            return self._tool_broadcast(params)
        elif name == "send_message":
            return self._tool_send_message(params)
        elif name == "read_inbox":
            return self._tool_read_inbox()
        elif name == "list_teammates":
            return self._tool_list_teammates()
        elif name == "get_scene_state":
            return self._tool_get_scene_state()
        elif name == "get_task_status":
            return self._tool_get_task_status(params)
        elif name == "shutdown_teammate":
            return self._tool_shutdown_teammate(params)
        elif name == "shutdown_all":
            return self._tool_shutdown_all()
        elif name == "create_task":
            return self._tool_create_task(params)
        elif name == "update_task":
            return self._tool_update_task(params)
        elif name == "list_tasks":
            return self._tool_list_tasks(params)
        elif name == "get_task":
            return self._tool_get_task(params)
        elif name == "load_skill":
            return self._tool_load_skill(params)
        else:
            return ToolResult(ToolStatus.ERROR, f"Unknown tool: {name}")

    def _tool_spawn_teammate(self, params: Dict) -> ToolResult:
        """工具：生成一个机械臂队友智能体"""
        name = params.get("name", "")
        arm_id = params.get("arm_id", "")
        prompt = params.get("prompt", "You are now online. Stand by for task assignments.")
        
        if not name or not arm_id:
            return ToolResult(ToolStatus.ERROR, "Missing name or arm_id")
        
        valid_arms = ["arm_left", "arm_right"]
        if arm_id not in valid_arms:
            return ToolResult(ToolStatus.ERROR, f"Invalid arm_id. Must be one of: {valid_arms}")
        
        result = self.teammate_manager.spawn_arm_teammate(name, arm_id, prompt)
        return ToolResult(ToolStatus.SUCCESS, result, {"teammate": name, "arm_id": arm_id})
    
    def _tool_assign_task(self, params: Dict) -> ToolResult:
        teammate = params.get("teammate", "")
        task = params.get("task", {})
        
        if not teammate or not task:
            return ToolResult(ToolStatus.ERROR, "Missing teammate or task")
        
        teammate_obj = self.teammate_manager.get_teammate(teammate)
        if not teammate_obj:
            return ToolResult(ToolStatus.ERROR, f"Teammate '{teammate}' not found. Spawn it first.")
        
        persistent_task_id = task.get("task_id")
        task_id = self.protocol.assign_task("lead", teammate, task, persistent_task_id)
        return ToolResult(ToolStatus.SUCCESS, f"Task {task_id} assigned to {teammate}", {"task_id": task_id})
    
    def _tool_broadcast(self, params: Dict) -> ToolResult:
        content = params.get("content", "")
        teammates = list(self.teammate_manager.teammates.keys())
        
        if not teammates:
            return ToolResult(ToolStatus.ERROR, "No teammates spawned. Use spawn_teammate first.")
        
        result = self.bus.broadcast("lead", content, teammates)
        return ToolResult(ToolStatus.SUCCESS, result)
    
    def _tool_send_message(self, params: Dict) -> ToolResult:
        to = params.get("to", "")
        content = params.get("content", "")
        msg_type = params.get("msg_type", "message")
        
        if not to or not content:
            return ToolResult(ToolStatus.ERROR, "Missing recipient or content")
        
        if to not in self.teammate_manager.teammates:
            return ToolResult(ToolStatus.ERROR, f"Teammate '{to}' not found. Spawn it first.")
        
        self.bus.send("lead", to, content, msg_type)
        return ToolResult(ToolStatus.SUCCESS, f"Message sent to {to}")
    
    def _tool_read_inbox(self) -> ToolResult:
        inbox = self.bus.read_inbox("lead")
        messages = [msg.to_dict() for msg in inbox]
        return ToolResult(ToolStatus.SUCCESS, "Inbox read", {"messages": messages, "count": len(messages)})
    
    def _tool_list_teammates(self) -> ToolResult:
        status = self.teammate_manager.get_team_status()
        return ToolResult(ToolStatus.SUCCESS, "Team status", status)
    
    def _tool_get_scene_state(self) -> ToolResult:
        state = self.manager.get_all_states()
        return ToolResult(ToolStatus.SUCCESS, "Scene state", state)
    
    def _tool_get_task_status(self, params: Dict) -> ToolResult:
        task_id = params.get("task_id", "")
        status = self.protocol.get_task_status(task_id)
        
        if not status:
            return ToolResult(ToolStatus.ERROR, f"Task {task_id} not found")
        
        return ToolResult(ToolStatus.SUCCESS, "Task status", status)
    
    def _tool_shutdown_teammate(self, params: Dict) -> ToolResult:
        name = params.get("name", "")
        result = self.teammate_manager.stop_teammate(name)
        return ToolResult(ToolStatus.SUCCESS, result)
    
    def _tool_shutdown_all(self) -> ToolResult:
        self.teammate_manager.stop_all()
        return ToolResult(ToolStatus.SUCCESS, "All teammates shutdown")
    
    def _tool_create_task(self, params: Dict) -> ToolResult:
        name = params.get("name", "")
        description = params.get("description", "")
        skill_name = params.get("skill_name")
        assigned_arm = params.get("assigned_arm")
        blocked_by = params.get("blocked_by")
        blocks = params.get("blocks")
        
        if not name:
            return ToolResult(ToolStatus.ERROR, "Task name required")
        
        task = self.task_persistence.create(
            name=name,
            description=description,
            skill_name=skill_name,
            assigned_arm=assigned_arm,
            blocked_by=blocked_by,
            blocks=blocks,
        )
        return ToolResult(ToolStatus.SUCCESS, f"Task #{task.task_id} created: {name}", {"task": task.to_dict()})
    
    def _tool_update_task(self, params: Dict) -> ToolResult:
        task_id = params.get("task_id", "")
        status = params.get("status")
        result = params.get("result")
        add_blocked_by = params.get("add_blocked_by")
        add_blocks = params.get("add_blocks")
        
        if not task_id:
            return ToolResult(ToolStatus.ERROR, "Task ID required")
        
        try:
            task = self.task_persistence.update(
                task_id=task_id,
                status=status,
                result=result,
                add_blocked_by=add_blocked_by,
                add_blocks=add_blocks,
            )
            if not task:
                return ToolResult(ToolStatus.ERROR, f"Task {task_id} not found")
            return ToolResult(ToolStatus.SUCCESS, f"Task {task_id} updated", {"task": task.to_dict()})
        except ValueError as e:
            return ToolResult(ToolStatus.ERROR, str(e))
    
    def _tool_list_tasks(self, params: Dict) -> ToolResult:
        status = params.get("status")
        task_list = self.task_persistence.list_all(status)
        summary = self.task_persistence.get_summary()
        formatted = self.task_persistence.format_task_list(status)
        return ToolResult(ToolStatus.SUCCESS, formatted, {"tasks": [t.to_dict() for t in task_list], "summary": summary})
    
    def _tool_get_task(self, params: Dict) -> ToolResult:
        task_id = params.get("task_id", "")
        if not task_id:
            return ToolResult(ToolStatus.ERROR, "Task ID required")
        
        task = self.task_persistence.get(task_id)
        if not task:
            return ToolResult(ToolStatus.ERROR, f"Task {task_id} not found")
        
        return ToolResult(ToolStatus.SUCCESS, f"Task {task_id}", {"task": task.to_dict()})
    
    def _tool_load_skill(self, params: Dict) -> ToolResult:
        skill_name = params.get("name", "")
        if not skill_name:
            return ToolResult(ToolStatus.ERROR, "Skill name required")
        
        skill_content = self.skill_loader.get_skill_content(skill_name)
        if skill_content.startswith("Error:"):
            return ToolResult(ToolStatus.ERROR, skill_content)
        
        return ToolResult(ToolStatus.SUCCESS, f"Skill '{skill_name}' loaded", {"content": skill_content})
    
    def _get_tools(self) -> List[Dict]:
        return LeadToolRegistry.get_all_tools()
    
    def _extract_text(self, content: List) -> str:
        texts = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                texts.append(block.text)
        return "\n".join(texts)
    
    def _handle_offline(self, user_message: str) -> str:
        lower_msg = user_message.lower()
        
        if "state" in lower_msg or "status" in lower_msg:
            return json.dumps(self.manager.get_all_states(), indent=2, ensure_ascii=False)
        
        if "team" in lower_msg:
            return self.teammate_manager.list_teammates()
        
        if "reset" in lower_msg:
            self.manager.reset()
            self.teammate_manager.stop_all()
            return "System reset complete."
        
        return "API key required for AI responses. Available commands: state, team, reset."
    
    def get_state(self) -> Dict:
        return {
            "scene": self.manager.get_all_states(),
            "team": self.teammate_manager.get_team_status(),
            "messages": len(self.messages),
            "tasks": self.task_persistence.get_summary(),
            "skills": self.skill_loader.list_skills(),
        }
    
    def reset(self):
        self.manager.reset()
        self.teammate_manager.stop_all()
        self.messages.clear()
        self.task_persistence.clear_all()
        logger.info("[LeadAgent] Full reset complete")
    
    def disconnect(self):
        self.teammate_manager.stop_all()
        self.manager.disconnect_all()
        logger.info("[LeadAgent] Disconnected")


def create_lead_agent(
    config_path: Optional[str] = None,
    model: Optional[str] = None,
    use_simulator: bool = None,
    api_key: Optional[str] = None,
    stream_callback: Optional[Callable[[str, str], None]] = None,
    tasks_dir: Optional[str] = None,
    skills_dir: Optional[str] = None,
) -> LeadAgent:
    return LeadAgent(
        config_path=config_path,
        model=model,
        use_simulator=use_simulator,
        api_key=api_key,
        stream_callback=stream_callback,
        tasks_dir=tasks_dir,
        skills_dir=skills_dir,
    )
