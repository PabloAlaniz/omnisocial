"""Links y hashtags en un post de Bluesky.

Bluesky no los detecta solo: sin marcarlos, un link queda como texto sin enlace. Cada marca dice de qué
byte a qué byte va (en UTF-8, no en caracteres) y qué es.
"""

from __future__ import annotations

import re
from operator import itemgetter

_LINK = re.compile(r"https?://[^\s<>\"']+")
_TAG = re.compile(r"(?<![\w#])#([^\W\d_]\w{0,63})")
# La puntuación pegada al final de un link no es parte del link.
_TRAILING = ".,;:!?)]}»"


def _facet(text: str, start: int, end: int, feature: dict[str, str]) -> dict[str, object]:
    index = {"byteStart": len(text[:start].encode()), "byteEnd": len(text[:end].encode())}
    return {"index": index, "features": [feature]}


def facets(text: str) -> list[dict[str, object]]:
    found: list[tuple[int, dict[str, object]]] = []
    links: list[tuple[int, int]] = []
    for match in _LINK.finditer(text):
        uri = match.group().rstrip(_TRAILING)
        links.append((match.start(), match.end()))
        feature = {"$type": "app.bsky.richtext.facet#link", "uri": uri}
        found.append((match.start(), _facet(text, match.start(), match.start() + len(uri), feature)))
    for match in _TAG.finditer(text):
        # Un `#` dentro de una URL es un ancla, no un hashtag.
        if any(start <= match.start() < end for start, end in links):
            continue
        feature = {"$type": "app.bsky.richtext.facet#tag", "tag": match.group(1)}
        found.append((match.start(), _facet(text, match.start(), match.end(), feature)))
    return [facet for _, facet in sorted(found, key=itemgetter(0))]
