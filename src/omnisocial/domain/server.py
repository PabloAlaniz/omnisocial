"""El servidor de una red federada: la instancia de Mastodon, el servidor de datos de Bluesky.

Lo elige quien conecta la cuenta, y la librería después le hace pedidos. Por eso se valida: tiene que ser
un nombre de dominio público, no una dirección ni un nombre interno.
"""

from __future__ import annotations

import re

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST = re.compile(rf"(?:{_LABEL}\.)+[a-z]{{2,63}}")
_INTERNAL = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".test", ".invalid", ".example")
_MAX_LENGTH = 253


def normalize_server(text: str) -> str | None:
    """El nombre del servidor, en minúsculas y sin adornos. `None` si no es un dominio público.

    Acepta `mastodon.social`, `https://mastodon.social/` o `Mastodon.Social`. Rechaza `http://`, las
    direcciones IP, los puertos, las rutas y los nombres internos.

    No protege contra un dominio público que resuelve a una dirección interna: eso se controla en la
    salida a la red de quien despliega.
    """
    host = text.strip().lower().removeprefix("https://").removesuffix("/")
    if len(host) > _MAX_LENGTH or not _HOST.fullmatch(host) or host.endswith(_INTERNAL):
        return None
    return host
