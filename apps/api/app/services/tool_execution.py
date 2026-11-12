"""Allow-listed agent-tool execution with permission and resource boundaries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import json
from typing import Any, Callable


class ToolExecutionError(Exception):
    pass


class ToolPermissionError(ToolExecutionError):
    pass


class ToolTimeoutError(ToolExecutionError):
    pass


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    handler: ToolHandler
    required_permission: str
    timeout_seconds: float = 10.0
    max_input_bytes: int = 32_768
    max_output_bytes: int = 65_536


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_name: str
    output: Any
    output_bytes: int


class AgentToolRegistry:
    """Only application-registered tools can be invoked; no dynamic shell commands."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool '{definition.name}' is already registered.")
        if definition.timeout_seconds <= 0 or definition.max_input_bytes <= 0 or definition.max_output_bytes <= 0:
            raise ValueError("Tool resource limits must be positive.")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolExecutionError(f"Tool '{name}' is not registered.") from exc

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())


class ToolExecutionSandbox:
    """Executes an allow-listed, trusted tool with enforced API-level limits.

    This boundary does not expose a shell, filesystem path, or arbitrary code to
    an agent. Deployment must additionally use a container/cgroup boundary for
    CPU and memory limits when tools access untrusted content.
    """

    def __init__(self, registry: AgentToolRegistry, *, audit_sink: Callable[[str, dict[str, object]], None] | None = None) -> None:
        self._registry = registry
        self._audit_sink = audit_sink or (lambda _action, _details: None)

    def execute(self, *, tool_name: str, arguments: dict[str, Any], permissions: set[str]) -> ToolExecutionResult:
        definition = self._registry.get(tool_name)
        if definition.required_permission not in permissions:
            self._audit_sink("tool.denied", {"tool": tool_name, "reason": "permission"})
            raise ToolPermissionError(f"Permission '{definition.required_permission}' is required for tool '{tool_name}'.")

        input_size = len(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))
        if input_size > definition.max_input_bytes:
            raise ToolExecutionError(f"Tool input exceeds the {definition.max_input_bytes}-byte limit.")

        # The executor gives the request a hard response deadline. Registered
        # handlers must be side-effect safe/idempotent because a timed-out worker
        # may need process-level cancellation in production deployment.
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{tool_name}")
        try:
            future = executor.submit(definition.handler, arguments)
            try:
                output = future.result(timeout=definition.timeout_seconds)
            except FutureTimeoutError as exc:
                future.cancel()
                self._audit_sink("tool.timed_out", {"tool": tool_name, "timeout_seconds": definition.timeout_seconds})
                raise ToolTimeoutError(f"Tool '{tool_name}' exceeded its timeout.") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        encoded_output = json.dumps(output, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded_output) > definition.max_output_bytes:
            raise ToolExecutionError(f"Tool output exceeds the {definition.max_output_bytes}-byte limit.")
        self._audit_sink("tool.completed", {"tool": tool_name, "output_bytes": len(encoded_output)})
        return ToolExecutionResult(tool_name=tool_name, output=output, output_bytes=len(encoded_output))
