from datetime import UTC, datetime, timedelta

from omnisocial.domain.token import Token, TokenKind

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)


def test_un_token_sin_vencimiento_nunca_vence_ni_pide_renovacion() -> None:
    token = Token(TokenKind.ASSET, "t")
    assert not token.is_expired(NOW)
    assert not token.needs_refresh(NOW)


def test_pide_renovacion_dentro_del_margen_antes_de_vencer() -> None:
    token = Token(TokenKind.USER, "t", expires_at=NOW + timedelta(minutes=3))
    assert token.needs_refresh(NOW)
    assert not token.is_expired(NOW)


def test_vence_en_el_instante_exacto() -> None:
    assert Token(TokenKind.USER, "t", expires_at=NOW).is_expired(NOW)


def test_el_token_no_aparece_en_repr() -> None:
    assert "secreto" not in repr(Token(TokenKind.USER, "secreto", refresh_token="otro-secreto"))


def test_scopes_faltantes() -> None:
    token = Token(TokenKind.USER, "t", scopes=frozenset({"a"}))
    assert token.missing_scopes(frozenset({"a", "b"})) == {"b"}
    assert token.with_scopes(frozenset({"a", "b"})).missing_scopes(frozenset({"b"})) == frozenset()
