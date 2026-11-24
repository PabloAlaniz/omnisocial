"""Cómo se arma una red para probarla contra su API real.

Cada red se enciende con una variable de entorno, `OMNISOCIAL_LIVE_<RED>`, que trae un JSON:

    {
      "config": {"client_id": "...", "client_secret": "..."},
      "token": {"access_token": "...", "refresh_token": "...", "server": "mastodon.social"},
      "credentials": {"token": "..."},
      "write": {"options": {"chat_id": "@canal_de_prueba"}}
    }

- `config`: los argumentos de la configuración de esa red.
- `token` o `credentials`: con qué se conecta la cuenta de prueba. Una de las dos.
- `write`: opcional. Si está y además `OMNISOCIAL_LIVE_WRITE=1`, se publica un texto y se lo borra.

Sin la variable, la red se saltea. Nada de esto se imprime.
"""

from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.stores.memory import InMemoryServerAppStore
from omnisocial.application.registry import Provider
from omnisocial.domain.publishing import PublishOptions
from omnisocial.domain.token import Token, TokenKind

PREFIX = "OMNISOCIAL_LIVE_"
WRITE = "OMNISOCIAL_LIVE_WRITE"
REPORT = "OMNISOCIAL_LIVE_REPORT"

NETWORKS = (
    "meta",
    "instagram",
    "tiktok",
    "youtube",
    "linkedin",
    "x",
    "threads",
    "bluesky",
    "mastodon",
    "pixelfed",
    "pinterest",
    "reddit",
    "google_business",
    "whatsapp",
    "telegram",
    "discord",
    "discord_webhook",
)
"""Las redes que se pueden probar en vivo. Un test comprueba que estén todas las del paquete."""


def variable(network: str) -> str:
    return f"{PREFIX}{network.upper()}"


@dataclass(frozen=True, slots=True)
class Setup:
    network: str
    config: Mapping[str, object] = field(default_factory=dict, repr=False)
    token: Token | None = field(default=None, repr=False)
    credentials: Mapping[str, str] = field(default_factory=dict, repr=False)
    write: Mapping[str, object] | None = field(default=None, repr=False)


def _token(data: Mapping[str, object]) -> Token:
    expires, scopes = data.get("expires_at"), data.get("scopes")
    return Token(
        TokenKind(str(data.get("kind", "user"))),
        str(data["access_token"]),
        refresh_token=str(data["refresh_token"]) if data.get("refresh_token") else None,
        expires_at=datetime.fromisoformat(str(expires)) if expires else None,
        scopes=frozenset(str(scope) for scope in scopes) if isinstance(scopes, list) else frozenset(),
        server=str(data["server"]) if data.get("server") else None,
    )


def parse(network: str, raw: str) -> Setup:
    """El armado de una red, desde el JSON de su variable."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError(f"{variable(network)} tiene que ser un objeto JSON.")
    token, credentials = data.get("token"), data.get("credentials") or {}
    if (token is None) == (not credentials):
        raise ValueError(f"{variable(network)} trae `token` o `credentials`: una de las dos.")
    return Setup(
        network,
        config=data.get("config") or {},
        token=_token(token) if token is not None else None,
        credentials={str(key): str(value) for key, value in credentials.items()},
        write=data.get("write"),
    )


def _public(network: str) -> object:
    return importlib.import_module(f"omnisocial.{network}")


def _one(module: object, suffix: str) -> type | None:
    names = [name for name in getattr(module, "__all__", ()) if name.endswith(suffix)]
    return getattr(module, names[0]) if len(names) == 1 else None


def build(setup: Setup, transport: HttpTransport) -> Provider:
    """El proveedor de esa red, con su configuración. Las listas del JSON pasan a ser tuplas."""
    module = _public(setup.network)
    config_class = _one(module, "Config")
    if config_class is None:
        raise LookupError(f"`omnisocial.{setup.network}` no exporta una sola configuración.")
    values = {key: tuple(value) if isinstance(value, list) else value for key, value in setup.config.items()}
    factory = getattr(module, f"{setup.network}_provider")
    extra: dict[str, object] = {}
    if "apps" in inspect.signature(factory).parameters:
        # Las redes federadas registran una app por servidor: para una prueba alcanza con la memoria.
        extra["apps"] = InMemoryServerAppStore()
    provider = factory(config_class(**values), transport, **extra)
    if not isinstance(provider, Provider):
        raise TypeError(f"`{setup.network}_provider` no devolvió un proveedor.")
    return provider


def options(setup: Setup) -> PublishOptions | None:
    """Las opciones para publicar en esa red, si el armado las trae."""
    given = (setup.write or {}).get("options")
    if not isinstance(given, dict):
        return None
    options_class = _one(_public(setup.network), "Options")
    if options_class is None:
        raise LookupError(f"`omnisocial.{setup.network}` no exporta un solo tipo de opciones.")
    built = options_class(**given)
    if not isinstance(built, PublishOptions):
        raise TypeError(f"Las opciones de `{setup.network}` no son opciones de publicación.")
    return built
