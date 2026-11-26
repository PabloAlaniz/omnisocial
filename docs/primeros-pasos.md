# Primeros pasos

En cinco minutos: instalar, conectar una cuenta de Bluesky y publicar. Se eligió Bluesky porque no hace
falta registrar una app ni esperar una aprobación: alcanza con una cuenta.

Todo queda en memoria. Sirve para probar; para producción, ver [Instalar y armar](instalar-y-armar.md).

## 1. Instalar

Hace falta Python 3.11 o más nuevo.

```bash
pip install "omnisocial[httpx]"
```

## 2. Crear una contraseña de aplicación

En la configuración de Bluesky, en *Privacidad y seguridad*, la sección de contraseñas de aplicación
(*App passwords*). Es una contraseña aparte de la de la cuenta: se puede revocar sin tocar la principal.

```bash
export BLUESKY_HANDLE="tu-nombre.bsky.social"
export BLUESKY_APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"
```

## 3. Conectar y publicar

Guardar esto como `primeros_pasos.py`:

```python
import asyncio
import os

from omniwebhook import AsyncMemoryIdempotencyStore

from omnisocial import (
    Done,
    Draft,
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
    Omnisocial,
    Refused,
    ReturnUrlPolicy,
    SystemClock,
)
from omnisocial.bluesky import BlueskyConfig, bluesky_provider
from omnisocial.httpx import HttpxTransport


async def main() -> None:
    social = Omnisocial.build(
        providers=[bluesky_provider(BlueskyConfig(), HttpxTransport())],
        connections=InMemoryConnectionRepository(),
        assets=InMemoryAssetRepository(),
        states=InMemoryAuthorizationStateStore(SystemClock()),
        webhook_events=AsyncMemoryIdempotencyStore(),
        redirect_uri_for=lambda provider: f"http://localhost:8000/oauth/{provider}/callback",
        return_urls=ReturnUrlPolicy.of("http://localhost:8000"),
    )

    # 1. Conectar la cuenta con la contraseña de aplicación.
    connected = await social.connect_with_credentials.execute(
        "bluesky",
        owner="yo",
        credentials={
            "identifier": os.environ["BLUESKY_HANDLE"],
            "password": os.environ["BLUESKY_APP_PASSWORD"],
        },
    )
    if isinstance(connected, Refused):
        raise SystemExit(f"No se pudo conectar: {connected.reason}")

    # 2. Los activos de la conexión: en Bluesky, la cuenta.
    account = connected.assets[0]
    print("Conectada:", account.name)

    # 3. Publicar.
    result = await social.publish.execute(account.id, Draft("Hola desde omnisocial"))
    match result:
        case Done(value=publication):
            print("Publicado:", publication.url)
        case Refused(reason=reason):
            print("No se publicó:", reason)


asyncio.run(main())
```

```bash
python primeros_pasos.py
```

## Qué pasó

- **`Omnisocial.build`** juntó las redes (acá, solo Bluesky) con los lugares donde se guardan las
  conexiones, los activos y los avisos. Los `InMemory*` se pierden al terminar el proceso.
- **`connect_with_credentials`** cambió la contraseña de aplicación por un token, que quedó guardado en
  una **conexión** a nombre de un **dueño** (`"yo"`). La contraseña no se guarda.
- Al conectar se descubrieron los **activos**: lo que la conexión permite manejar. En Bluesky es la cuenta;
  en Meta, cada página y cada cuenta de Instagram que administra la persona.
- **`publish`** devolvió `Done` con la publicación, o `Refused` con el motivo. La librería devuelve
  `Refused` cuando la red, o la propia librería, decide que no se puede (falta un permiso, el texto es
  demasiado largo, la conexión venció). Las excepciones quedan para lo que el código no puede decidir. Ver
  [la tabla de negativas](referencia/negativas.md).

## Después

- [Instalar y armar](instalar-y-armar.md) con PostgreSQL y tokens cifrados.
- [Conectar cuentas](conectar.md) de redes con OAuth (Meta, TikTok, YouTube…).
- [Publicar](publicar-contenido.md) con imágenes, videos e hilos.
- La [página de cada red](bluesky.md) dice qué cubre y lo que conviene saber.
