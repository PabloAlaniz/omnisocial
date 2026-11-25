"""El login de WhatsApp Business: el diálogo de Facebook, con la configuración de la app."""

from __future__ import annotations

from dataclasses import replace

from typing_extensions import override

from omnisocial.adapters.http.oauth2 import OAuthApp, StandardOAuth
from omnisocial.adapters.providers.whatsapp.client import WhatsAppClient, as_str
from omnisocial.adapters.providers.whatsapp.config import WHATSAPP
from omnisocial.adapters.providers.whatsapp.spec import SPEC, oauth_spec
from omnisocial.application.ports import Clock, IdentityReader
from omnisocial.domain.authorization import Purpose
from omnisocial.domain.errors import ProviderError
from omnisocial.domain.identity import Identity
from omnisocial.domain.token import Token


class WhatsAppIdentity(IdentityReader):
    def __init__(self, client: WhatsAppClient) -> None:
        self._client = client

    @override
    async def identity(self, token: Token) -> Identity:
        """La persona o el usuario de sistema dueño del token."""
        me = await self._client.get("me", token.access_token, {"fields": "id,name"})
        external_id = as_str(me.get("id"))
        if external_id is None:
            raise ProviderError(WHATSAPP, "Meta no devolvió el id del dueño del token.")
        return Identity(provider=WHATSAPP, external_id=external_id, name=as_str(me.get("name")))


def whatsapp_oauth(client: WhatsAppClient, clock: Clock) -> StandardOAuth:
    config = client.config
    oauth = oauth_spec(config.authorize_url, f"{config.api_base}/oauth/access_token")
    if config.config_id:
        oauth = replace(oauth, authorize_params={"config_id": config.config_id})
    app = OAuthApp(
        config.app_id,
        config.app_secret,
        scopes={Purpose.LOGIN: config.connect_scopes, Purpose.CONNECT: config.connect_scopes},
    )
    return StandardOAuth(
        replace(SPEC, oauth=oauth),
        app,
        transport=client.transport,
        clock=clock,
        identity=WhatsAppIdentity(client),
    )
