"""Qué es una red y qué puede hacer."""

from __future__ import annotations

from enum import StrEnum
from typing import NewType

ProviderId = NewType("ProviderId", str)
"""Identificador estable de una red: `meta`, `tiktok`… Es lo que se guarda en la base."""


class Capability(StrEnum):
    """Lo que una red puede hacer. Cada adaptador implementa solo las que soporta."""

    LOGIN = "login"
    ASSETS = "assets"
    CONTENT = "content"
    COMMENTS = "comments"
    MESSAGING = "messaging"
    INSIGHTS = "insights"
    WEBHOOKS = "webhooks"
    PUBLISHING = "publishing"
    """Publicar en un activo, retomar una publicación en curso y borrarla."""
    PUBLIC_PROFILES = "public_profiles"
    """Leer el perfil público de cuentas que no se administran."""
