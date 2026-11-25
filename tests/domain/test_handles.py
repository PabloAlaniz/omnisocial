from __future__ import annotations

import pytest

from omnisocial.domain.handles import Handle, HandleKind, Network, parse_handle


@pytest.mark.parametrize(
    ("network", "raw", "expected"),
    [
        ("instagram", "@Marca.Oficial", "marca.oficial"),
        ("instagram", "https://www.instagram.com/marca_ok/?hl=es", "marca_ok"),
        ("instagram", "instagram.com/marca/reels/", "marca"),
        ("facebook", "https://m.facebook.com/MiPagina", "mipagina"),
        ("facebook", "facebook.com/profile.php?id=100064", "100064"),
        ("tiktok", "marca", "@marca"),
        ("tiktok", "https://www.tiktok.com/@Marca?lang=es", "@marca"),
        ("youtube", "https://youtube.com/@Canal", "@canal"),
        ("youtube", "youtube.com/user/ViejoUsuario", "viejousuario"),
        ("youtube", "youtube.com/c/Nombre/videos", "nombre"),
        ("x", "https://twitter.com/Marca/status/1", "marca"),
        ("x", "@marca_ar", "marca_ar"),
        ("linkedin", "https://www.linkedin.com/company/mi-empresa/", "mi-empresa"),
        ("linkedin", "linkedin.com/in/persona", "persona"),
        # Una barra codificada no termina dentro del nombre.
        ("instagram", "https://www.instagram.com/marca%2Fposts", "marca"),
    ],
)
def test_normaliza(network: str, raw: str, expected: str) -> None:
    handle = parse_handle(network, raw)
    assert handle is not None
    assert str(handle) == expected


def test_los_ids_estables_se_marcan() -> None:
    channel = "UCabcdefghijklmnopqrstuv"
    assert parse_handle(Network.YOUTUBE, f"https://www.youtube.com/channel/{channel}") == Handle(
        Network.YOUTUBE, channel, HandleKind.ID
    )
    numeric = parse_handle("facebook", "100064")
    assert numeric is not None
    assert numeric.kind is HandleKind.ID


@pytest.mark.parametrize(
    ("network", "raw"),
    [
        ("instagram", ""),
        ("instagram", "https://otro.com/marca"),
        ("instagram", "https://instagram.com/"),
        ("instagram", "con espacio"),
        ("x", "un_nombre_demasiado_largo"),
        ("tiktok", "@a"),
        ("facebook", "https://facebook.com/profile.php"),
    ],
)
def test_lo_que_no_es_una_cuenta(network: str, raw: str) -> None:
    assert parse_handle(network, raw) is None


def test_una_red_desconocida_es_un_error() -> None:
    with pytest.raises(ValueError, match="myspace"):
        parse_handle("myspace", "marca")


@pytest.mark.parametrize(
    ("network", "raw", "value", "kind"),
    [
        (Network.MASTODON, "@Ana@Mastodon.Social", "ana@mastodon.social", HandleKind.USERNAME),
        (Network.MASTODON, "ana@mastodon.social", "ana@mastodon.social", HandleKind.USERNAME),
        (Network.MASTODON, "https://mastodon.social/@ana", "ana@mastodon.social", HandleKind.USERNAME),
        (Network.BLUESKY, "@ana.bsky.social", "ana.bsky.social", HandleKind.USERNAME),
        (Network.BLUESKY, "https://bsky.app/profile/ana.ejemplo.com", "ana.ejemplo.com", HandleKind.USERNAME),
        (Network.BLUESKY, "did:plc:abc123", "did:plc:abc123", HandleKind.ID),
        (Network.BLUESKY, "https://bsky.app/profile/did:plc:abc123", "did:plc:abc123", HandleKind.ID),
        (Network.THREADS, "https://www.threads.com/@mi.marca", "mi.marca", HandleKind.USERNAME),
    ],
)
def test_nombres_de_redes_federadas(network: Network, raw: str, value: str, kind: HandleKind) -> None:
    handle = parse_handle(network, raw)
    assert handle is not None
    assert (handle.network, handle.value, handle.kind) == (network, value, kind)


@pytest.mark.parametrize(
    ("network", "raw"),
    [
        # En Mastodon el nombre lleva el servidor: sin él no se sabe dónde buscar.
        (Network.MASTODON, "ana"),
        (Network.MASTODON, "ana@localhost"),
        (Network.MASTODON, "ana@127.0.0.1"),
        (Network.MASTODON, "https://mastodon.social/about"),
        (Network.MASTODON, "an a@mastodon.social"),
        (Network.BLUESKY, "ana"),
        (Network.BLUESKY, "https://ejemplo.com/profile/ana.bsky.social"),
        (Network.BLUESKY, "https://bsky.app/"),
    ],
)
def test_lo_que_no_es_un_nombre_de_una_red_federada(network: Network, raw: str) -> None:
    assert parse_handle(network, raw) is None
