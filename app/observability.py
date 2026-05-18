from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
_tracer: Any | None = None


def configure_observability() -> None:
    settings = get_settings()
    if not settings.enable_opentelemetry:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception as exc:
        logger.warning("OpenTelemetry is enabled but dependencies are unavailable: %s", exc)
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    exporter_kwargs = {"endpoint": settings.otel_exporter_otlp_endpoint} if settings.otel_exporter_otlp_endpoint else {}
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)))
    trace.set_tracer_provider(provider)
    global _tracer
    _tracer = trace.get_tracer(settings.otel_service_name)


def request_span(name: str, attributes: dict[str, Any] | None = None):
    if _tracer is None:
        return nullcontext()
    return _tracer.start_as_current_span(name, attributes=attributes or {})
