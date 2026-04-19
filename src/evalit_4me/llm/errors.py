"""Provider-agnostic LLM error hierarchy.

Adapters wrap vendor-specific exceptions in these so pipeline code can
handle failures uniformly.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for all LLM-layer errors."""


class LLMAuthError(LLMError):
    """Credentials missing or invalid."""


class LLMRateLimitError(LLMError):
    """Upstream rate-limited the request."""


class LLMUnsupportedError(LLMError):
    """Requested capability (e.g., embeddings on Anthropic) is not supported."""
