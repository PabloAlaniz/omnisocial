"""Conectar una cuenta de Bluesky con una contraseña de aplicación.

La persona la genera en Bluesky (Configuración → Privacidad y seguridad → Contraseñas de aplicación) y la
carga junto con su nombre. Se cambia por una sesión (un token de acceso de unas dos horas y uno de
renovación de unos 90 días) y se descarta: lo que se guarda es la sesión.

El token de renovación rota: cada renovación trae uno nuevo.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse
from omnisocial.adapters.providers.bluesky.client import BlueskyClient, as_dict, as_int, as_str, bearer
from omnisocial.adapters.providers.bluesky.config import BLUESKY
from omnisocial.application.ports import CredentialLogin, IdentityReader
from omnisocial.domain.authorization import CredentialField
from omnisocial.domain.errors import ProviderError, TokenRejected
from omnisocial.domain.identity import Identity
from omnisocial.domain.server import normalize_server
from omnisocial.domain.token import Token, TokenKind

FIELDS = (
    CredentialField("identifier"),
    CredentialField("password", secret=True),
    CredentialField("server", required=False),
)
ACCESS_LIFETIME = timedelta(hours=2)
_UNAUTHORIZED = 401
# Al iniciar sesión o al renovar, estos errores quieren decir que la credencial no sirve.
_REJECTED = frozenset({"AuthenticationRequired", "ExpiredToken", "InvalidToken", "AccountTakedown"})
_SECOND_FACTOR = "AuthFactorTokenRequired"


def _expiry(jwt: str) -> datetime | None:
    """Cuándo vence un token, leído de su contenido. No se verifica la firma: solo se usa para saber
    cuándo renovar."""
    try:
        payload = jwt.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, binascii.Error):
        return None
    exp = as_int(as_dict(claims).get("exp"))
    return datetime.fromtimestamp(exp, UTC) if exp is not None else None


class BlueskySession(CredentialLogin):
    def __init__(self, client: BlueskyClient) -> None:
        self._client = client

    @property
    @override
    def fields(self) -> Sequence[CredentialField]:
        return FIELDS

    def _session(self, response: HttpResponse, server: str) -> Token:
        body = as_dict(response.data)
        name = as_str(body.get("error"))
        if name == _SECOND_FACTOR:
            raise TokenRejected(
                BLUESKY,
                "La cuenta pide un código por mail: hay que conectar con una contraseña de aplicación, "
                "no con la contraseña de la cuenta.",
                code=name,
            )
        if name in _REJECTED or (response.status == _UNAUTHORIZED and name is None):
            message = as_str(body.get("message")) or "credencial inválida"
            raise TokenRejected(BLUESKY, f"Bluesky rechazó la credencial: {message}", code=name)
        session = self._client.unwrap(response)
        access, refresh = as_str(session.get("accessJwt")), as_str(session.get("refreshJwt"))
        if not access or not refresh:
            raise ProviderError(BLUESKY, "Bluesky no devolvió una sesión.")
        expires_at = _expiry(access) or self._client.clock.now() + ACCESS_LIFETIME
        return Token(TokenKind.USER, access, refresh_token=refresh, expires_at=expires_at, server=server)

    @override
    async def login(self, credentials: Mapping[str, str]) -> Token:
        given = credentials.get("server") or self._client.config.default_server
        server = normalize_server(given)
        if server is None:
            raise TokenRejected(BLUESKY, f"'{given}' no es un servidor de Bluesky válido.")
        response = await self._client.transport_request(
            server,
            "com.atproto.server.createSession",
            json={
                "identifier": credentials["identifier"].strip().lstrip("@"),
                "password": credentials["password"],
            },
        )
        return self._session(response, server)

    @override
    def can_refresh(self, token: Token) -> bool:
        return token.refresh_token is not None

    @override
    async def refresh(self, token: Token) -> Token:
        if token.refresh_token is None or token.server is None:
            raise ProviderError(BLUESKY, "La sesión no tiene cómo renovarse.")
        response = await self._client.transport_request(
            token.server, "com.atproto.server.refreshSession", headers=bearer(token.refresh_token)
        )
        return self._session(response, token.server)

    @override
    async def revoke(self, token: Token) -> None:
        if token.refresh_token is None or token.server is None:
            return
        response = await self._client.transport_request(
            token.server, "com.atproto.server.deleteSession", headers=bearer(token.refresh_token)
        )
        self._client.unwrap(response)


async def own_session(client: BlueskyClient, token: Token) -> dict[str, object]:
    session = await client.get("com.atproto.server.getSession", token, {})
    if not as_str(session.get("did")):
        raise ProviderError(BLUESKY, "Bluesky no devolvió el DID de la cuenta.")
    return session


class BlueskyIdentity(IdentityReader):
    def __init__(self, client: BlueskyClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        """La identidad es el DID: el nombre es un dominio y puede cambiar."""
        session = await own_session(self._client, token)
        return Identity(
            provider=BLUESKY,
            external_id=str(session["did"]),
            name=as_str(session.get("handle")),
            email=as_str(session.get("email")),
        )
