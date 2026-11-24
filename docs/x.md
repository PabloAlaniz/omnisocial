# X: API v2, pago por uso y lo que conviene saber

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

## Armado

```python
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

## Cuánto cuesta

**La API de X es paga y por uso**, con créditos prepagos: no hay plan gratuito ni mínimo. Los precios que
publica X al momento de escribir esto (conviene confirmarlos en su página):

| Qué | Costo por unidad |
|-----|------------------|
| Leer un post propio, o los seguidores propios | USD 0,001 |
| Leer un post ajeno (una respuesta, por ejemplo) | USD 0,005 |
| Leer un usuario (un perfil público) | USD 0,010 |
| Crear un post | USD 0,015 |
| Crear un post **que tiene una URL** | USD 0,20 |
| Responder a quien mencionó a la cuenta | USD 0,01 |

- **Un link en el texto multiplica por trece el costo del post.** Conviene saberlo antes de publicar en
  cantidad.
- **Cada post leído se cobra.** `list_posts` le pasa la ventana a X para no traer de más, y conviene
  pedirlo con `limit`.
- **Sin créditos, las llamadas fallan** y vuelve `Refused(QUOTA_EXHAUSTED)`. No es el token: la conexión
  sigue sana y todo vuelve a andar al cargar créditos. Lo mismo si se llega al tope de gasto configurado.
- La app tiene que estar en un proyecto con pago por uso; si no, X responde `client-not-enrolled` y vuelve
  `Refused(MISSING_PERMISSION)`.

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
  servir. La librería lo guarda con compare-and-swap: si dos procesos renuevan a la vez, el que pierde usa
  el token que guardó el otro.
- **Dos sistemas con la misma app no pueden compartir una conexión**: cada uno le invalida el token de
  renovación al otro. Cada sistema necesita su propia autorización.
- La app se identifica con una cabecera (`Authorization: Basic`), no en el cuerpo del pedido.
- **Un 401 deja la conexión inválida. Un 402 o un 403, nunca.**

## Publicar

```python
from omnisocial import Draft, Media, MediaKind, PathFile

draft = Draft(
    "Abrimos el local nuevo 🎉",
    media=(Media(MediaKind.IMAGE, file=PathFile.open("local.jpg", "image/jpeg"), alt_text="El frente"),),
    thread=(Draft("Estamos en Av. Siempreviva 742."), Draft("De lunes a sábado, de 9 a 20.")),
)
result = await social.publish.execute(account.id, draft, idempotency_key="local-nuevo")
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
  deja responder por API a quien mencionó o citó a la cuenta; si no, lo rechaza. No se pudo confirmar si
  esa regla alcanza a las respuestas a uno mismo, que es lo que es un hilo: es lo primero a probar con una
  cuenta real.
- Sin primer comentario (para eso está el hilo) y sin link adjunto: el link va en el texto.

## Posts, respuestas y contadores

- **Las respuestas se buscan en la conversación del post**, y la búsqueda de X solo llega a los últimos 7
  días. Las de la propia cuenta (las partes de un hilo) no se devuelven como comentarios.
- **Los contadores de la cuenta no tienen historia**: `read_insights` devuelve una foto del momento.
- **Los nombres de algunos campos están cambiando.** La documentación de X dice `tweet.fields` en las guías
  y `post.fields` en la especificación, y lo mismo con `retweet_count` / `repost_count` y `tweet_count` /
  `post_count`. Al leer se aceptan los dos; el parámetro que se envía es
  `XConfig(post_fields_param="tweet.fields")`, por si X deja de aceptar uno.

## Límites

Además del costo, cada endpoint tiene un límite por ventana de 15 minutos (publicar: 100 por cuenta;
leer posts propios: 900). Al llegar, X responde 429 y dice a qué hora vuelve: `Refused(RATE_LIMITED)` trae
los segundos que faltan en `retry_after`.

## Lo que conviene saber

- **El dominio de autorización es `x.com`**, no `twitter.com`.
- **Los errores tienen dos formas**: la nueva, con `type` y `detail`, y la vieja, con `errors[0].message`.
  El `type` puede venir con el dominio nuevo o con el viejo: se mira solo el último tramo.
- **Una cuenta que no existe o está suspendida** puede volver con 200 y sin datos, no con 404.
- Guardar el id de la cuenta, no el nombre: el nombre de usuario cambia.
