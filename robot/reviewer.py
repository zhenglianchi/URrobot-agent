"""
Reviewer审查智能体
基于Reflection机制，对任务计划和执行结果进行复盘评审
检查计划是否符合物理约束和依赖规则，提升执行正确性
"""
import json
import os
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass

from utils.logger_handler import logger
from robot.team import MessageBus, CoordinationProtocol, TeamState, TeamMessage
from robot.task_persistence import TaskPersistence
from robot.skill_loader import SkillLoader


REVIEWER_SYSTEM_PROMPT = """你是双臂机器人装配系统的**Reviewer审查智能体**，负责对Lead智能体生成的任务计划进行合规性审查，以及对最终执行结果进行验收。

## 你的核心职责
1. **计划审查**：检查任务计划是否违反物理规则和依赖约束，识别潜在错误
2. **结果验收**：所有任务执行完成后，检查最终状态是否符合用户目标
3. **给出明确结论**：必须明确给出"通过"或"不通过"结论，不通过时说明具体修改建议

---

## 计划审查检查清单（必须逐项检查）

### 1. 依赖关系检查
- [ ] 每个任务的 `blocked_by` 依赖关系是否正确
- [ ] 是否存在循环依赖
- [ ] 前置任务是否确实需要阻塞当前任务

### 2. 物理约束检查（关键！必须严格检查）
请对照下表检查每个任务：

| 操作 | 必须满足的前置条件 |
|-----|------------------|
| pick-screwdriver | 螺丝刀必须在工具架 (status: stored) |
| loosen-screw | 机械臂必须持有 screwdriver |
| tighten-screw | 机械臂必须持有 screwdriver |
| pick-old-oru | 螺丝必须已拧松 (oru_old 状态: loose)，夹爪必须打开，机械臂不能持有其他物体 |
| pull-out-oru | 螺丝必须已拧松，机械臂必须持有 oru_old |
| insert-oru | 旧ORU已经移出，机械臂必须持有 oru_new |
| place-screwdriver | 机械臂必须持有 screwdriver |

### 3. 夹爪占用规则检查（非常容易出错）
- [ ] 一个机械臂夹爪同一时间只能持有一个物体
- [ ] 完成操作后是否及时释放（工具/零件归位）
- [ ] 常见错误：拧松螺丝后没有放回螺丝刀就去抓ORU，这是错误的！

### 4. 双臂并行检查
- [ ] 无依赖的任务是否识别出并行机会
- [ ] 两个机械臂是否会同时操作同一位置导致冲突
- [ ] 是否存在不必要的依赖阻塞

### 5. 最终归位检查
- [ ] 所有工具使用完成后是否放回原位（特别是螺丝刀）
- [ ] 所有任务是否都有明确的收尾

---

## 输出格式
请按照以下JSON格式输出审查结果：

```json
{
  "approved": true/false,
  "errors": [
    "错误描述1",
    "错误描述2"
  ],
  "suggestions": [
    "修改建议1",
    "修改建议2"
  ],
  "comment": "一句话总结评审意见"
}
```

- `approved`: true = 通过，可以执行；false = 不通过，需要修改
- `errors`: 列出发现的错误，如果没有错误就是空数组
- `suggestions`: 具体的修改建议
- `comment`: 一句话总结，让Lead快速理解

---

## 评审原则
- 严格但不苛刻：只检查确实违反规则的错误
- 对不确定的地方，倾向于通过，而不是误杀
- 修改建议要具体，指明哪个任务有问题，应该怎么改
"""


@dataclass
class ReviewResult:
    """评审结果"""
    approved: bool
    errors: List[str]
    suggestions: List[str]
    comment: str

    def to_dict(self) -> Dict:
        return {
            "approved": self.approved,
            "errors": self.errors,
            "suggestions": self.suggestions,
            "comment": self.comment
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class ReviewerAgent:
    """Reviewer审查智能体
    负责对任务计划和执行结果进行Reflection评审
    """

    def __init__(
        self,
        bus: MessageBus,
        protocol: CoordinationProtocol,
        team_state: TeamState,
        task_persistence: TaskPersistence,
        skill_loader: SkillLoader,
        model: str = None,
        api_key: str = None,
        base_url: str = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.bus = bus
        self.protocol = protocol
        self.team_state = team_state
        self.task_persistence = task_persistence
        self.skill_loader = skill_loader
        self.model = model or os.environ.get("MODEL_ID", "minimax-m2.5")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        self.stream_callback = stream_callback

        # 添加到团队状态
        self.team_state.add_member("reviewer", "reviewer", ["plan-review", "result-validation"])

        # 注册消息回调
        self.bus.register_callback("reviewer", self._on_message)

        self._client = None
        logger.info("[ReviewerAgent] Initialized")

    @property
    def client(self):
        """懒加载获取Anthropic客户端"""
        if self._client is None and self.api_key:
            try:
                import anthropic
                client_kwargs = {"api_key": self.api_key}
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                self._client = anthropic.Anthropic(**client_kwargs)
            except ImportError:
                logger.warning("[ReviewerAgent] anthropic package not installed")
        return self._client

    def _emit(self, event_type: str, content: str):
        """发送事件到流回调"""
        if self.stream_callback:
            self.stream_callback(event_type, content)
        if event_type != "thinking":
            logger.info(f"[Reviewer][{event_type}] {content[:150]}...")

    def _on_message(self, msg: TeamMessage):
        """处理收到的消息"""
        self._emit("message-received", f"From {msg.sender}: {msg.msg_type}")
        self.team_state.increment_message_count("reviewer")

        if msg.msg_type == "review_request":
            self._handle_review_request(msg)

    def _handle_review_request(self, msg: TeamMessage):
        """处理评审请求"""
        request_data = msg.extra.get("request_data", {})
        review_type = request_data.get("type", "plan")  # plan 或 result
        tasks_json = request_data.get("tasks", "[]")
        user_target = request_data.get("user_target", "")

        self._emit("review-started", f"Reviewing {review_type}, {len(json.loads(tasks_json))} tasks")

        if not self.client:
            self._send_result(msg.sender, ReviewResult(
                approved=False,
                errors=["Anthropic client not initialized"],
                suggestions=["Check API key configuration"],
                comment="评审失败：客户端未初始化"
            ))
            return

        result = self._do_review(review_type, tasks_json, user_target)
        self._send_result(msg.sender, result)

    def _do_review(self, review_type: str, tasks_json: str, user_target: str) -> ReviewResult:
        """执行评审"""
        prompt = self._build_review_prompt(review_type, tasks_json, user_target)

        self._emit("thinking", "[thinking]Starting review...[/thinking]")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=REVIEWER_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            text = self._extract_text(response.content)
            result = self._parse_result(text)

            self._emit("review-completed", f"approved={result.approved}, errors={len(result.errors)}")
            return result

        except Exception as e:
            logger.error(f"[Reviewer] Review failed: {e}")
            return ReviewResult(
                approved=False,
                errors=[f"Review execution error: {str(e)}"],
                suggestions=[],
                comment="评审执行失败"
            )

    def _build_review_prompt(self, review_type: str, tasks_json: str, user_target: str) -> str:
        """构建评审prompt"""
        if review_type == "plan":
            return f"""请对以下任务计划进行审查：

用户目标: {user_target}

任务列表:
{tasks_json}

请按照系统提示中的检查清单逐项检查，输出JSON格式的评审结果。
"""
        else:  # result
            return f"""请对以下执行结果进行验收：

用户目标: {user_target}

最终任务状态:
{tasks_json}

请检查所有任务是否都已完成，最终状态是否符合用户目标，输出JSON格式的评审结果。
"""

    def _extract_text(self, content: List) -> str:
        """提取文本响应"""
        texts = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                texts.append(block.text)
        return "\n".join(texts)

    def _parse_result(self, text: str) -> ReviewResult:
        """解析大模型返回的JSON结果"""
        # 尝试提取JSON
        import re
        json_match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        else:
            json_match = re.search(r'{.*}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)

        try:
            data = json.loads(text)
            return ReviewResult(
                approved=data.get("approved", False),
                errors=data.get("errors", []),
                suggestions=data.get("suggestions", []),
                comment=data.get("comment", "")
            )
        except json.JSONDecodeError as e:
            logger.warning(f"[Reviewer] Failed to parse JSON, falling back: {e}")
            # 简单匹配
            approved = "通过" in text or "approved" in text.lower() and "不通过" not in text
            return ReviewResult(
                approved=approved,
                errors=[],
                suggestions=[],
                comment=text[:200]
            )

    def _send_result(self, receiver: str, result: ReviewResult):
        """发送评审结果"""
        self.bus.send(
            sender="reviewer",
            receiver=receiver,
            content=result.comment,
            msg_type="review_result",
            extra={"result": result.to_dict()}
        )
        self._emit("result-sent", f"Sent result: approved={result.approved}")

    def get_status(self) -> Dict:
        """获取Reviewer状态"""
        return {
            "name": "reviewer",
            "role": "reviewer",
            "status": self.team_state.get_member("reviewer").get("status", "unknown")
        }
