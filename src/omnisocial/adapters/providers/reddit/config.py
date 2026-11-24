"""Configuración de la app de Reddit."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

REDDIT = ProviderId("reddit")

REDDIT_ACCOUNT = "reddit_account"
"""La cuenta de quien autorizó. Publica en las comunidades donde puede hacerlo."""

LOGIN_SCOPES: tuple[str, ...] = ("identity",)
CONNECT_SCOPES: tuple[str, ...] = ("identity", "history", "read", "mysubreddits")
"""Quién es, sus publicaciones, los comentarios y sus comunidades."""
PUBLISH_SCOPES: tuple[str, ...] = ("submit", "edit", "flair")
"""Publicar y comentar (`submit`), borrar lo propio (`edit`) y ver las etiquetas de una comunidad."""
MODERATE_SCOPES: tuple[str, ...] = ("modposts",)
"""Quitar y aprobar comentarios, en las comunidades que la cuenta modera."""

AUTHORIZE_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"  # noqa: S105  # es una URL
REVOKE_URL = "https://www.reddit.com/api/v1/revoke_token"
API_BASE = "https://oauth.reddit.com"
SITE = "https://www.reddit.com"

MAX_TITLE = 300
_PREFIX = re.compile(r"^/?r/")


@dataclass(frozen=True, slots=True, kw_only=True)
class RedditConfig:
    client_id: str
    client_secret: str = field(repr=False)
    user_agent: str
    """Reddit lo exige y limita fuerte a quien manda uno genérico. La forma que pide:
    `<plataforma>:<id de la app>:<versión> (by /u/<usuario>)`."""
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = AUTHORIZE_URL
    token_url: str = TOKEN_URL
    revoke_url: str = REVOKE_URL
    api_base: str = API_BASE
    page_size: int = 100
    """Publicaciones o comunidades por página. La API acepta hasta 100."""
    max_pages: int = 10

    def __post_init__(self) -> None:
        if not self.user_agent.strip():
            raise ValueError("Reddit exige un User-Agent propio que identifique a la app.")


def community(name: str) -> str:
    """El nombre de una comunidad, sin `r/` ni barras."""
    return _PREFIX.sub("", name.strip()).strip("/")


@dataclass(frozen=True, slots=True)
class RedditOptions(PublishOptions):
    """En Reddit se publica en una comunidad y con un título: sin los dos no hay publicación."""

    subreddit: str
    """Sale de la consulta `communities`. Para el perfil propio, `u_<usuario>`."""
    title: str
    flair_id: str | None = None
    """Sale de la consulta `flairs`. Hay comunidades que no aceptan publicaciones sin etiqueta."""
    flair_text: str | None = None
    nsfw: bool = False
    spoiler: bool = False
    send_replies: bool = True
    """Si las respuestas llegan a la bandeja de la cuenta."""
    resubmit: bool = True
    """Si se acepta publicar un link que ya está en la comunidad. Con `False`, Reddit lo rechaza."""

    def __post_init__(self) -> None:
        if not community(self.subreddit):
            raise ValueError("Falta la comunidad donde se publica.")
        if not self.title.strip() or len(self.title) > MAX_TITLE:
            raise ValueError(f"El título es obligatorio y tiene hasta {MAX_TITLE} caracteres.")
