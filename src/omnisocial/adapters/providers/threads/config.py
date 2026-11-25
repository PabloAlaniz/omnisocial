"""Configuración de la app de Threads."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

THREADS = ProviderId("threads")

THREADS_ACCOUNT = "threads_account"

LOGIN_SCOPES: tuple[str, ...] = ("threads_basic",)

CONNECT_SCOPES: tuple[str, ...] = ("threads_basic", "threads_read_replies", "threads_manage_insights")
"""Leer la cuenta, sus posts, las respuestas y las métricas."""

PUBLISH_SCOPES: tuple[str, ...] = ("threads_content_publish", "threads_delete")
"""Publicar (también responder) y borrar."""

MODERATE_SCOPES: tuple[str, ...] = ("threads_manage_replies",)
"""Ocultar respuestas."""


@dataclass(frozen=True, slots=True)
class ThreadsConfig:
    """La app de Threads. Tiene su propio id y su propio secreto, distintos de los de la app de Meta."""

    client_id: str
    client_secret: str = field(repr=False)
    api_version: str = "v1.0"
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = "https://threads.com/oauth/authorize"
    graph_url: str = "https://graph.threads.com"
    page_size: int = 50
    """Posts o respuestas por página. La API acepta hasta 100."""

    @property
    def base(self) -> str:
        return f"{self.graph_url.rstrip('/')}/{self.api_version}"


@dataclass(frozen=True, slots=True)
class ThreadsOptions(PublishOptions):
    reply_to: str | None = None
    """El id del post al que responde."""
    reply_control: str | None = None
    """Quién puede responder: `everyone`, `accounts_you_follow`, `mentioned_only`, `followers_only` o
    `parent_post_author_only`."""
    topic_tag: str | None = None
    """El tema del post: de 1 a 50 caracteres, sin puntos ni `&`."""
