from decimal import Decimal
import time

import pytest

from app.services.llm_gateway import (
    ApprovalRequiredError,
    ChatMessage,
    LLMGateway,
    LLMGatewayError,
    LLMRequest,
    LLMResponse,
    ModelRoute,
    ProviderUnavailableError,
)
from app.services.llm_providers import AnthropicProvider, HttpResponse, OllamaProvider, OpenAIProvider
from app.services.tool_execution import (
    AgentToolRegistry,
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionSandbox,
    ToolPermissionError,
    ToolTimeoutError,
)


class MockProvider:
    def __init__(self, response: LLMResponse | Exception) -> None:
        self.response = response
        self.calls: list[str] = []

    def complete(self, *, model: str, request: LLMRequest) -> LLMResponse:
        self.calls.append(model)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class MockTransport:
    def __init__(self, body: dict, status_code: int = 200) -> None:
        self.body, self.status_code = body, status_code
        self.requests: list[dict] = []

    def post(self, **kwargs) -> HttpResponse:
        self.requests.append(kwargs)
        return HttpResponse(status_code=self.status_code, body=self.body, request_id="request-1")


def _request(*, task_type: str = "reporting", approval_granted: bool = False, content: str = "Summarize aggregate indicators") -> LLMRequest:
    return LLMRequest(messages=(ChatMessage(role="user", content=content),), task_type=task_type, approval_granted=approval_granted)


def test_gateway_routes_by_cost_falls_back_and_records_usage() -> None:
    events: list[tuple[str, dict]] = []
    openai = MockProvider(ProviderUnavailableError("rate limited"))
    ollama = MockProvider(LLMResponse(content="local answer", input_tokens=120, output_tokens=30))
    gateway = LLMGateway(
        providers={"openai": openai, "ollama": ollama},
        routes=[
            ModelRoute("openai", "small", frozenset({"chat"}), Decimal("1"), Decimal("2"), priority=1),
            ModelRoute("ollama", "llama-local", frozenset({"chat"}), Decimal("0"), Decimal("0"), priority=2),
        ],
        audit_sink=lambda action, details: events.append((action, details)),
    )
    # Prefer OpenAI first, then make it unavailable so local Ollama becomes fallback.
    gateway._routes = (
        ModelRoute("openai", "small", frozenset({"chat"}), Decimal("0"), Decimal("0"), priority=1),
        ModelRoute("ollama", "llama-local", frozenset({"chat"}), Decimal("1"), Decimal("1"), priority=2),
    )
    result = gateway.complete(_request())

    assert result.route.provider == "ollama"
    assert result.fallback_count == 1
    assert result.cost_usd == Decimal("0.000150")
    assert openai.calls == ["small"]
    assert ollama.calls == ["llama-local"]
    assert [event[0] for event in events] == ["llm.provider_failed", "llm.completed"]


def test_gateway_enforces_approval_and_external_patient_data_boundary() -> None:
    provider = MockProvider(LLMResponse(content="not sent"))
    gateway = LLMGateway(
        providers={"openai": provider},
        routes=[ModelRoute("openai", "model", frozenset({"chat"}))],
    )

    with pytest.raises(ApprovalRequiredError):
        gateway.complete(_request(task_type="clinical_triage"))
    with pytest.raises(LLMGatewayError, match="External LLM execution is denied"):
        gateway.complete(_request(content='{"patient_id":"P-101"}'))
    assert provider.calls == []


def test_openai_anthropic_and_ollama_adapters_use_mock_transport() -> None:
    openai_transport = MockTransport({"choices": [{"message": {"content": "openai"}}], "usage": {"prompt_tokens": 2, "completion_tokens": 3}})
    anthropic_transport = MockTransport({"content": [{"text": "anthropic"}], "usage": {"input_tokens": 4, "output_tokens": 5}})
    ollama_transport = MockTransport({"message": {"content": "ollama"}, "prompt_eval_count": 6, "eval_count": 7})

    assert OpenAIProvider(transport=openai_transport, api_key="test").complete(model="m", request=_request()).content == "openai"
    assert AnthropicProvider(transport=anthropic_transport, api_key="test").complete(model="m", request=_request()).input_tokens == 4
    assert OllamaProvider(transport=ollama_transport).complete(model="m", request=_request()).output_tokens == 7
    assert openai_transport.requests[0]["url"].endswith("/chat/completions")
    assert anthropic_transport.requests[0]["url"].endswith("/messages")
    assert ollama_transport.requests[0]["url"].endswith("/api/chat")


def test_tool_registry_sandbox_enforces_permission_timeout_and_byte_limits() -> None:
    registry = AgentToolRegistry()
    registry.register(ToolDefinition("sum", "adds values", lambda value: {"total": value["a"] + value["b"]}, "tool.math"))
    registry.register(ToolDefinition("slow", "slow tool", lambda _value: (time.sleep(0.1), "done")[1], "tool.slow", timeout_seconds=0.01))
    registry.register(ToolDefinition("large", "large result", lambda _value: "x" * 20, "tool.large", max_output_bytes=10))
    sandbox = ToolExecutionSandbox(registry)

    assert sandbox.execute(tool_name="sum", arguments={"a": 2, "b": 5}, permissions={"tool.math"}).output == {"total": 7}
    with pytest.raises(ToolPermissionError):
        sandbox.execute(tool_name="sum", arguments={"a": 2, "b": 5}, permissions=set())
    with pytest.raises(ToolTimeoutError):
        sandbox.execute(tool_name="slow", arguments={}, permissions={"tool.slow"})
    with pytest.raises(ToolExecutionError, match="output exceeds"):
        sandbox.execute(tool_name="large", arguments={}, permissions={"tool.large"})
