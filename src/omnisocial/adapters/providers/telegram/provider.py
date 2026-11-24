"""Arma el proveedor de Telegram."""

from __future__ import annotations

from omnisocial.adapters.http.pacing import paced
from omnisocial.adapters.http.transport import HttpTransport
from omnisocial.adapters.providers.telegram.client import TelegramClient
from omnisocial.adapters.providers.telegram.config import TELEGRAM, TelegramConfig
from omnisocial.adapters.providers.telegram.sending import TelegramMessagingGateway, TelegramPublisher
from omnisocial.adapters.providers.telegram.session import (
    TelegramAssetDirectory,
    TelegramIdentity,
    TelegramSession,
)
from omnisocial.adapters.providers.telegram.spec import SPEC
from omnisocial.adapters.providers.telegram.webhooks import TelegramWebhookParser, TelegramWebhooks
from omnisocial.adapters.system import UuidGenerator
from omnisocial.application.ports import IdGenerator
from omnisocial.application.registry import Provider
from omnisocial.domain.spec import Pace


def telegram_provider(
    config: TelegramConfig,
    transport: HttpTransport,
    *,
    ids: IdGenerator | None = None,
    pace: Pace | None = SPEC.pace,
) -> Provider:
    """Cada bot se conecta con su token (`social.connect_with_credentials`). `pace` es el ritmo de los
    pedidos dentro de este proceso."""
    client = TelegramClient(config, paced(transport, pace))
    ids = ids or UuidGenerator()
    return Provider(
        id=TELEGRAM,
        credentials=TelegramSession(client),
        identity=TelegramIdentity(client),
        assets=TelegramAssetDirectory(client),
        publisher=TelegramPublisher(client, ids),
        messaging=TelegramMessagingGateway(client, ids),
        webhooks=TelegramWebhookParser(config.webhook_secret),
        spec=SPEC,
    )


def telegram_webhooks(config: TelegramConfig, transport: HttpTransport) -> TelegramWebhooks:
    """Para registrar la URL de los avisos de cada bot."""
    return TelegramWebhooks(TelegramClient(config, transport))
