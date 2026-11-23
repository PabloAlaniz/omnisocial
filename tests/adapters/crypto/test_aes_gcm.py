import pytest

from omnisocial.adapters.crypto.aes_gcm import AesGcmTokenCipher, DecryptionFailed, generate_key

K1 = generate_key()
K2 = generate_key()


def test_ida_y_vuelta() -> None:
    cipher = AesGcmTokenCipher({"k1": K1}, active="k1")
    sealed = cipher.encrypt("token-secreto", context="connection|c1")
    assert sealed.startswith("v1.k1.")
    assert "token-secreto" not in sealed
    assert cipher.decrypt(sealed, context="connection|c1") == "token-secreto"
    assert cipher.encrypt("x", context="c") != cipher.encrypt("x", context="c")


def test_el_contexto_ata_el_token_a_su_fila() -> None:
    cipher = AesGcmTokenCipher({"k1": K1}, active="k1")
    sealed = cipher.encrypt("token", context="connection|c1")
    with pytest.raises(DecryptionFailed, match="contexto"):
        cipher.decrypt(sealed, context="connection|c2")


def test_rotacion_de_claves() -> None:
    old = AesGcmTokenCipher({"k1": K1}, active="k1")
    sealed = old.encrypt("token", context="c")
    rotated = AesGcmTokenCipher({"k1": K1, "k2": K2}, active="k2")
    assert rotated.decrypt(sealed, context="c") == "token"
    assert rotated.needs_rotation(sealed)
    assert not rotated.needs_rotation(rotated.encrypt("token", context="c"))
    assert rotated.needs_rotation("roto")


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("roto", "formato"),
        ("v2.k1.abc", "Versión"),
        ("v1.k9.abc", "clave 'k9'"),
        ("v1.k1.%%%", "descifrar"),
        ("v1.k1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "descifrar"),
    ],
)
def test_sobres_invalidos(value: str, message: str) -> None:
    with pytest.raises(DecryptionFailed, match=message):
        AesGcmTokenCipher({"k1": K1}, active="k1").decrypt(value, context="c")


def test_validaciones_de_configuracion() -> None:
    with pytest.raises(ValueError, match="activa"):
        AesGcmTokenCipher({"k1": K1}, active="k2")
    with pytest.raises(ValueError, match="32 bytes"):
        AesGcmTokenCipher({"k1": "corta"}, active="k1")
    with pytest.raises(ValueError, match="puntos"):
        AesGcmTokenCipher({"k.1": K1}, active="k.1")
    assert AesGcmTokenCipher({"k1": bytes(32)}, active="k1").encrypt("x", context="c")
