import time
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.ai.prompts import build_reply_prompt
from app.ai.validators import is_valid_reply
from app.config import settings
from app.utils.logger import logger


client = None


@dataclass
class ReplyGenerationResult:
    reply: str | None
    error: str | None = None
    prompt: str | None = None
    completion: str | None = None
    model: str | None = None
    temperature: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.reply is not None and self.error is None


def format_conversation(messages):
    lines = []
    for msg in messages:
        if hasattr(msg, "speaker"):
            sender = getattr(msg, "speaker", "unknown")
            message = getattr(msg, "message", "")
        else:
            sender = msg.get("sender") or msg.get("role", "unknown")
            message = msg.get("message") or msg.get("content", "")
        lines.append(f"{sender.upper()}: {message}")
    return "\n".join(lines)


def _extract_usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0, 0

    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    total_tokens = getattr(usage, "total_tokens", 0) or 0
    return prompt_tokens, completion_tokens, total_tokens


def _default_completion_create(**kwargs):
    global client
    if client is None:
        client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=25.0
        )
    return client.chat.completions.create(**kwargs)


def generate_reply_result(
    messages,
    *,
    model: str | None = None,
    temperature: float | None = None,
    retries: int = 3,
    base_delay: int = 2,
    prompt_builder: Callable[[str], str] | None = None,
    completion_create: Callable[..., Any] | None = None,
):
    conversation = format_conversation(messages)
    prompt_builder = prompt_builder or build_reply_prompt
    prompt = prompt_builder(conversation)

    model_name = model or settings.OPENAI_REPLY_MODEL
    model_temperature = (
        settings.OPENAI_REPLY_TEMPERATURE
        if temperature is None
        else temperature
    )
    completion_create = completion_create or _default_completion_create
    last_error = None

    for attempt in range(1, retries + 1):
        started_at = time.perf_counter()
        try:
            response = completion_create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=model_temperature,
            )
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            completion = response.choices[0].message.content.strip()
            prompt_tokens, completion_tokens, total_tokens = _extract_usage(
                response
            )

            if not is_valid_reply(completion):
                logger.warning("Invalid AI reply generated")
                return ReplyGenerationResult(
                    reply=None,
                    error="invalid_ai_reply",
                    prompt=prompt,
                    completion=completion,
                    model=model_name,
                    temperature=model_temperature,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                )

            return ReplyGenerationResult(
                reply=completion,
                prompt=prompt,
                completion=completion,
                model=model_name,
                temperature=model_temperature,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
            )

        except (RateLimitError, APITimeoutError, APIError) as e:
            last_error = str(e)
            logger.warning(
                f"OpenAI reply attempt {attempt}/{retries} failed: {e}"
            )
            if attempt < retries:
                time.sleep(base_delay * attempt)

        except Exception as e:
            last_error = str(e)
            logger.exception(f"Unexpected AI reply error: {e}")
            break

    return ReplyGenerationResult(
        reply=None,
        error=last_error or "ai_reply_failed",
        prompt=prompt,
        model=model_name,
        temperature=model_temperature,
    )


def generate_reply(messages, retries=3, base_delay=2):
    result = generate_reply_result(
        messages,
        retries=retries,
        base_delay=base_delay,
    )
    return result.reply, result.error
