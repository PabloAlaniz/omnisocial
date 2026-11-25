"""El login de X: OAuth 2.0 con PKCE. La identidad es la cuenta que autorizó."""

from __future__ import annotations

from dataclasses import replace

from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.providers.x.client import XClient, as_dict, as_str
from omnisocial.adapters.providers.x.config import X
from omnisocial.adapters.providers.x.spec import SPEC, oauth_spec
from omnisocial.application.ports import Clock, IdentityReader
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token

USER_FIELDS = "profile_image_url,username,name,public_metrics,description,verified,url"


async def own_account(client: XClient, token: Token) -> dict[str, object]:
    data = await client.get("users/me", token.access_token, {"user.fields": USER_FIELDS})
    account = as_dict(data.get("data"))
    if not as_str(account.get("id")):
        raise ProviderError(X, "X no devolvió el id de la cuenta.")
    return account


class XIdentity(IdentityReader):
    def __init__(self, client: XClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        account = await own_account(self._client, token)
        return Identity(
            provider=X,
            external_id=str(account["id"]),
            name=as_str(account.get("name")) or as_str(account.get("username")),
            avatar_url=as_str(account.get("profile_image_url")),
        )


def x_oauth(client: XClient, clock: Clock) -> StandardOAuth:
    """El token dura dos horas y el de renovación es de un solo uso: cada renovación trae uno nuevo. Dos
    sistemas con la misma app no pueden compartir una conexión, porque cada uno le invalida el token al
    otro."""
    config = client.config
    network = replace(SPEC, oauth=oauth_spec(authorize_url=config.authorize_url, api_base=config.api_base))
    app = OAuthApp(
        config.client_id or "",
        config.client_secret or "",
        scopes={Purpose.LOGIN: config.login_scopes, Purpose.CONNECT: config.connect_scopes},
    )
    return StandardOAuth(network, app, transport=client.transport, clock=clock, identity=XIdentity(client))
