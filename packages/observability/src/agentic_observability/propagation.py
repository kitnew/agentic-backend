"""W3C Trace Context helpers without baggage."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Link, SpanKind, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()
TRACE_CONTEXT_FIELDS = frozenset({"traceparent", "tracestate"})


def inject_trace_context(
    carrier: MutableMapping[str, str], context: Context | None = None
) -> None:
    _PROPAGATOR.inject(carrier, context=context)


def extract_trace_context(carrier: Mapping[str, str]) -> Context:
    return _PROPAGATOR.extract(carrier)


def trace_context_fields(carrier: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value for name in TRACE_CONTEXT_FIELDS if (value := carrier.get(name))
    }


@contextmanager
def process_message_span(
    tracer: Tracer | None,
    carrier: Mapping[str, str],
    *,
    stream: str,
    group: str,
    message_id: str,
) -> Iterator[None]:
    if tracer is None:
        yield
        return
    source = trace.get_current_span(extract_trace_context(carrier)).get_span_context()
    links = [Link(source)] if source.is_valid else []
    with tracer.start_as_current_span(
        "messaging.process",
        context=Context(),
        kind=SpanKind.CONSUMER,
        links=links,
        attributes={
            "messaging.system": "redis",
            "messaging.operation": "process",
            "messaging.destination.name": stream,
            "messaging.message.id": message_id,
            "messaging.consumer.group.name": group,
        },
    ):
        yield
