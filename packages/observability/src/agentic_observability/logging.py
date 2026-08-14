"""Optional log correlation helpers; nothing installs this filter automatically."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from opentelemetry import trace

from .attributes import safe_log_fields


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        record.trace_id = f"{context.trace_id:032x}" if context.is_valid else None
        record.span_id = f"{context.span_id:016x}" if context.is_valid else None
        fields = getattr(record, "telemetry_fields", None)
        if fields is not None:
            if not isinstance(fields, Mapping):
                raise ValueError("telemetry_fields must be a mapping")
            record.telemetry_fields = safe_log_fields(fields)
        return True


def install_trace_context_filter(handlers: Iterable[logging.Handler]) -> None:
    for handler in handlers:
        if not any(
            isinstance(filter_, TraceContextFilter) for filter_ in handler.filters
        ):
            handler.addFilter(TraceContextFilter())
