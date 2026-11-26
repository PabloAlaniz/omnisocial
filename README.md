# omnisocial

Redes sociales con las mismas reglas: login, conexiones, activos, publicaciones, comentarios, mensajes
privados, métricas y webhooks, con un núcleo común y un adaptador por red.

[![PyPI](https://img.shields.io/pypi/v/omnisocial)](https://pypi.org/project/omnisocial/)
[![En vivo](https://github.com/PabloAlaniz/omnisocial/actions/workflows/en-vivo.yml/badge.svg)](https://pabloalaniz.github.io/omnisocial/pruebas-en-vivo/)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/PabloAlaniz/omnisocial/badge)](https://scorecard.dev/viewer/?uri=github.com/PabloAlaniz/omnisocial)

> La API puede cambiar entre versiones menores hasta la 1.0.

Cada producto que trabaja con redes termina escribiendo lo mismo: el diálogo de OAuth, dónde guardar el
token, cuándo renovarlo, qué páginas administra la persona, cómo leer métricas que cambian de nombre en
cada versión de la API, cómo responder un mensaje sin que la red bloquee la cuenta. `omnisocial` separa
esas reglas de cada red:

- **Un núcleo para todas las redes.** Autorizar, guardar conexiones, renovar tokens (sin perder la
  conexión aunque dos procesos renueven a la vez), descubrir activos y enrutar avisos se hace igual para
  Meta que para la próxima red.
- **Cada red, lo que tiene.** Cada red implementa solo las capacidades que soporta. Si una red no tiene
  mensajes privados, pedírselos vuelve como un resultado, no como una excepción a mitad de camino.
- **Resultados tipados.** Las decisiones de negocio (el `state` venció, la conexión fue revocada, pasó la
  ventana para responder) vuelven como `Refused(reason)`. Las excepciones quedan para lo que el código no
  puede decidir.
- **Webhooks con [omniwebhook](https://pypi.org/project/omniwebhook/).** Cada aviso se verifica y se
  reserva antes de procesarlo: un reintento de la red no se procesa dos veces, y si el procesamiento falla,
  el reintento entra.
- **Cualquier base, cualquier cliente HTTP.** El almacenamiento y el transporte son intercambiables: hay
  versiones en memoria y para PostgreSQL, y un transporte con httpx.

Redes disponibles, y qué puede hacer cada una y cada tipo de activo:

<!-- matriz:inicio (generada por scripts/matriz.py, no editar a mano) -->
| Red | Activo | Soporte | Login | Credencial | Activos | Publicaciones | Publicar | Comentarios | Mensajes | Métricas | Webhooks | Perfiles públicos |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [**Bluesky**](https://pabloalaniz.github.io/omnisocial/bluesky/) |  | experimental |  | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |
|  | `bluesky_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Discord**](https://pabloalaniz.github.io/omnisocial/discord/) |  | experimental | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
|  | `discord_guild` |  |  |  |  |  | ✓ |  |  |  |  |  |
| [**Discord (webhook)**](https://pabloalaniz.github.io/omnisocial/discord/) |  | experimental |  | ✓ | ✓ |  | ✓ |  |  |  |  |  |
|  | `discord_webhook` |  |  |  |  |  | ✓ |  |  |  |  |  |
| [**Google Business Profile**](https://pabloalaniz.github.io/omnisocial/google-business/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `google_business_location` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Instagram (login propio)**](https://pabloalaniz.github.io/omnisocial/instagram/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `instagram_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**LinkedIn**](https://pabloalaniz.github.io/omnisocial/linkedin/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `linkedin_member` |  |  |  |  |  | ✓ |  |  |  |  |  |
|  | `linkedin_organization` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Mastodon**](https://pabloalaniz.github.io/omnisocial/mastodon/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |
|  | `mastodon_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Meta**](https://pabloalaniz.github.io/omnisocial/meta/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
|  | `facebook_page` |  |  |  |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
|  | `instagram_account` |  |  |  |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| [**Pinterest**](https://pabloalaniz.github.io/omnisocial/pinterest/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ |  |  | ✓ |  |  |
|  | `pinterest_account` |  |  |  |  | ✓ | ✓ |  |  | ✓ |  |  |
| [**Pixelfed**](https://pabloalaniz.github.io/omnisocial/mastodon/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `pixelfed_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Reddit**](https://pabloalaniz.github.io/omnisocial/reddit/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  |  |  |  |
|  | `reddit_account` |  |  |  |  | ✓ | ✓ | ✓ |  |  |  |  |
| [**Telegram**](https://pabloalaniz.github.io/omnisocial/telegram/) |  | experimental |  | ✓ | ✓ |  | ✓ |  | ✓ |  | ✓ |  |
|  | `telegram_bot` |  |  |  |  |  | ✓ |  | ✓ |  | ✓ |  |
| [**Threads**](https://pabloalaniz.github.io/omnisocial/threads/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `threads_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**TikTok**](https://pabloalaniz.github.io/omnisocial/tiktok/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  |
|  | `tiktok_account` |  |  |  |  | ✓ | ✓ |  |  | ✓ |  |  |
| [**WhatsApp Business**](https://pabloalaniz.github.io/omnisocial/whatsapp/) |  | experimental | ✓ |  | ✓ |  |  |  | ✓ |  | ✓ |  |
|  | `whatsapp_number` |  |  |  |  |  |  |  | ✓ |  | ✓ |  |
| [**X**](https://pabloalaniz.github.io/omnisocial/x/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |
|  | `x_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**YouTube**](https://pabloalaniz.github.io/omnisocial/youtube/) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |
|  | `youtube_channel` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
<!-- matriz:fin -->

Instagram está dos veces: a través de una página de Facebook (dentro de Meta, con todo) o con su login
propio, sin página ([cuál conviene](https://pabloalaniz.github.io/omnisocial/instagram/)).

La fila de la red dice lo que ofrece; la de cada activo, lo que ese activo habilita. Lo que falta es
porque la API de la red no lo ofrece (TikTok no tiene comentarios ni mensajes; LinkedIn y Threads no
tienen mensajes) o porque todavía no se integró (los mensajes de X; los avisos de YouTube, LinkedIn y X).
"Soporte" dice qué tan probada está cada red: ver
[niveles de soporte](https://pabloalaniz.github.io/omnisocial/niveles-de-soporte/).

Sumar otra red no toca el núcleo: un comando crea el esqueleto de una red que ya pasa el contrato común.
Ver [Sumar una red](https://pabloalaniz.github.io/omnisocial/nueva-red/) y la
[hoja de ruta](https://pabloalaniz.github.io/omnisocial/hoja-de-ruta/).

## Instalación

Python 3.11 a 3.14.

```bash
pip install "omnisocial[httpx]"                              # lo mínimo
pip install "omnisocial[httpx,postgres,crypto,starlette]"    # para producción
```

Qué trae cada extra está en [Instalar y armar](https://pabloalaniz.github.io/omnisocial/instalar-y-armar/).

## Un ejemplo

Conectar una cuenta de Bluesky y publicar, con todo en memoria. Bluesky no pide registrar una app: alcanza
con una [contraseña de aplicación](https://pabloalaniz.github.io/omnisocial/primeros-pasos/#2-crear-una-contrasena-de-aplicacion).

```python
import asyncio
import os

from omniwebhook import AsyncMemoryIdempotencyStore

from omnisocial import (
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
    connected = await social.connect_with_credentials.execute(
        "bluesky",
        owner="yo",
        credentials={
            "identifier": os.environ["BLUESKY_HANDLE"],
            "password": os.environ["BLUESKY_APP_PASSWORD"],
        },
    )
    if isinstance(connected, Refused):
        raise SystemExit(connected.reason)

    account = connected.assets[0]
    print(await social.publish.execute(account.id, Draft("Hola desde omnisocial")))


asyncio.run(main())
```

El paso a paso, con lo que pasó en cada línea, está en [Primeros pasos](https://pabloalaniz.github.io/omnisocial/primeros-pasos/).

## Documentación

En **[pabloalaniz.github.io/omnisocial](https://pabloalaniz.github.io/omnisocial/)**:

- [Primeros pasos](https://pabloalaniz.github.io/omnisocial/primeros-pasos/) y [guías](https://pabloalaniz.github.io/omnisocial/instalar-y-armar/): instalar, conectar cuentas,
  publicar, comentarios y mensajes, métricas, avisos y operar en producción.
- [Una página por red](https://pabloalaniz.github.io/omnisocial/meta/): cómo crear la app, permisos, límites y lo que conviene saber.
- [Negativas y errores](https://pabloalaniz.github.io/omnisocial/referencia/negativas/) y [glosario](https://pabloalaniz.github.io/omnisocial/referencia/glosario/).
- [Decisiones de diseño](https://pabloalaniz.github.io/omnisocial/adr/0001-arquitectura-en-capas/).

También: [CHANGELOG](CHANGELOG.md), [cómo contribuir](CONTRIBUTING.md) y [seguridad](SECURITY.md).

## Licencia

MIT
