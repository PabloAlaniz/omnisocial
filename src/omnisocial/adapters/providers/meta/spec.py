"""La descripción de Meta: capacidades, tipos de activo y qué quiere decir cada código de error."""

from __future__ import annotations

from omnisocial.adapters.providers.meta.config import FACEBOOK_PAGE, INSTAGRAM_ACCOUNT, META
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.spec import ErrorTable, NetworkSpec

PAGE_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.MESSAGING, Capability.INSIGHTS, Capability.WEBHOOKS}
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

INVALID_REQUEST_CODES = frozenset({100})


def _codes() -> dict[str, ErrorKind]:
    groups = {
        ErrorKind.TOKEN_DEAD: TOKEN_DEAD_CODES,
        ErrorKind.MISSING_PERMISSION: PERMISSION_CODES,
        ErrorKind.RATE_LIMITED: RATE_LIMIT_CODES,
        ErrorKind.TRANSIENT: TRANSIENT_CODES,
        ErrorKind.INVALID_REQUEST: INVALID_REQUEST_CODES,
    }
    return {str(code): kind for kind, codes in groups.items() for code in codes}


ERRORS = ErrorTable(codes=_codes())

SPEC = NetworkSpec(
    id=META,
    name="Meta",
    capabilities=frozenset(Capability),
    assets={FACEBOOK_PAGE: PAGE_CAPABILITIES, INSTAGRAM_ACCOUNT: INSTAGRAM_CAPABILITIES},
    errors=ERRORS,
    docs="docs/meta.md",
)
