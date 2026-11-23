"""Errores del dominio.

Las decisiones de negocio vuelven como resultados tipados (ver `application.results`). Las excepciones
quedan para lo que el código que llama no puede decidir: una red que no responde o que rechaza un token.
"""

from __future__ import annotations

from omnisocial.domain.provider import Capability, ProviderId


class OmnisocialError(Exception):
    """Base de todos los errores de la librería."""


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
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.code = code


class PermissionMissing(ProviderError):
    """Al token le falta un permiso para esto. Se resuelve volviendo a conectar con los permisos que faltan.

    Es distinto de que la red no ofrezca la acción: eso no se arregla pidiendo nada.
    """
