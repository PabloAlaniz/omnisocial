"""El armazón de las pruebas en vivo funciona para todas las redes, sin llamar a ninguna."""

from __future__ import annotations

import json
import pkgutil
import sys
from pathlib import Path

import pytest

from omnisocial.adapters import providers
from omnisocial.domain.token import TokenKind
from omnisocial.testing import FakeTransport
from tests.live.armado import NETWORKS, build, options, parse, variable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from matriz import specs as matrix_specs  # noqa: E402  # el script vive fuera del paquete

# Lo mínimo que cada red exige para armarse. Los valores son de mentira.
MINIMAL: dict[str, dict[str, object]] = {
    "meta": {"api_version": "v25.0", "app_id": "app", "app_secret": "secreto"},
    "instagram": {"client_id": "app", "client_secret": "secreto", "api_version": "v24.0"},
    "tiktok": {"client_key": "app", "client_secret": "secreto"},
    "youtube": {"client_id": "app", "client_secret": "secreto"},
    "linkedin": {"client_id": "app", "client_secret": "secreto", "api_version": "202611"},
    "x": {"client_id": "app", "client_secret": "secreto"},
    "threads": {"client_id": "app", "client_secret": "secreto"},
    "bluesky": {},
    "mastodon": {"client_name": "Prueba"},
    "pixelfed": {"client_name": "Prueba"},
    "pinterest": {"client_id": "app", "client_secret": "secreto"},
    "reddit": {"client_id": "app", "client_secret": "secreto", "user_agent": "web:prueba:1.0 (by /u/prueba)"},
    "google_business": {"client_id": "app", "client_secret": "secreto"},
    "whatsapp": {"app_id": "app", "app_secret": "secreto"},
    "telegram": {},
    "discord": {
        "client_id": "app",
        "client_secret": "secreto",
        "bot_token": "token",
        "app_url": "https://ejemplo.com",
    },
    "discord_webhook": {"app_url": "https://ejemplo.com"},
}


def test_estan_todas_las_redes_del_paquete() -> None:
    assert sorted(NETWORKS) == sorted(str(spec.id) for spec in matrix_specs())
    packages = {module.name for module in pkgutil.iter_modules(providers.__path__) if module.ispkg}
    assert packages <= set(NETWORKS)


@pytest.mark.parametrize("network", NETWORKS)
def test_cada_red_se_arma_desde_su_variable(network: str) -> None:
    raw = json.dumps({"config": MINIMAL[network], "token": {"access_token": "acceso"}})
    setup = parse(network, raw)
    provider = build(setup, FakeTransport())
    assert provider.id == network
    assert provider.spec is not None
    # El armado no muestra nada de lo que trae.
    assert "acceso" not in repr(setup)
    assert "secreto" not in repr(setup)


def test_el_token_las_credenciales_y_las_opciones() -> None:
    assert variable("google_business") == "OMNISOCIAL_LIVE_GOOGLE_BUSINESS"
    token = {
        "access_token": "a",
        "refresh_token": "r",
        "server": "mastodon.social",
        "scopes": ["read", "write"],
        "expires_at": "2027-01-01T00:00:00+00:00",
        "kind": "system",
    }
    setup = parse("mastodon", json.dumps({"token": token}))
    assert setup.token is not None
    assert (setup.token.kind, setup.token.refresh_token, setup.token.server, setup.token.scopes) == (
        TokenKind.SYSTEM,
        "r",
        "mastodon.social",
        frozenset({"read", "write"}),
    )
    assert setup.token.expires_at is not None
    by_credential = parse(
        "telegram",
        json.dumps({"credentials": {"token": "1:abc"}, "write": {"options": {"chat_id": "@canal"}}}),
    )
    assert by_credential.credentials == {"token": "1:abc"}
    built = options(by_credential)
    assert built is not None
    assert getattr(built, "chat_id", None) == "@canal"
    assert options(setup) is None
    # Las listas de la configuración pasan a ser tuplas, que es lo que esperan las configuraciones.
    scoped = parse(
        "reddit",
        json.dumps(
            {"config": {**MINIMAL["reddit"], "connect_scopes": ["identity"]}, "token": {"access_token": "a"}}
        ),
    )
    assert build(scoped, FakeTransport()).id == "reddit"


@pytest.mark.parametrize(
    ("raw", "error", "message"),
    [
        ("[]", TypeError, "objeto JSON"),
        ("{}", ValueError, "una de las dos"),
        ('{"token": {"access_token": "a"}, "credentials": {"x": "y"}}', ValueError, "una de las dos"),
    ],
)
def test_un_armado_mal_escrito_se_dice_sin_mostrar_su_contenido(
    raw: str, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        parse("meta", raw)


def test_las_redes_verificadas_estan_en_la_corrida_nocturna() -> None:
    workflow = (ROOT / ".github" / "workflows" / "en-vivo.yml").read_text(encoding="utf-8")
    for spec in matrix_specs():
        if spec.support == "verified":
            assert f"- {spec.id}\n" in workflow, f"{spec.name} se declara verificada y no se prueba en vivo."
    for network in NETWORKS:
        assert f"- {network}\n" in workflow, f"{network} no está en la corrida nocturna."
