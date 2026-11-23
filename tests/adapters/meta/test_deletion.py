from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from omnisocial.adapters.providers.meta.deletion import (
    InvalidSignedRequest,
    MetaDeletionRequests,
    parse_signed_request,
)
from tests.adapters.meta.conftest import config


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def signed(payload: object, secret: str = "secreto") -> str:
    encoded = _b64(json.dumps(payload).encode())
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{_b64(signature)}.{encoded}"


VALID = {"algorithm": "HMAC-SHA256", "user_id": "123", "issued_at": 1_700_000_000}


def test_un_signed_request_valido() -> None:
    request = parse_signed_request(signed(VALID), ["secreto"])
    assert request.user_id == "123"
    assert request.issued_at == datetime.fromtimestamp(1_700_000_000, UTC)


def test_acepta_el_secreto_anterior_mientras_se_rota() -> None:
    requests = MetaDeletionRequests(config(app_secret="nuevo", previous_app_secrets=("viejo",)))
    assert requests.parse(signed(VALID, "viejo")).user_id == "123"
    assert requests.parse(signed({**VALID, "user_id": 9, "issued_at": None}, "nuevo")).issued_at is None


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("sin-punto", "forma"),
        (".datos", "forma"),
        ("a.b.c", "forma"),
        ("%%%.e30", "base64url"),
        (signed(VALID, "otro"), "firma"),
        (signed({**VALID, "algorithm": "HMAC-SHA1"}), "HMAC-SHA256"),
        (signed({"algorithm": "HMAC-SHA256"}), "user_id"),
        (signed({**VALID, "user_id": True}), "user_id"),
        (signed([1, 2]), "objeto"),
    ],
)
def test_lo_que_se_rechaza(value: str, match: str) -> None:
    with pytest.raises(InvalidSignedRequest, match=match):
        parse_signed_request(value, ["secreto"])


def test_datos_que_no_son_json() -> None:
    encoded = _b64(b"no es json")
    signature = _b64(hmac.new(b"secreto", encoded.encode(), hashlib.sha256).digest())
    with pytest.raises(InvalidSignedRequest, match="JSON"):
        parse_signed_request(f"{signature}.{encoded}", ["secreto"])
