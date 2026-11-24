"""Consultas auxiliares: lo que hay que elegir antes de publicar.

Algunas redes no publican "en la cuenta" a secas: un pin va a un tablero, un post de Reddit a una comunidad
y, según la comunidad, con una etiqueta. La red declara qué consultas ofrece y la app las usa para armar el
formulario.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LookupSpec:
    name: str
    """Con qué nombre se pide: `boards`, `communities`."""
    description: str
    parent: str | None = None
    """Si las opciones dependen de otra elección, de cuál: las etiquetas dependen de la comunidad."""
    searchable: bool = False
    """Si acepta un texto para buscar. Sin texto devuelve lo propio de la cuenta."""


@dataclass(frozen=True, slots=True)
class Choice:
    id: str
    """Lo que va en las opciones de la publicación."""
    name: str
    detail: str | None = None
    data: Mapping[str, str] = field(default_factory=dict)
    """Lo que la red dice de esa opción y sirve para decidir (si una comunidad acepta links, por ejemplo)."""
