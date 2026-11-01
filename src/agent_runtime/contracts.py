"""Run data shared by the runner and harness, independent of a benchmark suite."""
from dataclasses import dataclass, field
from typing import Any, Literal

Terminal = Literal["completed", "blocked", "error", "unknown", "budget_exhausted", "timeout", "cancelled", "protocol_error"]


@dataclass(frozen=True)
class TaskInput:
    episode_id: str
    prompt: str
    tool_names: tuple[str, ...]


@dataclass(frozen=True)
class Limits:
    model_attempts: int = 8
    tool_attempts: int = 16
    seconds: float = 180

    def __post_init__(self):
        if (type(self.model_attempts) is not int or type(self.tool_attempts) is not int or
                self.model_attempts < 1 or self.tool_attempts < 1 or not 0 < self.seconds <= 3600):
            raise ValueError("invalid_run_limits")


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolOutcome:
    call_id: str
    status: Literal["executed", "blocked", "error", "unknown"]
    output: Any = None
    evidence_ref: str | None = None
    guard: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunResult:
    episode_id: str
    status: Terminal
    answer: str
    model_attempts: int
    tool_attempts: int
    outcomes: tuple[ToolOutcome, ...]
    error: str | None = None
