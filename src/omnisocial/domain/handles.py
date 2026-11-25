"""Cuentas por su nombre público: `@marca`, `instagram.com/marca/`, `youtube.com/channel/UC…`.

La gente pega lo que tiene a mano. Esto lo lleva a una forma única por red, para buscar la cuenta y para no
guardar la misma dos veces. La identidad estable de una cuenta es su id numérico en la red, no el nombre:
el nombre se usa para encontrarla.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qs, unquote, urlsplit

from typing_extensions import override

from omnisocial.domain.server import normalize_server


class Network(StrEnum):
    """La red donde vive una cuenta pública. Meta, como proveedor, cubre dos: Facebook e Instagram."""

    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    X = "x"
    LINKEDIN = "linkedin"
    THREADS = "threads"
    BLUESKY = "bluesky"
    MASTODON = "mastodon"
    """También vale para las redes que hablan el mismo protocolo, como Pixelfed."""


class HandleKind(StrEnum):
    USERNAME = "username"
    """El nombre que elige la cuenta. Puede cambiar."""
    ID = "id"
    """Un id que la red no cambia: el `UC…` de un canal de YouTube o el número de un perfil de Facebook."""


@dataclass(frozen=True, slots=True)
class Handle:
    network: Network
    value: str
    kind: HandleKind = HandleKind.USERNAME

    @override
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class _Rule:
    hosts: tuple[str, ...]
    pattern: re.Pattern[str]
    prefixes: tuple[str, ...] = ()
    """Segmentos de ruta que van antes del nombre (`channel/`, `company/`)."""


_RULES: dict[Network, _Rule] = {
    Network.FACEBOOK: _Rule(("facebook.com", "fb.com"), re.compile(r"[a-z0-9.]{1,50}|\d+")),
    Network.INSTAGRAM: _Rule(("instagram.com",), re.compile(r"[a-z0-9._]{1,30}")),
    Network.TIKTOK: _Rule(("tiktok.com",), re.compile(r"@[a-z0-9._-]{2,24}")),
    Network.YOUTUBE: _Rule(
        ("youtube.com",),
        re.compile(r"@[a-z0-9._-]{3,30}|[a-z0-9._-]{1,100}"),
        prefixes=("channel", "user", "c"),
    ),
    Network.X: _Rule(("x.com", "twitter.com"), re.compile(r"[a-z0-9_]{1,15}")),
    Network.THREADS: _Rule(("threads.com", "threads.net"), re.compile(r"[a-z0-9._]{1,30}")),
    Network.LINKEDIN: _Rule(
        ("linkedin.com",), re.compile(r"[a-z0-9-]{1,100}"), prefixes=("in", "company", "school")
    ),
}

_YOUTUBE_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def _host_matches(host: str, hosts: tuple[str, ...]) -> bool:
    host = host.lower().removeprefix("www.").removeprefix("m.")
    return any(host == known or host.endswith(f".{known}") for known in hosts)


def _from_url(raw: str, rule: _Rule) -> str | None:
    """El segmento del nombre en una URL de la red, o `None` si la URL es de otro sitio."""
    url = raw if _SCHEME.match(raw) else f"https://{raw}"
    parts = urlsplit(url)
    if not _host_matches(parts.hostname or "", rule.hosts):
        return None
    # Las barras codificadas (`%2F`) se decodifican antes de partir la ruta; si no, quedan dentro del nombre.
    segments = [s for s in unquote(parts.path).split("/") if s]
    if segments[:1] == ["profile.php"]:
        return next(iter(parse_qs(parts.query).get("id", [])), "")
    if len(segments) > 1 and segments[0] in rule.prefixes:
        return segments[1]
    return segments[0] if segments else ""


def _looks_like_url(raw: str, rule: _Rule) -> bool:
    return bool(_SCHEME.match(raw)) or any(known in raw.lower() for known in rule.hosts)


_FEDIVERSE_USER = re.compile(r"[a-z0-9_]{1,30}")
_BLUESKY_DID = re.compile(r"did:(?:plc|web):[a-z0-9.:%-]{1,200}")


def _mastodon(text: str) -> Handle | None:
    """`@ana@mastodon.social`, `ana@mastodon.social` o `https://mastodon.social/@ana`: el nombre lleva
    el servidor, porque la misma persona puede existir en varios."""
    if _SCHEME.match(text):
        parts = urlsplit(text)
        segments = [s for s in unquote(parts.path).split("/") if s]
        text = f"{segments[0]}@{parts.hostname}" if segments and segments[0].startswith("@") else ""
    user, _, server = text.lstrip("@").lower().partition("@")
    host = normalize_server(server)
    if host is None or not _FEDIVERSE_USER.fullmatch(user):
        return None
    return Handle(Network.MASTODON, f"{user}@{host}")


def _bluesky(text: str) -> Handle | None:
    """`ana.bsky.social`, `@ana.bsky.social`, `https://bsky.app/profile/ana.bsky.social` o un DID. El
    nombre es un dominio y puede cambiar; el DID no."""
    if _SCHEME.match(text):
        parts = urlsplit(text)
        segments = [s for s in unquote(parts.path).split("/") if s]
        is_profile = parts.hostname == "bsky.app" and segments[:1] == ["profile"] and len(segments) > 1
        text = segments[1] if is_profile else ""
    name = text.lstrip("@").lower()
    if _BLUESKY_DID.fullmatch(name):
        return Handle(Network.BLUESKY, name, HandleKind.ID)
    host = normalize_server(name)
    return Handle(Network.BLUESKY, host) if host is not None else None


_FEDERATED = {Network.MASTODON: _mastodon, Network.BLUESKY: _bluesky}


def parse_handle(network: Network | str, raw: str) -> Handle | None:
    """El nombre normalizado, o `None` si lo que se pegó no es una cuenta válida de esa red."""
    federated = _FEDERATED.get(Network(network))
    if federated is not None:
        return federated(raw.strip())
    rule = _RULES[Network(network)]
    text = raw.strip()
    if _looks_like_url(text, rule):
        found = _from_url(text, rule)
        if found is None:
            return None
        text = found
    if network == Network.YOUTUBE and _YOUTUBE_CHANNEL_ID.fullmatch(text):
        return Handle(Network.YOUTUBE, text, HandleKind.ID)
    name = text.lstrip("@").lower()
    # En TikTok el nombre siempre lleva `@`; en YouTube, `@marca` es un handle y `marca` un usuario viejo.
    if network == Network.TIKTOK or (network == Network.YOUTUBE and text.startswith("@")):
        name = f"@{name}"
    if not name or not rule.pattern.fullmatch(name):
        return None
    kind = HandleKind.ID if network == Network.FACEBOOK and name.isdigit() else HandleKind.USERNAME
    return Handle(Network(network), name, kind)
