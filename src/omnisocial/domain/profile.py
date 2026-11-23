"""Lo que se ve de una cuenta ajena: el perfil público."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from omnisocial.domain.handles import Network


@dataclass(frozen=True, slots=True)
class PublicProfile:
    """Una cuenta que no administramos, tal como la muestra la red.

    `external_id` es la identidad: el nombre puede cambiar y el id no. Conviene guardar la historia por id.
    Los contadores en `None` quieren decir que la red no los informó, no que sean cero.
    """

    network: Network
    external_id: str
    username: str | None = None
    name: str | None = None
    followers: int | None = None
    following: int | None = None
    posts: int | None = None
    bio: str | None = None
    avatar_url: str | None = None
    """Suele ser un link firmado que vence: si hace falta mostrarlo después, conviene copiar la imagen."""
    website: str | None = None
    verified: bool | None = None
    url: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict, repr=False)
