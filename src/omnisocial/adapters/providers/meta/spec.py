"""La descripción de Meta: capacidades, tipos de activo y qué quiere decir cada código de error."""

from __future__ import annotations

from omnisocial.adapters.providers.meta.config import FACEBOOK_PAGE, INSTAGRAM, INSTAGRAM_ACCOUNT, META
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits
from omnisocial.domain.spec import ErrorTable, NetworkSpec

PAGE_CAPABILITIES = frozenset(
    {
        Capability.CONTENT,
        Capability.COMMENTS,
        Capability.MESSAGING,
        Capability.INSIGHTS,
        Capability.WEBHOOKS,
        Capability.PUBLISHING,
    }
)
INSTAGRAM_CAPABILITIES = PAGE_CAPABILITIES

# Códigos que quieren decir "este token ya no sirve".
#   190: token vencido, revocado o inválido.
#   102: alias viejo de la misma condición (sesión inválida).
# El 2500 queda afuera a propósito: Meta también lo devuelve ante pedidos mal armados.
TOKEN_DEAD_CODES = frozenset({190, 102})

# 10: a la app le falta el permiso. 200 a 299: al token le falta un permiso (200 en general, 2xx uno puntual).
PERMISSION_CODES = frozenset({10, *range(200, 300)})

# Límites de uso. Meta los cuenta por ventana móvil: se resuelven esperando.
#   4: de la app.  17: de la persona.  32: de la página.  613: uno propio del endpoint.
#   341: tope de la app.  80001: páginas.  80002: Instagram.  80006: Messenger.
RATE_LIMIT_CODES = frozenset({4, 17, 32, 341, 613, 80001, 80002, 80006})

# 1: error desconocido del lado de Meta.  2: servicio no disponible por un momento.
TRANSIENT_CODES = frozenset({1, 2})

# 100: parámetro inválido.  352: formato de video no soportado.  9004: Instagram no pudo descargar el medio.
# 36000, 36001 y 36003: la imagen pesa demasiado, tiene un formato o una proporción que Instagram no acepta.
INVALID_REQUEST_CODES = frozenset({100, 352, 9004, 36000, 36001, 36003})

# Con subcódigo, cuando el código solo no alcanza.
#   9/2207042: se llegó al tope de publicaciones por API de Instagram en 24 horas.
PRECISE_CODES = {"9/2207042": ErrorKind.QUOTA_EXHAUSTED}

PAGE_LIMITS = PublishLimits(
    max_text=63206, max_images=10, max_videos=1, link=True, first_comment=True, delete=True
)
# Instagram siempre pide al menos un medio. Borrar por API existe, pero pide otro permiso
# (`instagram_manage_contents`) y todavía no se ofrece.
INSTAGRAM_LIMITS = PublishLimits(
    max_text=2200,
    max_images=20,
    max_videos=20,
    max_media=20,
    mix_media=True,
    media_required=True,
    first_comment=True,
)


def _codes() -> dict[str, ErrorKind]:
    groups = {
        ErrorKind.TOKEN_DEAD: TOKEN_DEAD_CODES,
        ErrorKind.MISSING_PERMISSION: PERMISSION_CODES,
        ErrorKind.RATE_LIMITED: RATE_LIMIT_CODES,
        ErrorKind.TRANSIENT: TRANSIENT_CODES,
        ErrorKind.INVALID_REQUEST: INVALID_REQUEST_CODES,
    }
    return {str(code): kind for kind, codes in groups.items() for code in codes} | PRECISE_CODES


ERRORS = ErrorTable(codes=_codes())

# Instagram con login propio: la misma cuenta profesional, sin pasar por una página de Facebook. No tiene
# mensajes ni webhooks integrados todavía, y la API no deja ver perfiles ajenos con este login.
INSTAGRAM_LOGIN_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.INSIGHTS, Capability.PUBLISHING}
)
INSTAGRAM_SPEC = NetworkSpec(
    id=INSTAGRAM,
    name="Instagram (login propio)",
    capabilities=frozenset({Capability.LOGIN, Capability.ASSETS}) | INSTAGRAM_LOGIN_CAPABILITIES,
    assets={INSTAGRAM_ACCOUNT: INSTAGRAM_LOGIN_CAPABILITIES},
    errors=ERRORS,
    docs="docs/instagram.md",
    publishing={INSTAGRAM_ACCOUNT: INSTAGRAM_LIMITS},
)

EXTRA_SPECS = (INSTAGRAM_SPEC,)
"""Otras redes que viven en este paquete porque comparten el cliente y los adaptadores."""

SPEC = NetworkSpec(
    id=META,
    name="Meta",
    capabilities=frozenset(Capability),
    assets={FACEBOOK_PAGE: PAGE_CAPABILITIES, INSTAGRAM_ACCOUNT: INSTAGRAM_CAPABILITIES},
    errors=ERRORS,
    docs="docs/meta.md",
    publishing={FACEBOOK_PAGE: PAGE_LIMITS, INSTAGRAM_ACCOUNT: INSTAGRAM_LIMITS},
)
