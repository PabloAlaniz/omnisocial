"""La descripción de Threads: sus capacidades, sus límites y qué quiere decir cada error."""

from __future__ import annotations

from omnisocial.adapters.providers.threads.config import THREADS, THREADS_ACCOUNT, ThreadsOptions
from omnisocial.domain.errors import ErrorKind
from omnisocial.domain.provider import Capability
from omnisocial.domain.publishing import PublishLimits, TextCount
from omnisocial.domain.spec import ErrorTable, NetworkSpec

ACCOUNT_CAPABILITIES = frozenset(
    {Capability.CONTENT, Capability.COMMENTS, Capability.INSIGHTS, Capability.PUBLISHING}
)

# Threads no documenta sus códigos de error: responde con la forma de la Graph API de Meta, y acá se
# usan los códigos generales de esa API.
#   190: el token venció, lo revocaron o es inválido.
#   10: a la app le falta el permiso.  200 a 299: al token le falta un permiso.
#   4, 17 y 613: límites de uso.  1 y 2: fallas pasajeras.  100: parámetro inválido.
_GROUPS = {
    ErrorKind.TOKEN_DEAD: (190,),
    ErrorKind.MISSING_PERMISSION: (10, *range(200, 300)),
    ErrorKind.RATE_LIMITED: (4, 17, 613),
    ErrorKind.TRANSIENT: (1, 2),
    ErrorKind.INVALID_REQUEST: (100,),
}
ERRORS = ErrorTable(codes={str(code): kind for kind, codes in _GROUPS.items() for code in codes})

# Hasta 20 imágenes o videos en un carrusel, tomados de una URL pública. Un link adjunto solo en un post
# de texto. Los emojis cuentan por sus bytes.
ACCOUNT_LIMITS = PublishLimits(
    max_text=500,
    text_count=TextCount.EMOJI_BYTES,
    max_images=20,
    max_videos=20,
    max_media=20,
    mix_media=True,
    link=True,
    delete=True,
    max_image_bytes=8 * 1024**2,
    max_video_bytes=1024**3,
    max_video_seconds=300,
    options=ThreadsOptions,
    max_thread=24,
)

SPEC = NetworkSpec(
    id=THREADS,
    name="Threads",
    capabilities=frozenset(
        {
            Capability.LOGIN,
            Capability.ASSETS,
            Capability.CONTENT,
            Capability.COMMENTS,
            Capability.INSIGHTS,
            Capability.PUBLISHING,
        }
    ),
    assets={THREADS_ACCOUNT: ACCOUNT_CAPABILITIES},
    errors=ERRORS,
    docs="docs/threads.md",
    publishing={THREADS_ACCOUNT: ACCOUNT_LIMITS},
)
