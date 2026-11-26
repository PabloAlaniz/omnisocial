<!-- Generada por scripts/sitio.py a partir del README. No editar a mano. -->

# omnisocial

Redes sociales con las mismas reglas: login, conexiones, activos, publicaciones, comentarios, mensajes
privados, métricas y webhooks, con un núcleo común y un adaptador por red.

[![PyPI](https://img.shields.io/pypi/v/omnisocial)](https://pypi.org/project/omnisocial/)
[![En vivo](https://github.com/PabloAlaniz/omnisocial/actions/workflows/en-vivo.yml/badge.svg)](pruebas-en-vivo.md)
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
| [**Bluesky**](bluesky.md) |  | experimental |  | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |
|  | `bluesky_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Discord**](discord.md) |  | experimental | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
|  | `discord_guild` |  |  |  |  |  | ✓ |  |  |  |  |  |
| [**Discord (webhook)**](discord.md) |  | experimental |  | ✓ | ✓ |  | ✓ |  |  |  |  |  |
|  | `discord_webhook` |  |  |  |  |  | ✓ |  |  |  |  |  |
| [**Google Business Profile**](google-business.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `google_business_location` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Instagram (login propio)**](instagram.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `instagram_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**LinkedIn**](linkedin.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `linkedin_member` |  |  |  |  |  | ✓ |  |  |  |  |  |
|  | `linkedin_organization` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Mastodon**](mastodon.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |
|  | `mastodon_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Meta**](meta.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
|  | `facebook_page` |  |  |  |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
|  | `instagram_account` |  |  |  |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| [**Pinterest**](pinterest.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ |  |  | ✓ |  |  |
|  | `pinterest_account` |  |  |  |  | ✓ | ✓ |  |  | ✓ |  |  |
| [**Pixelfed**](mastodon.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `pixelfed_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**Reddit**](reddit.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  |  |  |  |
|  | `reddit_account` |  |  |  |  | ✓ | ✓ | ✓ |  |  |  |  |
| [**Telegram**](telegram.md) |  | experimental |  | ✓ | ✓ |  | ✓ |  | ✓ |  | ✓ |  |
|  | `telegram_bot` |  |  |  |  |  | ✓ |  | ✓ |  | ✓ |  |
| [**Threads**](threads.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |
|  | `threads_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**TikTok**](tiktok.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  |
|  | `tiktok_account` |  |  |  |  | ✓ | ✓ |  |  | ✓ |  |  |
| [**WhatsApp Business**](whatsapp.md) |  | experimental | ✓ |  | ✓ |  |  |  | ✓ |  | ✓ |  |
|  | `whatsapp_number` |  |  |  |  |  |  |  | ✓ |  | ✓ |  |
| [**X**](x.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |
|  | `x_account` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
| [**YouTube**](youtube.md) |  | experimental | ✓ |  | ✓ | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |
|  | `youtube_channel` |  |  |  |  | ✓ | ✓ | ✓ |  | ✓ |  |  |
<!-- matriz:fin -->

Instagram está dos veces: a través de una página de Facebook (dentro de Meta, con todo) o con su login
propio, sin página ([cuál conviene](instagram.md)).

La fila de la red dice lo que ofrece; la de cada activo, lo que ese activo habilita. Lo que falta es
porque la API de la red no lo ofrece (TikTok no tiene comentarios ni mensajes; LinkedIn y Threads no
tienen mensajes) o porque todavía no se integró (los mensajes de X; los avisos de YouTube, LinkedIn y X).
"Soporte" dice qué tan probada está cada red: ver
[niveles de soporte](niveles-de-soporte.md).

Sumar otra red no toca el núcleo: un comando crea el esqueleto de una red que ya pasa el contrato común.
Ver [Sumar una red](nueva-red.md) y la
[hoja de ruta](hoja-de-ruta.md).
