from datetime import UTC, datetime, timedelta

from omnisocial.domain.authorization import AuthorizationRequest, Purpose, pkce_challenge
from omnisocial.domain.provider import ProviderId

NOW = datetime(2026, 11, 23, tzinfo=UTC)


def test_pkce_s256_del_rfc_7636() -> None:
    # Vector del apéndice B del RFC 7636.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def _request(verifier: str | None) -> AuthorizationRequest:
    return AuthorizationRequest(
        state="s",
        provider=ProviderId("red"),
        purpose=Purpose.LOGIN,
        redirect_uri="https://app/cb",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        scopes=(),
        code_verifier=verifier,
    )


def test_el_pedido_vence_y_calcula_su_challenge() -> None:
    request = _request("v")
    assert request.code_challenge == pkce_challenge("v")
    assert _request(None).code_challenge is None
    assert not request.is_expired(NOW)
    assert request.is_expired(NOW + timedelta(minutes=10))
    assert "'v'" not in repr(request)
