"""Trazas y métricas de OpenTelemetry a partir de lo que se observa.

Cada llamada a una red y cada pedido HTTP dejan un tramo y dos métricas: una cuenta y una duración. Los
atributos son nombres (la red, la operación, la clase de error, la ruta sin ids): nunca un token, un
mensaje de error ni el contenido de lo que se mandó.

Los tramos se crean cuando la llamada ya terminó, con su comienzo y su fin: no envuelven la llamada, así
que no son padres de los tramos que cree el cliente HTTP por su cuenta.
"""

from __future__ import annotations

import time

from opentelemetry import metrics, trace
from opentelemetry.metrics import MeterProvider
from opentelemetry.trace import SpanKind, Status, StatusCode, TracerProvider
from typing_extensions import override

from omnisocial.adapters.http.observing import HttpObservation, HttpObserver
from omnisocial.application.observing import Observation, Observer, Result

NAME = "omnisocial"
_NANOS = 1_000_000_000
_ERROR = 400


class OtelObserver(Observer, HttpObserver):
    """Sirve para `Omnisocial.build(observer=...)` y para `ObservedTransport(..., observer)`."""

    def __init__(
        self, *, tracer_provider: TracerProvider | None = None, meter_provider: MeterProvider | None = None
    ) -> None:
        """Sin proveedores, usa los globales de OpenTelemetry."""
        self._tracer = trace.get_tracer(NAME, tracer_provider=tracer_provider)
        meter = metrics.get_meter(NAME, meter_provider=meter_provider)
        self._operations = meter.create_histogram(
            "omnisocial.operation.duration", unit="s", description="Cuánto tarda cada llamada a una red."
        )
        self._requests = meter.create_histogram(
            "omnisocial.http.duration", unit="s", description="Cuánto tarda cada pedido HTTP a una red."
        )

    def _span(self, name: str, kind: SpanKind, duration: float, attributes: dict[str, str | int]) -> None:
        end = time.time_ns()  # la hora de un tramo es la del reloj de pared, no la de la app
        span = self._tracer.start_span(
            name, kind=kind, start_time=end - int(duration * _NANOS), attributes=attributes
        )
        if "error.type" in attributes:
            span.set_status(Status(StatusCode.ERROR))
        span.end(end_time=end)

    @override
    def operation(self, observation: Observation) -> None:
        attributes: dict[str, str | int] = {
            "omnisocial.network": observation.provider,
            "omnisocial.port": observation.port,
            "omnisocial.operation": observation.operation,
            "omnisocial.result": str(observation.result),
        }
        if observation.result is Result.ERROR:
            attributes["error.type"] = observation.error or "unexpected"
        self._operations.record(observation.duration, attributes)
        name = f"{observation.provider} {observation.port}.{observation.operation}"
        self._span(name, SpanKind.INTERNAL, observation.duration, attributes)

    @override
    def request(self, observation: HttpObservation) -> None:
        attributes: dict[str, str | int] = {
            "omnisocial.network": observation.network,
            "http.request.method": observation.method,
            "server.address": observation.host,
            "http.route": observation.route,
        }
        if observation.status is not None:
            attributes["http.response.status_code"] = observation.status
        if observation.status is None or observation.status >= _ERROR:
            attributes["error.type"] = str(observation.status) if observation.status else "no_response"
        self._requests.record(observation.duration, attributes)
        name = f"{observation.method} {observation.route}"
        self._span(name, SpanKind.CLIENT, observation.duration, attributes)
