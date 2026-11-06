"""Structured operational events that deliberately exclude user content."""

from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
from time import perf_counter
from typing import Iterator
from uuid import uuid4


_trace_id: ContextVar[str | None] = ContextVar("opsdiary_trace_id", default=None)
_logger = logging.getLogger("opsdiary.events")


def new_trace_id() -> str:
    return uuid4().hex


@contextmanager
def trace_scope(trace_id: str | None = None) -> Iterator[str]:
    value = trace_id or new_trace_id()
    token = _trace_id.set(value)
    try:
        yield value
    finally:
        _trace_id.reset(token)


@contextmanager
def observed_stage(
    stage: str,
    *,
    incident_id: str | None = None,
    provider: str | None = None,
    metadata: dict | None = None,
) -> Iterator[dict]:
    """Emit one JSON log event with outcome and latency, never input/output text."""
    safe_metadata = metadata if metadata is not None else {}
    started = perf_counter()
    outcome = "ok"
    error_type = None
    try:
        yield safe_metadata
    except Exception as exc:
        outcome = "error"
        error_type = type(exc).__name__
        raise
    finally:
        event = {
            "event": "opsdiary.stage",
            "trace_id": _trace_id.get() or new_trace_id(),
            "stage": stage,
            "outcome": outcome,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        }
        if incident_id:
            event["incident_id"] = incident_id
        if provider:
            event["provider"] = provider
        if error_type:
            event["error_type"] = error_type
        for key in ("request_id", "source", "incident_id", "audio_bytes", "output_bytes"):
            if safe_metadata.get(key) is not None:
                event[key] = safe_metadata[key]
        _logger.info(json.dumps(event, ensure_ascii=True, separators=(",", ":")))
