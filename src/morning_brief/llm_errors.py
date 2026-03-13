from __future__ import annotations


class BriefGenerationError(RuntimeError):
    """Raised when the OpenAI briefing path cannot safely complete."""
