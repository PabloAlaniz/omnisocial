"""El formato de texto de LinkedIn ("little text").

Los caracteres reservados se escapan con una barra invertida. Sin eso, un paréntesis o un guion bajo en un
texto común puede hacer que LinkedIn rechace la publicación o la muestre cortada.
"""

from __future__ import annotations

import re

# `#` queda afuera a propósito: escapado deja de ser un hashtag.
_RESERVED = re.compile(r"([|{}@\[\]()<>\\*_~])")
_ESCAPED = re.compile(r"\\([|{}@\[\]()<>#\\*_~])")
# Un hashtag vuelve como `{hashtag|\#|tema}`; una mención, como `@[Nombre](urn:li:…)`.
_HASHTAG = re.compile(r"\{hashtag\|\\?#\|([^}]*)\}")
_MENTION = re.compile(r"@\[((?:[^\]\\]|\\.)*)\]\(urn:li:[^)]*\)")


def escape(text: str) -> str:
    """Texto común → little text."""
    return _RESERVED.sub(r"\\\1", text)


def plain(text: str) -> str:
    """Little text → texto común, con los hashtags y las menciones como se leen."""
    text = _HASHTAG.sub(r"#\1", text)
    text = _MENTION.sub(r"@\1", text)
    return _ESCAPED.sub(r"\1", text)
