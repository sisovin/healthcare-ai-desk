"""Provider-neutral LLM routing with a final healthcare safety egress gate.

Adapters are intentionally injected: this keeps provider SDKs out of the domain
layer and makes deterministic mock-provider tests possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Protocol

from app.services.safety_policy import evaluate_execution_safety


class LLMGatewayError(Exception):
    """Base error for a request that did not complete."""


class ProviderUnavailableError(LLMGatewayError):
    """The selected provider is unavailable or returned a retriable error."""


class ApprovalRequiredError(LLMGatewayError):
    """A high-impact request reached the provider boundary without approval."""


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMRequest:
    messages: tuple[ChatMessage, ...]
    task_type: str
    required_capabilities: frozenset[str] = frozenset({"chat"})
    preferred_provider: str | None = None
    approval_granted: bool = False

    @property
    def content_for_safety_check(self) -> str:
        return "\n".join(message.content for message in self.messages)


@dataclass(frozen=True)
class LLMResponse:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    provider_request_id: str | None = None


class LLMProvider(Protocol):
    """Implemented by an OpenAI, Anthropic, Ollama, or test adapter."""

    def complete(self, *, model: str, request: LLMRequest) -> LLMResponse: ...


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    capabilities: frozenset[str]
    input_cost_per_million: Decimal = Decimal("0")
    output_cost_per_million: Decimal = Decimal("0")
    available: bool = True
    priority: int = 100


@dataclass(frozen=True)
class GatewayResult:
    response: LLMResponse
    route: ModelRoute
    cost_usd: Decimal
    fallback_count: int


AuditSink = Callable[[str, dict[str, object]], None]


class LLMGateway:
    def __init__(
        self,
        *,
        providers: dict[str, LLMProvider],
        routes: list[ModelRoute],
        audit_sink: AuditSink | None = None,
    ) -> None:
        self._providers = {name.lower(): provider for name, provider in providers.items()}
        self._routes = tuple(routes)
        self._audit_sink = audit_sink or (lambda _action, _details: None)

    def route(self, request: LLMRequest, *, excluded: set[tuple[str, str]] | None = None) -> ModelRoute:
        excluded = excluded or set()
        candidates = [
            route
            for route in self._routes
            if route.available
            and route.provider.lower() in self._providers
            and request.required_capabilities.issubset(route.capabilities)
            and (route.provider, route.model) not in excluded
            and (request.preferred_provider is None or route.provider.lower() == request.preferred_provider.lower())
        ]
        if not candidates:
            raise ProviderUnavailableError("No available model route meets the requested capability and provider policy.")
        return min(
            candidates,
            key=lambda item: (item.input_cost_per_million + item.output_cost_per_million, item.priority, item.provider, item.model),
        )

    def complete(self, request: LLMRequest, *, max_attempts: int = 2) -> GatewayResult:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one.")

        excluded: set[tuple[str, str]] = set()
        failures: list[str] = []
        for attempt in range(max_attempts):
            # Route again after a failure so a lower-priority provider can act as fallback.
            route = self.route(request, excluded=excluded)
            try:
                decision = evaluate_execution_safety(
                    model_provider=route.provider,
                    task_type=request.task_type,
                    input_payload=request.content_for_safety_check,
                    task_payload=None,
                )
            except ValueError as exc:
                self._audit_sink("llm.request_denied", {"provider": route.provider, "reason": "patient_data_policy"})
                raise LLMGatewayError(str(exc)) from exc
            if decision.requires_human_approval and not request.approval_granted:
                self._audit_sink("llm.request_denied", {"provider": route.provider, "reason": decision.reason})
                raise ApprovalRequiredError("Human approval is required before this high-impact LLM request can be sent.")

            try:
                response = self._providers[route.provider.lower()].complete(model=route.model, request=request)
            except ProviderUnavailableError as exc:
                excluded.add((route.provider, route.model))
                failures.append(f"{route.provider}/{route.model}: {exc}")
                self._audit_sink("llm.provider_failed", {"provider": route.provider, "model": route.model})
                continue

            cost = self._cost(route, response)
            self._audit_sink(
                "llm.completed",
                {
                    "provider": route.provider,
                    "model": route.model,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": str(cost),
                    "fallback_count": attempt,
                },
            )
            return GatewayResult(response=response, route=route, cost_usd=cost, fallback_count=attempt)

        raise ProviderUnavailableError("All eligible LLM providers failed: " + "; ".join(failures))

    @staticmethod
    def _cost(route: ModelRoute, response: LLMResponse) -> Decimal:
        raw_cost = (
            Decimal(response.input_tokens) * route.input_cost_per_million
            + Decimal(response.output_tokens) * route.output_cost_per_million
        ) / Decimal("1000000")
        return raw_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
