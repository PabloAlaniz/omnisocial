"""Lo que se informa de un pedido HTTP, y con OpenTelemetry."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from omnisocial.adapters.http.observing import HttpObservation, ObservedTransport, route_of
from omnisocial.adapters.http.transport import HttpResponse, TransportError
from omnisocial.adapters.otel.observer import OtelObserver
from omnisocial.application.observing import Observation, Result
from omnisocial.testing import FakeTransport


@pytest.mark.parametrize(
    ("url", "route"),
    [
        (
            "https://graph.facebook.com/v26.0/106540352242922/messages?access_token=EAAG",
            "/v26.0/:id/messages",
        ),
        # El token de un bot de Telegram va en la ruta.
        ("https://api.telegram.org/bot7001234567:AAHk-AAHk-AAHk-AAHk/sendMessage", "/:id/sendMessage"),
        # La clave de un webhook de Discord también, y no siempre tiene dígitos.
        ("https://discord.com/api/v10/webhooks/111222333/clave-del_webhook", "/api/v10/webhooks/:id/:id"),
        ("https://discord.com/api/v10/webhooks/1/" + "aB" * 34, "/api/v10/webhooks/:id/:id"),
        ("https://discord.com/api/v10/oauth2/token", "/api/v10/oauth2/token"),
        ("https://bsky.social/xrpc/com.atproto.repo.createRecord", "/xrpc/com.atproto.repo.createRecord"),
        ("https://api.linkedin.com/rest/posts/urn%3Ali%3Ashare%3A7001", "/rest/posts/:id"),
        ("https://api.pinterest.com/v5/user_account/analytics", "/v5/user_account/analytics"),
        ("https://ejemplo.com", "/"),
    ],
)
def test_la_ruta_que_se_informa_no_lleva_ids_ni_claves(url: str, route: str) -> None:
    assert route_of(url) == (url.split("/")[2], route)


class Seen:
    def __init__(self) -> None:
        self.requests: list[HttpObservation] = []

    def request(self, observation: HttpObservation) -> None:
        self.requests.append(observation)


async def test_cada_pedido_avisa_con_o_sin_respuesta() -> None:
    inner, seen = FakeTransport(), Seen()
    ticks = iter([0.0, 0.25, 1.0, 1.5, 2.0, 2.0])
    transport = ObservedTransport(inner, seen, network="reddit", timer=lambda: next(ticks))
    url = "https://oauth.reddit.com/api/submit"
    inner.on("POST", url, {"ok": True}, HttpResponse(503, None, "ups"), TransportError("se cortó"))
    assert (await transport.request("POST", url, form={"title": "Hola"})).data == {"ok": True}
    assert (await transport.request("POST", url)).status == 503
    with pytest.raises(TransportError):
        await transport.request("POST", url, headers={"Authorization": "bearer secreto"})
    assert [(s.network, s.method, s.host, s.route, s.status, s.duration) for s in seen.requests] == [
        ("reddit", "POST", "oauth.reddit.com", "/api/submit", 200, 0.25),
        ("reddit", "POST", "oauth.reddit.com", "/api/submit", 503, 0.5),
        ("reddit", "POST", "oauth.reddit.com", "/api/submit", None, 0.0),
    ]
    assert "secreto" not in repr(seen.requests)
    assert inner.calls[0].form == {"title": "Hola"}

    class Broken:
        def request(self, observation: HttpObservation) -> None:
            raise RuntimeError("el observador se rompió")

    inner.on("GET", "https://oauth.reddit.com/api/v1/me", {})
    broken = ObservedTransport(inner, Broken(), network="reddit")
    assert (await broken.request("GET", "https://oauth.reddit.com/api/v1/me")).status == 200


def _otel() -> tuple[OtelObserver, InMemorySpanExporter, InMemoryMetricReader]:
    spans, reader = InMemorySpanExporter(), InMemoryMetricReader()
    tracing = TracerProvider()
    tracing.add_span_processor(SimpleSpanProcessor(spans))
    return OtelObserver(tracer_provider=tracing, meter_provider=MeterProvider([reader])), spans, reader


def _points(reader: InMemoryMetricReader) -> dict[str, list[dict[str, object]]]:
    data = reader.get_metrics_data()
    assert data is not None
    found: dict[str, list[dict[str, object]]] = {}
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                found[metric.name] = [dict(point.attributes or {}) for point in metric.data.data_points]
    return found


def test_con_opentelemetry_cada_llamada_deja_un_tramo_y_una_metrica() -> None:
    observer, spans, reader = _otel()
    observer.operation(Observation("meta", "content", "list_posts", Result.OK, 0.2))
    observer.operation(Observation("meta", "publisher", "publish", Result.ERROR, 1.5, "rate_limited"))
    fine, failed = spans.get_finished_spans()
    assert (fine.name, fine.kind, fine.status.status_code) == (
        "meta content.list_posts",
        SpanKind.INTERNAL,
        StatusCode.UNSET,
    )
    assert fine.end_time is not None
    assert fine.start_time is not None
    assert round((fine.end_time - fine.start_time) / 1e9, 3) == 0.2
    assert (failed.status.status_code, dict(failed.attributes or {})) == (
        StatusCode.ERROR,
        {
            "omnisocial.network": "meta",
            "omnisocial.port": "publisher",
            "omnisocial.operation": "publish",
            "omnisocial.result": "error",
            "error.type": "rate_limited",
        },
    )
    points = _points(reader)["omnisocial.operation.duration"]
    assert {point["omnisocial.operation"] for point in points} == {"list_posts", "publish"}


def test_con_opentelemetry_cada_pedido_deja_un_tramo_y_una_metrica() -> None:
    observer, spans, reader = _otel()
    observer.request(HttpObservation("x", "POST", "api.x.com", "/:id/tweets", 201, 0.1))
    observer.request(HttpObservation("x", "GET", "api.x.com", "/:id/users/me", 429, 0.1))
    observer.request(HttpObservation("x", "GET", "api.x.com", "/:id/users/me", None, 3.0))
    created, limited, lost = spans.get_finished_spans()
    assert (created.name, created.kind, created.status.status_code) == (
        "POST /:id/tweets",
        SpanKind.CLIENT,
        StatusCode.UNSET,
    )
    assert dict(created.attributes or {}) == {
        "omnisocial.network": "x",
        "http.request.method": "POST",
        "server.address": "api.x.com",
        "http.route": "/:id/tweets",
        "http.response.status_code": 201,
    }
    assert (limited.attributes or {})["error.type"] == "429"
    assert (lost.attributes or {})["error.type"] == "no_response"
    assert "http.response.status_code" not in (lost.attributes or {})
    assert len(_points(reader)["omnisocial.http.duration"]) == 3


def test_sin_proveedores_usa_los_globales() -> None:
    OtelObserver().operation(Observation("meta", "content", "list_posts", Result.OK, 0.1))
