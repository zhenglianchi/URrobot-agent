from typing import Dict, List, Optional, Any, Callable, Generator
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger_handler import logger
from robot.multi_arm_manager import MultiArmManager
from robot.task_queue import TaskQueue, TaskPriority
from robot.tools import create_robot_tools, ToolResult, ToolStatus
from robot.prompts import get_system_prompt


class MultiArmAgent:
    def __init__(
        self,
        config_path: Optional[str] = None,
        model: Optional[str] = None,
        use_simulator: bool = None,
        api_key: Optional[str] = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.config_path = config_path
        self.model = model or os.environ.get("MODEL_ID", "minimax-m2.5")
        self.use_simulator = use_simulator if use_simulator is not None else os.environ.get("USE_SIMULATOR", "true").lower() == "true"
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = os.environ.get("ANTHROPIC_BASE_URL")
        self.stream_callback = stream_callback
        
        self.manager = MultiArmManager(config_path, use_simulator=self.use_simulator)
        self.task_queue = TaskQueue()
        self.tool_registry = create_robot_tools(self.manager, self.task_queue)
        
        self.messages: List[Dict] = []
        self.max_iterations = 50
        self.conversation_history: List[Dict] = []
        
        self._client = None
        
        logger.info(f"[Agent] Initialized with model: {self.model}")
        if self.base_url:
            logger.info(f"[Agent] Using base URL: {self.base_url}")

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
                logger.warning("[Agent] anthropic package not installed")
        return self._client

    def _emit(self, event_type: str, content: str):
        if self.stream_callback:
            self.stream_callback(event_type, content)
        logger.info(f"[Agent][{event_type}] {content[:200]}...")

    def chat(self, user_message: str) -> str:
        self.conversation_history.append({"role": "user", "content": user_message})
        
        if not self.client:
            return self._handle_offline(user_message)
        
        try:
            return self._run_agent_loop(user_message)
        except Exception as e:
            logger.error(f"[Agent] Error: {e}")
            return f"Error: {str(e)}"

    def chat_stream(self, user_message: str) -> Generator[str, None, None]:
        self.conversation_history.append({"role": "user", "content": user_message})
        
        if not self.client:
            yield self._handle_offline(user_message)
            return
        
        messages = self._build_messages(user_message)
        tools = self.tool_registry.get_tools_schema()
        
        for iteration in range(self.max_iterations):
            self._emit("iteration", f"Starting iteration {iteration + 1}")
            
            try:
                with self.client.messages.stream(
                    model=self.model,
                    max_tokens=4096,
                    system=get_system_prompt(),
                    messages=messages,
                    tools=tools,
                ) as stream:
                    current_text = ""
                    tool_calls = []
                    
                    for event in stream:
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "type"):
                                if event.delta.type == "text_delta":
                                    text = event.delta.text
                                    current_text += text
                                    self._emit("thinking", text)
                                    yield f"[thinking]{text}[/thinking]"
                        
                    final_message = stream.get_final_message()
                    stop_reason = final_message.stop_reason
                    assistant_content = final_message.content
                    
                    messages.append({"role": "assistant", "content": assistant_content})
                    
                    if stop_reason == "end_turn":
                        final_text = self._extract_text(assistant_content)
                        self.conversation_history.append({"role": "assistant", "content": final_text})
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
                    
                    if stop_reason == "max_tokens":
                        yield "[error]Response truncated due to token limit.[/error]"
                        return
                    
                    yield f"[error]Unexpected stop condition: {stop_reason}[/error]"
                    return
                    
            except Exception as e:
                error_msg = f"Error in iteration {iteration + 1}: {str(e)}"
                self._emit("error", error_msg)
                yield f"[error]{error_msg}[/error]"
                return
        
        yield "[error]Max iterations reached without completion.[/error]"

    def _run_agent_loop(self, user_message: str) -> str:
        messages = self._build_messages(user_message)
        tools = self.tool_registry.get_tools_schema()
        
        for iteration in range(self.max_iterations):
            self._emit("iteration", f"Starting iteration {iteration + 1}")
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=get_system_prompt(),
                messages=messages,
                tools=tools,
            )
            
            stop_reason = response.stop_reason
            assistant_content = response.content
            
            messages.append({"role": "assistant", "content": assistant_content})
            
            if stop_reason == "end_turn":
                final_text = self._extract_text(assistant_content)
                self.conversation_history.append({"role": "assistant", "content": final_text})
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
            
            if stop_reason == "max_tokens":
                return "Response truncated due to token limit."
            
            logger.warning(f"[Agent] Unknown stop reason: {stop_reason}")
            return "Unexpected stop condition."
        
        return "Max iterations reached without completion."

    def _build_messages(self, user_message: str) -> List[Dict]:
        messages = []
        for msg in self.conversation_history[:-1]:
            messages.append(msg)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _execute_tool(self, name: str, params: Dict) -> ToolResult:
        logger.info(f"[Agent] Tool call: {name}({params})")
        result = self.tool_registry.execute(name, params)
        logger.info(f"[Agent] Tool result: {result.status.value}")
        return result

    def _extract_text(self, content: List) -> str:
        texts = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                texts.append(block.text)
        return "\n".join(texts)

    def _handle_offline(self, user_message: str) -> str:
        lower_msg = user_message.lower()
        
        if "state" in lower_msg or "status" in lower_msg:
            return self.manager.get_scene_summary()
        
        if "task" in lower_msg:
            return self.task_queue.get_task_summary()
        
        if "reset" in lower_msg:
            self.manager.reset()
            self.task_queue.reset()
            return "System reset complete."
        
        if "available" in lower_msg or "idle" in lower_msg:
            arms = self.manager.get_available_arms()
            return f"Available arms: {arms}" if arms else "No arms available."
        
        return "API key required for AI responses. Available commands: state, tasks, reset, available."

    def get_state(self) -> Dict:
        return {
            "manager": self.manager.get_all_states(),
            "tasks": self.task_queue.get_all_status(),
            "conversation_length": len(self.conversation_history),
        }

    def reset(self):
        self.manager.reset()
        self.task_queue.reset()
        self.conversation_history.clear()
        logger.info("[Agent] Full reset complete")

    def disconnect(self):
        self.manager.disconnect_all()
        logger.info("[Agent] Disconnected")


def create_agent(
    config_path: Optional[str] = None,
    model: Optional[str] = None,
    use_simulator: bool = None,
    api_key: Optional[str] = None,
    stream_callback: Optional[Callable[[str, str], None]] = None,
) -> MultiArmAgent:
    return MultiArmAgent(
        config_path=config_path,
        model=model,
        use_simulator=use_simulator,
        api_key=api_key,
        stream_callback=stream_callback,
    )
