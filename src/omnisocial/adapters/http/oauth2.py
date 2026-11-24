"""OAuth 2.0 con código de autorización, armado desde la descripción de la red.

Una red cuyo OAuth sigue el estándar no escribe un cliente: declara un `OAuthSpec` y usa `StandardOAuth`.
Lo único propio que aporta es cómo se lee la identidad de la persona.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlencode

from typing_extensions import override

from omnisocial.adapters.http.transport import HttpResponse, HttpTransport
from omnisocial.application.ports import Clock, IdentityReader, OAuthClient
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError, TokenRejected
from omnisocial.domain.identity import Identity
from omnisocial.domain.spec import NetworkSpec, OAuthSpec
from omnisocial.domain.token import Token, TokenKind

# RFC 6749: la credencial (el código o el token de renovación) venció, fue revocada o ya se usó.
_GRANT_DEAD = "invalid_grant"
_CLIENT_ERROR = 400
_SCOPE_SEPARATORS = re.compile(r"[,\s]+")


@dataclass(frozen=True, slots=True)
class OAuthApp:
    """La app registrada en la red y los permisos que pide para cada propósito."""

    client_id: str
    client_secret: str = field(repr=False)
    scopes: Mapping[Purpose, tuple[str, ...]] = field(default_factory=dict)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _seconds(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.isdigit() else None


class StandardOAuth(OAuthClient):
    def __init__(
        self,
        network: NetworkSpec,
        app: OAuthApp,
        *,
        transport: HttpTransport,
        clock: Clock,
        identity: IdentityReader,
    ) -> None:
        if network.oauth is None:
            raise ValueError(f"La red '{network.id}' no declara su OAuth.")
        self._network = network
        self._spec: OAuthSpec = network.oauth
        self._app = app
        self._transport = transport
        self._clock = clock
        self._identity = identity

    @property
    @override
    def supports_pkce(self) -> bool:
        return self._spec.pkce

    @override
    def default_scopes(self, purpose: Purpose) -> tuple[str, ...]:
        return self._app.scopes.get(purpose, ())

    @override
    def authorization_url(
        self, *, state: str, redirect_uri: str, scopes: Sequence[str], code_challenge: str | None
    ) -> str:
        query = {
            self._spec.client_id_param: self._app.client_id,
            "scope": self._spec.scope_separator.join(scopes),
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            **self._spec.authorize_params,
        }
        if self._spec.pkce and code_challenge is not None:
            query |= {"code_challenge": code_challenge, "code_challenge_method": "S256"}
        return f"{self._spec.authorize_url}?{urlencode(query)}"

    @override
    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str | None) -> Token:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        if code_verifier is not None:
            form["code_verifier"] = code_verifier
        return self._token(await self._post(self._spec.token_url, form))

    @override
    async def identity(self, token: Token) -> Identity:
        return await self._identity.identity(token)

    @override
    def can_refresh(self, token: Token) -> bool:
        return token.refresh_token is not None

    @override
    async def refresh(self, token: Token) -> Token:
        """Si la red rota el token de renovación, la respuesta trae uno nuevo y el anterior deja de servir.

        Si no manda ninguno, se conserva el que había. Quien llama guarda el token devuelto entero (lo hace
        `GetValidToken`, con compare-and-swap, así dos procesos no renuevan con el mismo token).
        """
        if token.refresh_token is None:
            raise ProviderError(self._network.id, "El token no tiene refresh token.")
        body = await self._post(
            self._spec.token_url, {"grant_type": "refresh_token", "refresh_token": token.refresh_token}
        )
        return self._token(body, previous=token)

    @override
    async def revoke(self, token: Token) -> None:
        if self._spec.revoke_url is not None:
            await self._post(self._spec.revoke_url, {"token": token.access_token}, revoking=True)

    def _token(self, body: Mapping[str, object], *, previous: Token | None = None) -> Token:
        access = _text(body.get("access_token"))
        if access is None:
            raise ProviderError(self._network.id, f"{self._network.name} no devolvió un token.")
        expires_in = _seconds(body.get("expires_in"))
        granted = frozenset(s for s in _SCOPE_SEPARATORS.split(_text(body.get("scope")) or "") if s)
        return Token(
            TokenKind.USER,
            access,
            refresh_token=_text(body.get("refresh_token")) or (previous.refresh_token if previous else None),
            expires_at=self._clock.now() + timedelta(seconds=expires_in) if expires_in else None,
            scopes=granted or (previous.scopes if previous else frozenset()),
        )

    async def _post(
        self, url: str, form: Mapping[str, str], *, revoking: bool = False
    ) -> Mapping[str, object]:
        """`revoking`: la revocación puede no llevar credenciales y responder sin cuerpo."""
        credentials = {
            self._spec.client_id_param: self._app.client_id,
            self._spec.client_secret_param: self._app.client_secret,
        }
        headers: dict[str, str] | None = None
        if revoking and not self._spec.revoke_with_credentials:
            credentials = {}
        elif self._spec.client_auth_basic:
            pair = f"{self._app.client_id}:{self._app.client_secret}".encode()
            headers = {"Authorization": f"Basic {base64.b64encode(pair).decode()}"}
            # La clave va igual en el cuerpo: es pública y hay redes que la piden ahí también.
            credentials = {self._spec.client_id_param: self._app.client_id}
        response = await self._transport.request(
            "POST",
            url,
            form={**credentials, **form},
            headers=headers,
            # El código y el token de renovación son de un solo uso: si el primer intento llegó y se perdió
            # la respuesta, el reintento falla con invalid_grant igual. Lo que salva es el 5xx pasajero.
            retry_safe="no publica nada en la cuenta",
        )
        body: Mapping[str, object] = response.data if isinstance(response.data, dict) else {}
        code = _text(body.get("error"))
        if code is not None:
            raise self._error(response, code, _text(body.get("error_description")) or code)
        if response.status >= _CLIENT_ERROR or not (revoking or isinstance(response.data, dict)):
            raise self._error(response, None, response.text[:300] or f"HTTP {response.status}")
        return body

    def _error(self, response: HttpResponse, code: str | None, message: str) -> Exception:
        provider = self._network.id
        if code == _GRANT_DEAD:
            return TokenRejected(
                provider, f"{self._network.name} rechazó la credencial: {message}", code=code
            )
        return self._network.errors.error(
            provider, message, status=response.status, code=code, retry_after=response.retry_after()
        )
