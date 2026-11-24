"""Errores del dominio.

Las decisiones de negocio vuelven como resultados tipados (ver `application.results`). Las excepciones
quedan para lo que el código que llama no puede decidir: una red que no responde o que rechaza un token.
"""

from __future__ import annotations

from enum import StrEnum

from omnisocial.domain.provider import Capability, ProviderId


class OmnisocialError(Exception):
    """Base de todos los errores de la librería."""


class ErrorKind(StrEnum):
    """Qué quiso decir la red con un error. Cada red lo declara en su tabla (`domain.spec.ErrorTable`)."""

    TOKEN_DEAD = "token_dead"  # noqa: S105  # es el nombre de la clase de error
    """El token ya no sirve. La conexión queda inválida."""
    MISSING_PERMISSION = "missing_permission"
    """Al token le falta un permiso. La conexión sigue sana."""
    RATE_LIMITED = "rate_limited"
    """Demasiados pedidos en poco tiempo. Se resuelve esperando."""
    QUOTA_EXHAUSTED = "quota_exhausted"
    """Se acabó la cuota o el crédito de la app. No se resuelve esperando unos segundos ni reconectando."""
    INVALID_REQUEST = "invalid_request"
    """El pedido está mal armado. Repetirlo igual da lo mismo."""
    TRANSIENT = "transient"
    """Falla pasajera de la red. Repetir más tarde puede andar."""
    UNKNOWN = "unknown"


class CapabilityNotSupported(OmnisocialError):
    """La red no implementa esa capacidad (por ejemplo, mensajes privados)."""

    def __init__(self, provider: ProviderId, capability: Capability) -> None:
        super().__init__(f"La red '{provider}' no soporta la capacidad '{capability}'.")
        self.provider = provider
        self.capability = capability


class UnknownProvider(OmnisocialError):
    """No hay ninguna red registrada con ese identificador."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"No hay ninguna red registrada como '{provider}'.")
        self.provider = provider


class TokenRejected(OmnisocialError):
    """La red rechazó el token: venció, lo revocaron o ya no es válido.

    No tiene sentido reintentar. Hasta que alguien vuelva a conectar la cuenta la respuesta va a ser la misma.
    """

    def __init__(self, provider: ProviderId, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code


class ProviderError(OmnisocialError):
    """La red respondió con un error que no es de token."""

    def __init__(
        self,
        provider: ProviderId,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        kind: ErrorKind = ErrorKind.UNKNOWN,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.code = code
        self.kind = kind


class PermissionMissing(ProviderError):
    """Al token le falta un permiso para esto. Se resuelve volviendo a conectar con los permisos que faltan.

    Es distinto de que la red no ofrezca la acción: eso no se arregla pidiendo nada.
    """


class RateLimited(ProviderError):
    """La red pide bajar el ritmo. `retry_after` son los segundos que pidió esperar, si lo dijo."""

    def __init__(
        self,
        provider: ProviderId,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(provider, message, status=status, code=code, kind=ErrorKind.RATE_LIMITED)
        self.retry_after = retry_after


class NotPublished(ProviderError):
    """Publicar falló antes de que la red creara nada: con certeza no salió, y se puede reintentar.

    Es lo que lanza un adaptador cuando se corta la subida de un archivo. Sin esto, un error a mitad de
    camino dejaría la publicación en duda.
    """


class QuotaExhausted(ProviderError):
    """Se acabó la cuota o el crédito de la app en la red. El token no tiene la culpa."""
