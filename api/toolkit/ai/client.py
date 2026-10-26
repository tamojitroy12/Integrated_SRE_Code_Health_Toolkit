"""The single place where the Toolkit calls Claude (TRD §10.4, IF-06, DEC-008).

The model receives fixed instructions plus the evidence pack only, has no tools, and its
output is constrained by a JSON schema. Sampling parameters are not sent (removed from the
API). Refusal fallbacks are enabled server-side so a safety decline is rerouted instead of
failing outright; a final ``refusal`` is reported as a failure, never parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

import anthropic

from toolkit.core.config import get_settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AiUnavailable(Exception):  # noqa: N818
    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        self.reason = reason
        self.retryable = retryable
        super().__init__(reason)


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None


class LlmClient(Protocol):
    def complete(self, system: str, messages: list[dict[str, Any]], schema: dict[str, Any]) -> Completion: ...


class ClaudeClient:
    def __init__(self) -> None:
        s = get_settings()
        if not s.anthropic_api_key.get_secret_value():
            raise AiUnavailable("ANTHROPIC_API_KEY is not configured")
        self.model = s.claude_model
        self.max_tokens = s.ai_max_output_tokens
        self._client = anthropic.Anthropic(
            api_key=s.anthropic_api_key.get_secret_value(),
            base_url=s.anthropic_base_url or None,
            timeout=s.ai_request_timeout_seconds,
            max_retries=2,
        )

    def complete(self, system: str, messages: list[dict[str, Any]], schema: dict[str, Any]) -> Completion:
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=cast(Any, messages),
                output_config=cast(Any, {"effort": "medium", "format": {"type": "json_schema", "schema": schema}}),
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise AiUnavailable("Anthropic rejected the API key") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AiUnavailable("The API key lacks permission for this model") from exc
        except anthropic.NotFoundError as exc:
            raise AiUnavailable(f"Model {self.model!r} was not found") from exc
        except anthropic.BadRequestError as exc:
            raise AiUnavailable(f"Request rejected by the Claude API: {exc.message[:200]}") from exc
        except anthropic.RateLimitError as exc:
            raise AiUnavailable("Claude API rate limit reached", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise AiUnavailable(f"Claude API error {exc.status_code}", retryable=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:
            raise AiUnavailable("Claude API unreachable", retryable=True) from exc
        if response.stop_reason == "refusal":
            raise AiUnavailable("The model declined this request")
        if response.stop_reason == "max_tokens":
            raise AiUnavailable("The model output exceeded AI_MAX_OUTPUT_TOKENS")
        text = "".join(getattr(b, "text", "") for b in response.content if b.type == "text")
        usage = response.usage
        return Completion(
            text, response.model, int(usage.input_tokens or 0), int(usage.output_tokens or 0), response.stop_reason
        )
