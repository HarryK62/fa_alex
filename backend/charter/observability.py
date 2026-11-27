"""Langfuse tracing for this Lambda. Implementation lives in backend/tracing.py."""

import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from tracing import (
    evaluation_input,
    flush_tracing,
    observation,
    observe,
    score_current,
    setup_tracing,
)

__all__ = [
    "evaluation_input",
    "flush_tracing",
    "observation",
    "observe",
    "score_current",
    "setup_tracing",
]
