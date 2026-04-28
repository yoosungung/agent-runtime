from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(service_name: str, otlp_endpoint: str | None) -> None:
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
        )
    trace.set_tracer_provider(provider)


def configure_metrics(service_name: str, otlp_endpoint: str | None) -> None:
    """Configure the global MeterProvider.

    If *otlp_endpoint* is set, attaches a PeriodicExportingMetricReader that
    pushes metrics to the OTLP collector at that address.
    """
    resource = Resource.create({"service.name": service_name})
    readers = []
    if otlp_endpoint:
        exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
        readers.append(PeriodicExportingMetricReader(exporter))
    provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(provider)


def get_meter(name: str) -> metrics.Meter:
    """Return a Meter for *name* from the global MeterProvider."""
    return metrics.get_meter(name)
