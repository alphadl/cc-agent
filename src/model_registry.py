"""Model registry: context window sizes and capabilities per model."""
from __future__ import annotations

# (context_window_tokens, supports_thinking)
_MODEL_REGISTRY: dict[str, tuple[int, bool]] = {
    # Anthropic Claude 4.x
    "claude-opus-4-6":              (200_000, True),
    "claude-sonnet-4-6":            (200_000, True),
    "claude-haiku-4-5":             (200_000, False),
    "claude-haiku-4-5-20251001":    (200_000, False),
    # Anthropic Claude 3.x
    "claude-opus-4":                (200_000, True),
    "claude-sonnet-3-5":            (200_000, False),
    "claude-haiku-3":               (200_000, False),
    # OpenAI
    "gpt-4o":                       (128_000, False),
    "gpt-4o-mini":                  (128_000, False),
    "gpt-4-turbo":                  (128_000, False),
    "gpt-4":                        (8_192,   False),
    "o1":                           (200_000, False),
    "o3-mini":                      (200_000, False),
    # Google Gemini
    "gemini-2.0-flash":             (1_048_576, False),
    "gemini-2.0-flash-lite":        (1_048_576, False),
    "gemini-1.5-pro":               (2_097_152, False),
    "gemini-1.5-flash":             (1_048_576, False),
    # Meta Llama
    "llama-3.3-70b-versatile":      (128_000, False),
    "llama-3.1-8b-instant":         (128_000, False),
    # DeepSeek
    "deepseek/deepseek-r1":         (128_000, True),
    "deepseek/deepseek-chat":       (64_000,  False),
    # Qwen
    "qwen/qwen3-6-plus-preview":    (128_000, True),
    "qwen/qwq-32b":                 (128_000, True),
}

_DEFAULT_CONTEXT_WINDOW = 128_000


def _strip_prefix(model: str) -> str:
    prefix = "openrouter/"
    return model[len(prefix):] if model.startswith(prefix) else model


def get_context_window(model: str) -> int:
    """Return context window size for the given model ID."""
    key = _strip_prefix(model)
    # Exact match
    if key in _MODEL_REGISTRY:
        return _MODEL_REGISTRY[key][0]
    # Prefix match (e.g. "claude-sonnet-4-6-20251022" → "claude-sonnet-4-6")
    for registered, (window, _) in _MODEL_REGISTRY.items():
        if key.startswith(registered):
            return window
    return _DEFAULT_CONTEXT_WINDOW


def supports_thinking(model: str) -> bool:
    key = _strip_prefix(model)
    if key in _MODEL_REGISTRY:
        return _MODEL_REGISTRY[key][1]
    for registered, (_, thinking) in _MODEL_REGISTRY.items():
        if key.startswith(registered):
            return thinking
    return False
