from datetime import UTC, datetime

from omnisocial.domain.connection import Connection, ConnectionStatus
from omnisocial.domain.identity import Identity
from omnisocial.domain.provider import ProviderId
from omnisocial.domain.token import Token, TokenKind

NOW = datetime(2026, 11, 23, tzinfo=UTC)
LATER = datetime(2026, 11, 24, tzinfo=UTC)
P = ProviderId("red")


def _connection() -> Connection:
    return Connection(
        id="c1",
        provider=P,
        owner="dueño",
        subject=Identity(P, "u1"),
        token=Token(TokenKind.USER, "viejo"),
        status=ConnectionStatus.ACTIVE,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def test_cambiar_el_token_sube_la_version_y_reactiva() -> None:
    invalid = _connection().mark(ConnectionStatus.INVALID, "revocado", NOW)
    renewed = invalid.with_token(Token(TokenKind.USER, "nuevo"), LATER)
    assert renewed.version == 3
    assert renewed.is_usable
    assert renewed.status_reason is None
    assert renewed.updated_at == LATER


def test_marcar_guarda_el_motivo() -> None:
    marked = _connection().mark(ConnectionStatus.EXPIRED, "venció", LATER)
    assert not marked.is_usable
    assert marked.status_reason == "venció"
    assert marked.version == 2


def test_reconectar_actualiza_la_identidad() -> None:
    again = _connection().reconnect(Identity(P, "u1", name="Nuevo"), Token(TokenKind.USER, "x"), LATER)
    assert again.subject.name == "Nuevo"
