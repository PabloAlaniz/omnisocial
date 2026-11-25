"""Qué pasa con cada llamada a una red: cuál, a qué operación, cómo salió y cuánto tardó.

Se observa en el borde con la red, que es donde se gasta el tiempo y donde fallan las cosas. Una negativa
que decide el núcleo sin llamar a nadie (un borrador que no entra) no es una llamada y no aparece.

Una observación nunca lleva un token, un secreto ni el contenido de lo que se mandó: solo nombres.
"""

from __future__ import annotations

import contextlib
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import Protocol

from omnisocial.application.registry import Provider
from omnisocial.domain.errors import (
    NotPublished,
    OmnisocialError,
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    TokenRejected,
)

Timer = Callable[[], float]
"""Un reloj que solo avanza, en segundos. Sirve para medir cuánto tardó algo."""


class Result(StrEnum):
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Observation:
    provider: str
    port: str
    """Qué parte de la red: `content`, `comments`, `publisher`, `oauth`…"""
    operation: str
    """El método del puerto: `list_posts`, `publish`, `refresh`…"""
    result: Result
    duration: float
    """Segundos."""
    error: str | None = None
    """Si falló, qué clase de error: `token_dead`, `rate_limited`, `missing_permission`, `transient`… o
    el nombre de la excepción si no vino de la red."""


class Observer(Protocol):
    def operation(self, observation: Observation) -> None:
        """Se llama después de cada llamada a una red. No debe tardar ni lanzar: si lanza, se ignora."""
        ...


# Estas clases dicen qué pasó aunque quien las lanzó no haya anotado la clase de error.
_BY_CLASS: dict[type[ProviderError], str] = {
    PermissionMissing: "missing_permission",
    QuotaExhausted: "quota_exhausted",
    NotPublished: "not_published",
}


def error_name(error: BaseException) -> str:
    """El nombre con que se cuenta un error. Nunca su mensaje, que puede traer datos de la cuenta."""
    if isinstance(error, TokenRejected):
        return "token_dead"
    for kind, name in _BY_CLASS.items():
        if isinstance(error, kind):
            return name
    if isinstance(error, ProviderError):
        return str(error.kind)
    if isinstance(error, OmnisocialError):
        return type(error).__name__
    return "unexpected"


def _tell(observer: Observer, observation: Observation) -> None:
    # Un observador roto no puede romper una publicación.
    with contextlib.suppress(Exception):
        observer.operation(observation)


class _Observed:
    """Un adaptador que avisa de cada llamada. Lo que no es una llamada a la red pasa sin tocar."""

    def __init__(self, inner: object, *, provider: str, port: str, observer: Observer, timer: Timer) -> None:
        self._inner = inner
        self._provider = provider
        self._port = port
        self._observer = observer
        self._timer = timer

    def __getattr__(self, name: str) -> object:
        attribute = getattr(self._inner, name)
        if not inspect.iscoroutinefunction(attribute):
            return attribute
        call: Callable[..., Awaitable[object]] = attribute

        async def observed(*args: object, **kwargs: object) -> object:
            started = self._timer()
            error: str | None = None
            try:
                return await call(*args, **kwargs)
            except BaseException as raised:
                error = error_name(raised)
                raise
            finally:
                _tell(
                    self._observer,
                    Observation(
                        provider=self._provider,
                        port=self._port,
                        operation=name,
                        result=Result.OK if error is None else Result.ERROR,
                        duration=self._timer() - started,
                        error=error,
                    ),
                )

        return observed


_NOT_PORTS = frozenset({"id", "spec"})


def observed(provider: Provider, observer: Observer, timer: Timer) -> Provider:
    """El mismo proveedor, avisando de cada llamada a la red."""
    wrapped = {
        field.name: _Observed(
            component, provider=str(provider.id), port=field.name, observer=observer, timer=timer
        )
        for field in fields(provider)
        if field.name not in _NOT_PORTS and (component := getattr(provider, field.name)) is not None
    }
    return replace(provider, **wrapped)  # type: ignore[arg-type]
