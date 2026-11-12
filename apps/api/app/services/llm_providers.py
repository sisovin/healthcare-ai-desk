"""Thin HTTP adapters for OpenAI-compatible, Anthropic, and Ollama chat APIs.

The transport is injected so credentials and network I/O stay at the application
edge, and each adapter can be tested without a live provider.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.llm_gateway import LLMRequest, LLMResponse, ProviderUnavailableError


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: dict[str, Any]
    request_id: str | None = None


class JsonHttpTransport(Protocol):
    def post(self, *, url: str, headers: dict[str, str], body: dict[str, Any], timeout_seconds: float) -> HttpResponse: ...


class UrllibJsonTransport:
    """Standard-library transport used by production adapter wiring.

    The gateway owns provider selection and safety checks; this class only
    serializes an already-authorized request over HTTPS/local HTTP.
    """

    def post(self, *, url: str, headers: dict[str, str], body: dict[str, Any], timeout_seconds: float) -> HttpResponse:
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: endpoint is configured by administrator
                raw = response.read().decode("utf-8")
                return HttpResponse(
                    status_code=response.status,
                    body=json.loads(raw) if raw else {},
                    request_id=response.headers.get("x-request-id"),
                )
        except HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {}
            return HttpResponse(status_code=exc.code, body=body, request_id=exc.headers.get("x-request-id"))
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderUnavailableError("Provider transport failed.") from exc


def _messages(request: LLMRequest) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in request.messages]


class OpenAIProvider:
    def __init__(self, *, transport: JsonHttpTransport, api_key: str, base_url: str = "https://api.openai.com/v1", timeout_seconds: float = 30) -> None:
        self._transport, self._api_key, self._base_url, self._timeout = transport, api_key, base_url.rstrip("/"), timeout_seconds

    def complete(self, *, model: str, request: LLMRequest) -> LLMResponse:
        response = self._transport.post(
            url=f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            body={"model": model, "messages": _messages(request)},
            timeout_seconds=self._timeout,
        )
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"OpenAI returned HTTP {response.status_code}.")
        try:
            usage = response.body.get("usage", {})
            return LLMResponse(
                content=response.body["choices"][0]["message"]["content"],
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                provider_request_id=response.request_id,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailableError("OpenAI returned an invalid completion payload.") from exc


class AnthropicProvider:
    def __init__(self, *, transport: JsonHttpTransport, api_key: str, base_url: str = "https://api.anthropic.com/v1", timeout_seconds: float = 30) -> None:
        self._transport, self._api_key, self._base_url, self._timeout = transport, api_key, base_url.rstrip("/"), timeout_seconds

    def complete(self, *, model: str, request: LLMRequest) -> LLMResponse:
        response = self._transport.post(
            url=f"{self._base_url}/messages",
            headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            body={"model": model, "max_tokens": 1024, "messages": _messages(request)},
            timeout_seconds=self._timeout,
        )
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"Anthropic returned HTTP {response.status_code}.")
        try:
            usage = response.body.get("usage", {})
            return LLMResponse(
                content=response.body["content"][0]["text"],
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                provider_request_id=response.request_id,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailableError("Anthropic returned an invalid completion payload.") from exc


class OllamaProvider:
    def __init__(self, *, transport: JsonHttpTransport, base_url: str = "http://localhost:11434", timeout_seconds: float = 60) -> None:
        self._transport, self._base_url, self._timeout = transport, base_url.rstrip("/"), timeout_seconds

    def complete(self, *, model: str, request: LLMRequest) -> LLMResponse:
        response = self._transport.post(
            url=f"{self._base_url}/api/chat",
            headers={"Content-Type": "application/json"},
            body={"model": model, "messages": _messages(request), "stream": False},
            timeout_seconds=self._timeout,
        )
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"Ollama returned HTTP {response.status_code}.")
        try:
            return LLMResponse(
                content=response.body["message"]["content"],
                input_tokens=int(response.body.get("prompt_eval_count", 0)),
                output_tokens=int(response.body.get("eval_count", 0)),
                provider_request_id=response.request_id,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailableError("Ollama returned an invalid completion payload.") from exc
