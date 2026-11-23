"""AES-256-GCM con rotación de claves.

Formato: `v1.<id de clave>.<base64url(nonce de 12 bytes + texto cifrado + tag)>`. El id de clave permite
rotar: se cifra con la activa y se descifra con la que diga el sobre.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from omnisocial.domain.errors import OmnisocialError

VERSION = "v1"
_NONCE_BYTES = 12


class DecryptionFailed(OmnisocialError):
    """El texto cifrado no corresponde a la clave o al contexto, o está dañado."""


def generate_key() -> str:
    """Una clave nueva de 32 bytes en base64url, para guardar en el gestor de secretos."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _decode_key(value: str | bytes) -> bytes:
    try:
        raw = value if isinstance(value, bytes) else base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        raw = b""
    if len(raw) != 32:
        raise ValueError("Cada clave tiene que tener 32 bytes (AES-256).")
    return raw


class AesGcmTokenCipher:
    def __init__(self, keys: Mapping[str, str | bytes], *, active: str) -> None:
        if active not in keys:
            raise ValueError(f"La clave activa '{active}' no está entre las claves.")
        for key_id in keys:
            if not key_id or "." in key_id:
                raise ValueError("El id de una clave no puede estar vacío ni tener puntos.")
        self._keys = {key_id: AESGCM(_decode_key(key)) for key_id, key in keys.items()}
        self._active = active

    def encrypt(self, plaintext: str, *, context: str) -> str:
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._keys[self._active].encrypt(nonce, plaintext.encode(), context.encode())
        payload = base64.urlsafe_b64encode(nonce + sealed).decode("ascii").rstrip("=")
        return f"{VERSION}.{self._active}.{payload}"

    def decrypt(self, ciphertext: str, *, context: str) -> str:
        try:
            version, key_id, payload = ciphertext.split(".", 2)
        except ValueError:
            raise DecryptionFailed("El sobre cifrado no tiene el formato esperado.") from None
        if version != VERSION:
            raise DecryptionFailed(f"Versión de sobre desconocida: {version}.")
        aead = self._keys.get(key_id)
        if aead is None:
            raise DecryptionFailed(f"No está la clave '{key_id}' para descifrar.")
        try:
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            return aead.decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], context.encode()).decode()
        except (InvalidTag, ValueError):
            raise DecryptionFailed("No se pudo descifrar: clave, contexto o datos incorrectos.") from None

    def needs_rotation(self, ciphertext: str) -> bool:
        """Lo cifró una clave que ya no es la activa."""
        parts = ciphertext.split(".", 2)
        return len(parts) != 3 or parts[1] != self._active
