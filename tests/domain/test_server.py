from __future__ import annotations

import pytest

from omnisocial.domain.server import normalize_server


@pytest.mark.parametrize(
    ("text", "host"),
    [
        ("mastodon.social", "mastodon.social"),
        ("  https://Mastodon.Social/  ", "mastodon.social"),
        ("social.ejemplo.com.ar", "social.ejemplo.com.ar"),
        ("xn--espaa-rta.social", "xn--espaa-rta.social"),
    ],
)
def test_un_servidor_publico(text: str, host: str) -> None:
    assert normalize_server(text) == host


@pytest.mark.parametrize(
    "text",
    [
        "",
        "localhost",
        "interno",
        "http://mastodon.social",
        "mastodon.social:8443",
        "mastodon.social/api/v1",
        "user@mastodon.social",
        "127.0.0.1",
        "10.0.0.8",
        "169.254.169.254",
        "[::1]",
        "servidor.local",
        "metadata.internal",
        "algo.localhost",
        "-malo.social",
        "malo-.social",
        "a" * 250 + ".social",
        "mastodon.social#x",
        "mastodon.social?x=1",
        "mastodon..social",
    ],
)
def test_lo_que_no_es_un_servidor_publico(text: str) -> None:
    assert normalize_server(text) is None
