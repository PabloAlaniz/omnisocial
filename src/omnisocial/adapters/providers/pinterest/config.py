"""Configuración de la app de Pinterest."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnisocial.domain.provider import ProviderId
from omnisocial.domain.publishing import PublishOptions

PINTEREST = ProviderId("pinterest")

PINTEREST_ACCOUNT = "pinterest_account"
"""La cuenta de quien autorizó. Publica en sus tableros."""

LOGIN_SCOPES: tuple[str, ...] = ("user_accounts:read",)
CONNECT_SCOPES: tuple[str, ...] = ("user_accounts:read", "boards:read", "pins:read")
PUBLISH_SCOPES: tuple[str, ...] = ("boards:write", "pins:write")
"""Crear y borrar pines. Pinterest pide los cuatro permisos de tableros y pines para escribir."""

AUTHORIZE_URL = "https://www.pinterest.com/oauth/"
API_BASE = "https://api.pinterest.com/v5"
SANDBOX_BASE = "https://api-sandbox.pinterest.com/v5"
"""Donde se prueba sin tocar la cuenta. Usa su propio token."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PinterestConfig:
    client_id: str
    client_secret: str = field(repr=False)
    login_scopes: tuple[str, ...] = LOGIN_SCOPES
    connect_scopes: tuple[str, ...] = CONNECT_SCOPES
    authorize_url: str = AUTHORIZE_URL
    api_base: str = API_BASE
    page_size: int = 100
    """Pines o tableros por página. La API acepta hasta 250."""
    max_pages: int = 20
    """Cuántas páginas se recorren como mucho al leer pines o tableros."""

    @property
    def token_url(self) -> str:
        return f"{self.api_base}/oauth/token"


@dataclass(frozen=True, slots=True)
class PinterestOptions(PublishOptions):
    """Un pin siempre va a un tablero: sin `board_id` no se publica. Sale de la consulta `boards`."""

    board_id: str
    title: str | None = None
    """Hasta 100 caracteres."""
    link: str | None = None
    """A dónde lleva el pin."""
    board_section_id: str | None = None
    """Una sección del tablero. Sale de la consulta `board_sections`."""
    cover_image_url: str | None = None
    """La portada de un video. Si falta, se usa un cuadro del video (`cover_second`)."""
    cover_second: int = 0

    def __post_init__(self) -> None:
        if not self.board_id:
            raise ValueError("Un pin va a un tablero: falta `board_id`.")
