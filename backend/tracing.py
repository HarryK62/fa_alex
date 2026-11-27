"""Langfuse tracing for Alex agents.

The OpenAI Agents SDK is instrumented with OpenInference and exported through
the Langfuse Python SDK. Model name, token usage, tool calls, and agent spans
are captured by that integration. This module adds the trace name, user,
session, and a glanceable input/output around each agent run.

Tracing is skipped when Langfuse credentials are absent, so local runs and
unconfigured deployments keep working.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger()

_ready = False
_auth_checked = False

_EMAIL = re.compile(r"\b[\w.-]+?@[\w.-]+?\.\w+?\b")
_PHONE = re.compile(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_SECRET = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{10,}|pk-lf-[A-Za-z0-9_\-]+|sk-lf-[A-Za-z0-9_\-]+|AKIA[0-9A-Z]{16})\b"
)


class Span:
    """Update handle for the active Langfuse observation. No-op when tracing is off."""

    def __init__(self, observation: Any = None) -> None:
        self._observation = observation

    def update(self, **kwargs: Any) -> None:
        if self._observation is not None:
            self._observation.update(**kwargs)


def _mask_string(value: str) -> str:
    value = _EMAIL.sub("[REDACTED EMAIL]", value)
    value = _PHONE.sub("[REDACTED PHONE]", value)
    value = _CARD.sub("[REDACTED CREDIT CARD]", value)
    value = _SECRET.sub("[REDACTED SECRET]", value)
    return value


def _mask_attribute(value: Any) -> Any:
    if isinstance(value, str):
        masked = _mask_string(value)
        return masked if masked != value else None
    if isinstance(value, (list, tuple)) and value and all(isinstance(item, str) for item in value):
        masked_items = [_mask_string(item) for item in value]
        if masked_items == list(value):
            return None
        return type(value)(masked_items)
    return None


# Python SDK v5 stores these as JSON-encoded strings, including on OpenInference spans.
_METADATA_PREFIXES = (
    "langfuse.trace.metadata.",
    "langfuse.observation.metadata.",
)


def _mask_json_value(value: Any) -> Any:
    """Return a masked copy, or None when the decoded metadata value is unchanged."""
    if isinstance(value, str):
        masked = _mask_string(value)
        return masked if masked != value else None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        masked_items = [_mask_string(item) for item in value]
        if masked_items == value:
            return None
        return masked_items
    return None


def _masked_attribute(key: str, value: Any) -> Any:
    """Mask one exported attribute.

    Metadata attributes are JSON-encoded in SDK v5. Decode them before masking
    and write replacements with json.dumps. A raw string from an older upstream
    service is masked the same way. Prompt and completion attributes stay raw
    OpenTelemetry strings.
    """
    if key.startswith(_METADATA_PREFIXES):
        if not isinstance(value, str):
            return None
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = value
        masked = _mask_json_value(decoded)
        if masked is None:
            return None
        return json.dumps(masked)
    return _mask_attribute(value)


def mask_otel_spans(*, params: Any) -> Any:
    """Redact secrets and contact details from exported OpenTelemetry attributes.

    OpenInference stores prompts on raw span attributes, so masking has to run
    at export time. A failure returns the batch unchanged instead of dropping it.
    """
    try:
        from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

        patches = {}
        for identifier, span in params.spans.items():
            replacements = {}
            for key, value in span.attributes.items():
                masked = _masked_attribute(key, value)
                if masked is not None:
                    replacements[key] = masked
            if replacements:
                patches[identifier] = OtelSpanPatch(set_attributes=replacements)
        if not patches:
            return None
        return MaskOtelSpansResult(span_patches=patches)
    except Exception:
        logger.exception("Langfuse masking failed; exporting this batch unchanged")
        return None


def _sync_endpoint() -> None:
    """The Python SDK reads LANGFUSE_BASE_URL. Terraform and older docs set LANGFUSE_HOST."""
    host = os.getenv("LANGFUSE_HOST")
    base_url = os.getenv("LANGFUSE_BASE_URL")
    if host and not base_url:
        os.environ["LANGFUSE_BASE_URL"] = host
    elif base_url and not host:
        os.environ["LANGFUSE_HOST"] = base_url


def tracing_environment() -> str:
    configured = os.getenv("LANGFUSE_TRACING_ENVIRONMENT")
    if configured:
        return configured
    return "development"


def setup_tracing() -> bool:
    """Instrument the Agents SDK once. Returns False when Langfuse is not configured."""
    global _ready, _auth_checked
    if _ready:
        return True

    _sync_endpoint()
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        logger.info("Langfuse credentials are not set; tracing is skipped")
        return False

    try:
        from langfuse import Langfuse
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

        # Instrument before the first agent run. The Langfuse client then
        # exports those OpenTelemetry spans, including LiteLLM generations.
        # exclusive_processor=False keeps the Agents SDK's own exporter, so
        # traces also reach the OpenAI dashboard. OpenInference 2.8+ defaults
        # to True, which replaces that exporter and sends traces to Langfuse only.
        OpenAIAgentsInstrumentor().instrument(exclusive_processor=False)
        client = Langfuse(
            mask_otel_spans=mask_otel_spans,
            environment=tracing_environment(),
        )
        if not _auth_checked:
            _auth_checked = True
            try:
                logger.info("Langfuse auth check passed: %s", client.auth_check())
            except Exception as auth_error:
                logger.warning("Langfuse auth check failed: %s", auth_error)
        _ready = True
        logger.info("Langfuse tracing enabled for environment %s", tracing_environment())
        return True
    except Exception as exc:
        logger.error("Langfuse setup failed: %s", exc)
        return False


def _metadata(feature: str, metadata: Optional[dict[str, Any]]) -> Optional[dict[str, str]]:
    merged: dict[str, Any] = {"feature": feature}
    if metadata:
        merged.update(metadata)
    safe: dict[str, str] = {}
    for key, value in merged.items():
        if value is None:
            continue
        text = str(value)
        # SDK v5 JSON-encodes metadata before applying the 200-character limit,
        # so a string can be at most 198 characters.
        if len(text) > 198:
            continue
        safe[str(key)] = text
    return safe or None


def _tags(feature: str, tags: Optional[list[str]]) -> list[str]:
    result: list[str] = []
    for tag in (feature, *(tags or [])):
        if tag and tag not in result:
            result.append(tag)
    return result


def _propagate_attributes(
    *,
    trace_name: str,
    feature: str,
    user_id: Optional[str],
    session_id: Optional[str],
    metadata: Optional[dict[str, Any]],
    tags: Optional[list[str]],
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "trace_name": trace_name,
        "tags": _tags(feature, tags),
        "environment": tracing_environment(),
    }
    if user_id:
        attributes["user_id"] = user_id
    if session_id:
        attributes["session_id"] = session_id
    safe_metadata = _metadata(feature, metadata)
    if safe_metadata:
        attributes["metadata"] = safe_metadata
    return attributes


@contextmanager
def observe(
    *,
    trace_name: str,
    feature: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    input: Any = None,
    metadata: Optional[dict[str, Any]] = None,
    tags: Optional[list[str]] = None,
) -> Iterator[Span]:
    """Root agent observation for one unit of work.

    Each Lambda invocation is its own trace. Pass the analysis job id as
    session_id so the planner, tagger, reporter, charter, and retirement
    traces group together in the Langfuse sessions view.

    Propagation is opened before the root observation. The root and every
    child created inside it, including cost-bearing generations, then carry
    the session id, user id, tags, and metadata used for filtering and cost.
    """
    if not setup_tracing():
        yield Span()
        return

    from langfuse import get_client, propagate_attributes

    langfuse = get_client()
    attributes = _propagate_attributes(
        trace_name=trace_name,
        feature=feature,
        user_id=user_id,
        session_id=session_id,
        metadata=metadata,
        tags=tags,
    )
    started = False
    try:
        # Scope first, then the root observation, so the root itself is created
        # inside the propagated context rather than updated after the fact.
        with propagate_attributes(**attributes):
            with langfuse.start_as_current_observation(
                as_type="agent",
                name=trace_name,
                input=input,
                metadata=attributes.get("metadata"),
            ) as root:
                started = True
                try:
                    yield Span(root)
                except Exception as exc:
                    root.update(level="ERROR", status_message=str(exc)[:500])
                    raise
    except Exception:
        if started:
            raise
        logger.exception("Langfuse trace %s could not be started", trace_name)
        yield Span()
    finally:
        if started:
            flush_tracing()


@contextmanager
def observation(
    *,
    name: str,
    as_type: str = "span",
    input: Any = None,
) -> Iterator[Span]:
    """Child observation nested under the active trace. No-op when tracing is off."""
    if not _ready:
        yield Span()
        return

    from langfuse import get_client

    langfuse = get_client()
    started = False
    try:
        with langfuse.start_as_current_observation(
            as_type=as_type,
            name=name,
            input=input,
        ) as current:
            started = True
            try:
                yield Span(current)
            except Exception as exc:
                current.update(level="ERROR", status_message=str(exc)[:500])
                raise
    except Exception:
        if started:
            raise
        logger.exception("Langfuse observation %s could not be started", name)
        yield Span()


def evaluation_input(
    *,
    job_id: str,
    instructions: str,
    task: str,
    report: str,
) -> dict[str, str]:
    """Values for the report-quality observation.

    Langfuse v4 observation evaluators read one observation. They cannot see
    the writer generation or the root span, so the instructions, task, and
    report have to sit on ``evaluate-report`` next to the score.
    """
    return {
        "job_id": job_id,
        "instructions": instructions,
        "task": task,
        "report": report,
    }


def score_current(
    *,
    name: str,
    value: float | str,
    comment: Optional[str] = None,
    data_type: str = "NUMERIC",
) -> None:
    """Attach a score to the observation that is active right now."""
    if not _ready:
        return

    from langfuse import get_client

    langfuse = get_client()
    trace_id = langfuse.get_current_trace_id()
    if not trace_id:
        logger.warning("No active Langfuse trace; score %s was not recorded", name)
        return
    langfuse.create_score(
        name=name,
        value=value,
        trace_id=trace_id,
        observation_id=langfuse.get_current_observation_id(),
        data_type=data_type,
        comment=comment,
    )


def flush_tracing() -> None:
    """Block until queued spans and scores are sent. Required in Lambda.

    Flushes both the Agents SDK exporter (OpenAI traces dashboard) and
    Langfuse. Lambda freezes the process once the handler returns, so
    anything still queued in a background exporter would be lost.
    """
    try:
        from agents.tracing import get_trace_provider

        get_trace_provider().force_flush()
    except Exception as exc:
        logger.error("Failed to flush OpenAI Agents traces: %s", exc)

    if not _ready:
        return

    from langfuse import get_client

    try:
        get_client().flush()
    except Exception as exc:
        logger.error("Failed to flush Langfuse traces: %s", exc)
