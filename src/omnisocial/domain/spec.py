"""La descripción de una red: lo que se puede decir con datos, sin escribir código.

Un adaptador declara acá sus URLs de OAuth, qué significa cada error y qué puede hacer cada tipo de activo.
Con eso el núcleo arma el OAuth estándar, clasifica los errores igual en todas las redes y genera la matriz
de capacidades. La clase propia queda para lo que la red hace distinto.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from omnisocial.domain.errors import (
    ErrorKind,
    OmnisocialError,
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.lookup import LookupSpec
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.publishing import PublishLimits

_TOO_MANY_REQUESTS = 429
_SERVER_ERROR = 500


@dataclass(frozen=True, slots=True)
class ErrorTable:
    """Qué quiere decir cada error de una red.

    Manda el código propio de la red; si no está en la tabla, el estado HTTP. Un 401 o un 403 sin código
    conocido **no** es un token muerto: solo invalidan la conexión los códigos que la red documenta así.
    """

    codes: Mapping[str, ErrorKind] = field(default_factory=dict)
    statuses: Mapping[int, ErrorKind] = field(default_factory=dict)

    def classify(self, *, status: int | None, code: str | None) -> ErrorKind:
        if code is not None and code in self.codes:
            return self.codes[code]
        if status is None:
            return ErrorKind.UNKNOWN
        if status in self.statuses:
            return self.statuses[status]
        if status == _TOO_MANY_REQUESTS:
            return ErrorKind.RATE_LIMITED
        return ErrorKind.TRANSIENT if status >= _SERVER_ERROR else ErrorKind.UNKNOWN

    def error(
        self,
        provider: ProviderId,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        retry_after: float | None = None,
    ) -> OmnisocialError:
        """La excepción que corresponde a ese error. Quien llama la lanza."""
        kind = self.classify(status=status, code=code)
        if kind is ErrorKind.TOKEN_DEAD:
            return TokenRejected(provider, message, code=code)
        if kind is ErrorKind.RATE_LIMITED:
            return RateLimited(provider, message, status=status, code=code, retry_after=retry_after)
        subclass = _SUBCLASS.get(kind, ProviderError)
        return subclass(provider, message, status=status, code=code, kind=kind)


_SUBCLASS: Mapping[ErrorKind, type[ProviderError]] = {
    ErrorKind.MISSING_PERMISSION: PermissionMissing,
    ErrorKind.QUOTA_EXHAUSTED: QuotaExhausted,
}


@dataclass(frozen=True, slots=True)
class OAuthSpec:
    """OAuth 2.0 con código de autorización, y en qué se aparta la red del estándar."""

    authorize_url: str
    token_url: str
    revoke_url: str | None = None
    scope_separator: str = " "
    pkce: bool = True
    client_id_param: str = "client_id"
    """Algunas redes le cambian el nombre (`client_key`)."""
    client_secret_param: str = "client_secret"  # noqa: S105  # es el nombre del parámetro
    authorize_params: Mapping[str, str] = field(default_factory=dict)
    """Parámetros fijos que la red pide en la URL de autorización (`access_type=offline`, por ejemplo)."""
    client_auth_basic: bool = False
    """La app se identifica con una cabecera `Authorization: Basic` y no manda su clave ni su
    secreto en el cuerpo."""
    revoke_with_credentials: bool = True
    """Si la revocación lleva las credenciales de la app, además del token."""
    refresh_rotates: bool = False
    """Cada renovación devuelve un token de renovación nuevo y el anterior deja de servir."""


class SupportLevel(StrEnum):
    """Cuánto respaldo tiene una red. Lo muestra la matriz del README."""

    VERIFIED = "verified"
    """Se prueba seguido contra la API real, con una cuenta de prueba, y tiene quién la mantenga."""
    COMMUNITY = "community"
    """Alguien la usa en producción y avisa cuando se rompe, pero no se prueba sola contra la API real."""
    EXPERIMENTAL = "experimental"
    """Escrita contra la documentación y probada con respuestas simuladas. Nadie confirmó que funcione
    con la API real."""


@dataclass(frozen=True, slots=True)
class ApiPin:
    """La versión de la API de la red contra la que está escrito el adaptador."""

    version: str
    reviewed: date
    """La última vez que alguien comparó el adaptador con la documentación de esa versión."""
    sunset: date | None = None
    """Cuándo la red la retira, si lo anunció."""
    changelog: str | None = None
    """Dónde anuncia la red sus versiones y sus retiros."""


@dataclass(frozen=True, slots=True)
class Pace:
    """El ritmo que la red tolera de una misma app. Lo respeta `PacedTransport`, dentro de un proceso."""

    max_concurrent: int | None = None
    """Cuántos pedidos pueden estar en curso a la vez. `None`: sin tope."""
    min_interval: float = 0.0
    """Segundos entre el comienzo de un pedido y el del siguiente."""

    def __post_init__(self) -> None:
        if self.max_concurrent is not None and self.max_concurrent < 1:
            raise ValueError("Hace falta dejar pasar al menos un pedido a la vez.")
        if self.min_interval < 0:
            raise ValueError("El intervalo entre pedidos no puede ser negativo.")


@dataclass(frozen=True, slots=True)
class NetworkSpec:
    id: ProviderId
    name: str
    """Como se la nombra en la documentación: `TikTok`, `Meta`."""
    capabilities: frozenset[Capability]
    """Todas las que la red ofrece con la configuración completa."""
    assets: Mapping[str, frozenset[Capability]] = field(default_factory=dict)
    """Qué habilita cada tipo de activo."""
    errors: ErrorTable = field(default_factory=ErrorTable)
    oauth: OAuthSpec | None = None
    """Solo si el OAuth de la red es el estándar. Si no, la red trae su propio `OAuthClient`."""
    docs: str | None = None
    """La página de la red, relativa a la raíz del repositorio."""
    publishing: Mapping[str, PublishLimits] = field(default_factory=dict)
    """Qué acepta cada tipo de activo al publicar."""
    lookups: Mapping[str, tuple[LookupSpec, ...]] = field(default_factory=dict)
    """Qué consultas auxiliares ofrece cada tipo de activo (tableros, comunidades, etiquetas)."""
    asset_comments: frozenset[str] = frozenset()
    """Los tipos de activo cuyos comentarios son del activo y no de una publicación (las reseñas de una
    sede): se piden una vez, sin recorrer publicaciones."""
    pace: Pace | None = None
    """El ritmo que la red tolera. `None`: no declara uno."""
    support: SupportLevel = SupportLevel.EXPERIMENTAL
    api: ApiPin | None = None
    """La versión de la API que usa el adaptador. `None`: la elige quien configura, o la red no tiene."""

    def __post_init__(self) -> None:
        for kind, capabilities in self.assets.items():
            extra = capabilities - self.capabilities
            if extra:
                names = ", ".join(sorted(extra))
                raise ValueError(f"El activo '{kind}' declara capacidades que la red no tiene: {names}.")
            if (Capability.PUBLISHING in capabilities) != (kind in self.publishing):
                raise ValueError(f"El activo '{kind}' publica si y solo si declara sus límites.")
        for kind, lookups in self.lookups.items():
            if kind not in self.assets:
                raise ValueError(f"Hay consultas para '{kind}', que no es un tipo de activo de la red.")
            declared = [lookup.name for lookup in lookups]
            if len(declared) != len(set(declared)):
                raise ValueError(f"El activo '{kind}' repite el nombre de una consulta.")
            if any(lookup.parent is not None and lookup.parent not in declared for lookup in lookups):
                raise ValueError(f"Una consulta de '{kind}' depende de otra que no está declarada.")
