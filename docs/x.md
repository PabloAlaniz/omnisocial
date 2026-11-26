# X

La cuenta de X de quien autoriza, con la API v2: posts, hilos, respuestas y contadores. La API es paga,
por uso.

## Qué cubre

| Capacidad         | Qué hace                                                                       |
|-------------------|--------------------------------------------------------------------------------|
| `login`           | OAuth 2.0 con PKCE: autorizar, canjear el código, renovar, revocar.            |
| `assets`          | La cuenta de quien autorizó es el único activo (`x_account`).                  |
| `content`         | Los posts propios, sin reposts ni respuestas, con sus contadores.              |
| `publishing`      | Un post o un hilo, con hasta 4 fotos o un video por parte. Borrar.             |
| `comments`        | Leer las respuestas a un post, responder, ocultar y dar like.                  |
| `insights`        | Contadores de la cuenta: seguidores, seguidos, posts y listas.                 |
| `public_profiles` | Cualquier cuenta por nombre, con el token de la app y sin que nadie autorice.  |

**Sin mensajes ni webhooks, por ahora.** X tiene API de mensajes privados y avisos de actividad; todavía no
se integran. Borrar la respuesta de otra cuenta no existe: se puede ocultar.

## Crear la app

1. En la [consola de desarrolladores de X](https://developer.x.com/), crear un **proyecto** con pago por uso y una **app** dentro
   de él, y cargar créditos.
2. En la configuración de autenticación de la app: **OAuth 2.0**, tipo **Web App** (cliente confidencial),
   permisos de lectura y escritura, y la URL de retorno `https://api.ejemplo.com/oauth/x/callback`.
3. Copiar el **client id** y el **client secret** de OAuth 2.0, y el **bearer token** si se van a buscar
   perfiles públicos.

Documentación oficial: [X API](https://docs.x.com/x-api/introduction) (verificado 2026-11).

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.x import CONNECT_SCOPES, MODERATE_SCOPES, PUBLISH_SCOPES, XConfig, x_provider

x = x_provider(
    XConfig(
        client_id=os.environ["X_CLIENT_ID"],
        client_secret=os.environ["X_CLIENT_SECRET"],
        bearer_token=os.environ["X_BEARER_TOKEN"],  # opcional: para perfiles públicos
        connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES + MODERATE_SCOPES,
    ),
    RetryingTransport(HttpxTransport()),
)
```

Solo con `XConfig(bearer_token=...)`, sin app, el proveedor ofrece perfiles públicos y nada más.

## Permisos

| Constante         | Permisos                                    | Para qué                                  |
|-------------------|---------------------------------------------|-------------------------------------------|
| `LOGIN_SCOPES`    | `tweet.read`, `users.read`                  | Saber quién es la persona.                |
| `CONNECT_SCOPES`  | los anteriores y `offline.access`           | Leer la cuenta y sus posts, y renovar.    |
| `PUBLISH_SCOPES`  | `tweet.write`, `media.write`                | Publicar, responder, borrar, subir medios.|
| `MODERATE_SCOPES` | `tweet.moderate.write`, `like.write`        | Ocultar respuestas y dar like.            |

## Tokens

- **El token dura dos horas** y se renueva solo, si se pidió `offline.access`.
- **El token de renovación es de un solo uso.** Cada renovación trae uno nuevo y el anterior deja de
  servir; la librería lo maneja aunque dos procesos renueven a la vez
  ([Mantener vivas las conexiones](conexiones.md)).
- **Dos sistemas con la misma app no pueden compartir una conexión**: cada uno le invalida el token de
  renovación al otro. Cada sistema necesita su propia autorización.
- La app se identifica con una cabecera (`Authorization: Basic`), no en el cuerpo del pedido.

## Publicar

```python
from omnisocial import Draft, Media, MediaKind, PathFile

draft = Draft(
    "Abrimos el local nuevo 🎉",
    media=(Media(MediaKind.IMAGE, file=PathFile.open("local.jpg", "image/jpeg"), alt_text="El frente"),),
    thread=(Draft("Estamos en Av. Siempreviva 742."), Draft("De lunes a sábado, de 9 a 20.")),
)
result = await social.publish.execute(asset_id, draft, idempotency_key="local-nuevo")
```

- **El texto se cuenta como lo cuenta X**: 280, donde una URL vale 23 sin importar su largo y los emojis y
  la escritura china, japonesa o coreana valen dos por carácter. La cuenta propia es una aproximación que
  nunca cuenta de menos: un emoji compuesto puede contar de más. Con X Premium,
  `XConfig(max_post_length=25000)` sube el tope.
- **Hasta 4 fotos, o un GIF, o un video por parte.** Siempre como archivo: X no va a buscar una URL.
  Imágenes de hasta 5 MB.
- **Los medios se suben por partes** de 3 MB. Si la subida falla, con certeza no salió:
  `Refused(NOT_PUBLISHED)`.
- **Un video queda `PENDING`** mientras X lo procesa: los medios ya están subidos y el plan de lo que falta
  crear queda guardado. `check_publication` la retoma y crea los posts cuando el video está listo.
- **Un hilo es una cadena de respuestas.** Si se corta en la parte 3, las dos primeras ya salieron: la
  publicación queda `PUBLISHED_WITH_ERROR`, con el id del primer post y el número de la parte que falló.
- **X rechaza el contenido duplicado** con un 403: vuelve `Refused(NOT_PUBLISHED)`.
- **Responder a otra cuenta** es `XOptions(reply_to="<id del post>")`. En el plan de pago por uso, X solo
  deja responder por API a quien mencionó o citó a la cuenta; si no, lo rechaza.
- Sin primer comentario (para eso está el hilo) y sin link adjunto: el link va en el texto.

## Posts, respuestas y contadores

- **Las respuestas se buscan en la conversación del post**, y la búsqueda de X solo llega a los últimos 7
  días. Las de la propia cuenta (las partes de un hilo) no se devuelven como comentarios.
- **Los contadores de la cuenta no tienen historia**: `read_insights` devuelve una foto del momento.
- **Los nombres de algunos campos están cambiando.** La documentación de X dice `tweet.fields` en las guías
  y `post.fields` en la especificación, y lo mismo con `retweet_count` / `repost_count` y `tweet_count` /
  `post_count`. Al leer se aceptan los dos; el parámetro que se envía es
  `XConfig(post_fields_param="tweet.fields")`, por si X deja de aceptar uno.

## Cuánto cuesta

**La API de X es paga y por uso**, con créditos prepagos: no hay plan gratuito ni mínimo. Los precios de
la [página de precios de X](https://docs.x.com/x-api/getting-started/pricing) (verificado 2026-11; los
vigentes están en la consola):

| Qué | Costo por unidad |
|-----|------------------|
| Leer un post propio, o los seguidores propios | USD 0,001 |
| Leer un post ajeno (una respuesta, por ejemplo) | USD 0,005 |
| Leer un usuario (un perfil público) | USD 0,010 |
| Crear un post | USD 0,015 |
| Crear un post **que tiene una URL** | USD 0,20 |
| Responder a quien mencionó a la cuenta | USD 0,010 |

- **Un link en el texto multiplica por trece el costo del post.** Conviene saberlo antes de publicar en
  cantidad.
- **Cada post leído se cobra.** `list_posts` le pasa la ventana a X para no traer de más, y conviene
  pedirlo con `limit`.
- **Sin créditos, las llamadas fallan** y vuelve `Refused(QUOTA_EXHAUSTED)`. No es el token: la conexión
  sigue sana y todo vuelve a andar al cargar créditos. Lo mismo si se llega al tope de gasto configurado.
- La app tiene que estar en un proyecto con pago por uso; si no, X responde `client-not-enrolled` y vuelve
  `Refused(MISSING_PERMISSION)`.

## Límites

Además del costo, cada endpoint tiene un límite por ventana de 15 minutos (publicar: 100 por cuenta;
leer posts propios: 900). Al llegar, X responde 429 y dice a qué hora vuelve: `Refused(RATE_LIMITED)` trae
los segundos que faltan en `retry_after`.

## Errores

| Respuesta | Resultado |
|---|---|
| 401 | La conexión queda inválida |
| 402, `usage-capped` | Sin créditos o tope de gasto: `Refused(QUOTA_EXHAUSTED)`. La conexión sigue sana |
| `client-forbidden`, `client-not-enrolled` | La app no tiene acceso (no está en un proyecto con pago por uso): `Refused(MISSING_PERMISSION)` |
| 429, `rate-limit-exceeded` | `Refused(RATE_LIMITED)`, con `retry_after` |
| 400, `invalid-request` | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |
| 403 al publicar contenido duplicado | `Refused(NOT_PUBLISHED)` |

Un 403 nunca deja la conexión inválida.

## Lo que conviene saber

- **El dominio de autorización es `x.com`**, no `twitter.com`.
- **Los errores tienen dos formas**: la nueva, con `type` y `detail`, y la vieja, con `errors[0].message`.
  El `type` puede venir con el dominio nuevo o con el viejo: se mira solo el último tramo.
- **Una cuenta que no existe o está suspendida** puede volver con 200 y sin datos, no con 404.

!!! warning "A confirmar con la API real"
    - Si la regla de "solo responder a quien mencionó a la cuenta" alcanza a las respuestas a uno mismo,
      que es lo que es un hilo.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
