<!-- Generada por scripts/sitio.py a partir del README. No editar a mano. -->

# Guía de uso

## Instalación

```bash
pip install "omnisocial[httpx,postgres,crypto,starlette]"
```

| Extra       | Para qué                                                   |
|-------------|------------------------------------------------------------|
| `httpx`     | El transporte HTTP de las redes.                           |
| `postgres`  | Guardar conexiones, activos y pedidos en PostgreSQL.       |
| `crypto`    | Cifrar los tokens con AES-256-GCM antes de guardarlos.     |
| `starlette` | Las rutas del callback y de los webhooks (sirve en FastAPI).|

Cada red se carga recién cuando se importa su módulo (`omnisocial.meta`, `omnisocial.tiktok`,
`omnisocial.youtube`, `omnisocial.linkedin`, `omnisocial.x`, `omnisocial.threads`, `omnisocial.instagram`, `omnisocial.bluesky`, `omnisocial.mastodon`, `omnisocial.pixelfed`, `omnisocial.pinterest`, `omnisocial.reddit`,
`omnisocial.google_business`, `omnisocial.whatsapp`, `omnisocial.telegram`, `omnisocial.discord`,
`omnisocial.discord_webhook`): quien usa una
sola no ejecuta el código de las otras, y ninguna suma dependencias obligatorias.

## Armado

```python
import os

from psycopg_pool import AsyncConnectionPool

from omnisocial import Omnisocial, ReturnUrlPolicy, SystemClock
from omnisocial.crypto import AesGcmTokenCipher
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.meta import MetaConfig, meta_provider
from omniwebhook.postgres import AsyncPostgresIdempotencyStore, AsyncPsycopgClient
from omnisocial.postgres import (
    PostgresAssetRepository,
    PostgresAuthorizationStateStore,
    PostgresConnectionRepository,
    PostgresPublicationRepository,
    create_schema,
)

pool = AsyncConnectionPool(os.environ["DATABASE_URL"], open=False)
cipher = AesGcmTokenCipher({"k1": os.environ["OMNISOCIAL_KEY_K1"]}, active="k1")

social = Omnisocial.build(
    providers=[
        meta_provider(
            MetaConfig(
                app_id=os.environ["META_APP_ID"],
                app_secret=os.environ["META_APP_SECRET"],
                api_version="v24.0",
                webhook_verify_token=os.environ["META_WEBHOOK_VERIFY_TOKEN"],
            ),
            RetryingTransport(HttpxTransport()),
        )
    ],
    connections=PostgresConnectionRepository(pool, cipher),
    assets=PostgresAssetRepository(pool, cipher),
    states=PostgresAuthorizationStateStore(pool, cipher, SystemClock()),
    webhook_events=AsyncPostgresIdempotencyStore(AsyncPsycopgClient(pool.connection)),
    publications=PostgresPublicationRepository(pool),
    redirect_uri_for=lambda provider: f"https://api.ejemplo.com/oauth/{provider}/callback",
    return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
)
```

La clave se genera una vez con `omnisocial.crypto.generate_key()` y va al gestor de secretos.
`create_schema(pool)` crea las tablas si no existen, incluida la de reservas de webhooks de omniwebhook.
Para probar sin base, hay almacenes en memoria (`InMemory*` y `omniwebhook.AsyncMemoryIdempotencyStore`):
sirven en un solo proceso y no sobreviven a un reinicio.

## Conectar una cuenta

El dueño de la conexión es opaco para la librería: un usuario, un proyecto, un cliente. Lo decide la app,
a partir de su propia sesión.

```python
from omnisocial import Purpose, Refused

started = await social.start_authorization.execute(
    "meta",
    purpose=Purpose.CONNECT,
    owner=f"proyecto:{project_id}",
    return_url="https://app.ejemplo.com/conexiones",
)
if isinstance(started, Refused):
    ...  # return_url no permitida, falta el dueño
redirect(started.url)
```

El callback lo resuelven las rutas de Starlette o FastAPI:

```python
from omnisocial.starlette import oauth_routes, webhook_routes

app.router.routes.extend(oauth_routes(social, on_logged_in=crear_sesion))
app.router.routes.extend(webhook_routes(social, on_events=encolar))
```

Al volver, la app recibe `?status=connected&connection_id=...` o `?status=error&reason=...`. Las páginas y
cuentas de Instagram que administra la persona ya quedaron guardadas como activos.

No todas las redes conectan con ese diálogo:

```python
# Redes federadas (Mastodon, Pixelfed): la persona dice en qué servidor está su cuenta.
started = await social.start_authorization.execute(
    "mastodon", purpose=Purpose.CONNECT, owner=owner, server="mastodon.social"
)

# Redes sin diálogo (Bluesky): una contraseña de aplicación, que se cambia por un token y no se guarda.
connected = await social.connect_with_credentials.execute(
    "bluesky", owner=owner, credentials={"identifier": "ana.bsky.social", "password": "abcd-efgh-ijkl-mnop"}
)
```

El servidor se valida antes de hacerle un pedido: tiene que ser un dominio público. Después de conectar,
todo lo demás se usa igual que en cualquier red.

## Webhooks

```python
async def encolar(events: Sequence[RoutedEvent]) -> None:
    for routed in events:
        for asset in routed.assets:  # un aviso puede ser de varios dueños
            await cola.put(asset.owner, routed.event)
```

| Llega                                   | Respuesta | `on_events`                 |
|-----------------------------------------|-----------|-----------------------------|
| Aviso firmado y nuevo                   | 200       | se llama una vez            |
| El mismo aviso otra vez                 | 200       | no se vuelve a llamar       |
| `on_events` lanza una excepción         | 500       | la red reintenta y entra    |
| Firma inválida o ausente                | 401       | no se llama                 |
| Sin secreto configurado                 | 500       | no se llama                 |

Un aviso de mensaje trae la conversación (`conversation_external_id`), los adjuntos y, si es sobre algo que
se mandó, hasta dónde llegó (`status`: enviado, entregado, leído o fallido).

La deduplicación es por entrega: si una entrega trae varios eventos y `on_events` falla, se reprocesa
entera. Conviene que lo que haga `on_events` sea idempotente por evento.

## Login con una red

El mismo flujo con `Purpose.LOGIN` no guarda nada: devuelve la identidad y la app crea su sesión.

```python
async def crear_sesion(request, result: LoggedIn) -> Response:
    user = await usuarios.por_identidad(result.identity.provider, result.identity.external_id)
    ...
```

## Usar los activos

```python
from omnisocial import CanonicalMetric, Done, InsightsRead, Period, TimeWindow

assets = await social.list_assets.execute(f"proyecto:{project_id}", provider="meta")

metrics = await social.read_insights.execute(
    page.id,
    metrics=[CanonicalMetric.FOLLOWERS, CanonicalMetric.REACH, "page_video_views"],
    period=Period.DAY,
    window=TimeWindow(since, until),
)
match metrics:
    case InsightsRead(series=series, unresolved=unresolved):
        ...  # `unresolved`: nombres comunes sin traducción para ese activo y esa versión
    case Refused(reason=reason):
        ...  # conexión vencida o revocada, red sin métricas…

posts = await social.list_posts.execute(page.id, window=TimeWindow(since, until), limit=50)
comments = await social.list_comments.execute(page.id, object_id=post_id)
await social.reply_to_comment.execute(page.id, comment_id=comment_id, text="¡Gracias!")
await social.set_comment_hidden.execute(page.id, comment_id=comment_id, hidden=True)
await social.delete_comment.execute(page.id, comment_id=comment_id)
await social.like_comment.execute(page.id, comment_id=comment_id)
# Refused(ACTION_NOT_OFFERED) si la red no ofrece la acción para ese activo (like en Instagram).

conversations = await social.list_conversations.execute(instagram.id)
sent = await social.send_message.execute(instagram.id, conversation_id=conv_id, text="Hola")
# Refused(OUTSIDE_REPLY_WINDOW) si pasaron más de 24 horas desde el último mensaje de la persona.
```

### Mensajes donde la red no guarda historial

WhatsApp y Telegram no dejan leer las conversaciones: los mensajes llegan por avisos, y para responder
hay que decir a quién. La app lo sabe porque guardó el aviso:

```python
from omnisocial import OutboundMessage, Recipient, TemplateRef

to = Recipient(event.conversation_external_id, last_inbound_at=event.occurred_at)
await social.send_message.execute(number.id, text="¡Hola!", to=to)
await social.send_message.execute(
    number.id, message=OutboundMessage("Mirá", attachments=(Media(MediaKind.IMAGE, url),)), to=to
)
# Fuera de la ventana solo sale una plantilla aprobada por la red.
template = OutboundMessage(template=TemplateRef("recordatorio", "es_AR"))
await social.send_message.execute(number.id, message=template, to=to)
```

Un mensaje que no entra en lo que acepta la red vuelve `Refused(INVALID_MESSAGE)` sin llamarla.

### La bandeja

Comentarios, mensajes y reseñas, de cualquier red, con la misma forma:

```python
from omnisocial import InboxKind, inbox_item_from_event

inbox = await social.read_inbox.execute(page.id, since=ayer)
for item in inbox.value.items:  # de lo más nuevo a lo más viejo
    item.kind, item.author_name, item.text, item.rating, item.thread_external_id

item = inbox_item_from_event(routed.event)  # lo mismo, desde un aviso; None si no es algo que escribieron
```

`read_inbox` sirve para ponerse al día: hace una llamada por publicación y otra por conversación. Lo que
llega después conviene recibirlo por avisos. Lo que no se pudo leer (un permiso que falta) viene en
`inbox.value.skipped`, y lo demás igual llega. La librería no guarda la bandeja ni sabe qué se respondió:
eso es de la app.

Los tokens se renuevan solos cuando la red lo permite. Si la red rechaza un token, la conexión queda
marcada como inválida y todas las operaciones devuelven `Refused(CONNECTION_INVALID)` hasta que alguien
vuelva a conectar. Si al token le falta un permiso, la operación devuelve `Refused(MISSING_PERMISSION)` y la
conexión sigue sana.

Lo mismo cuando la red pide bajar el ritmo o la app se quedó sin cuota: vuelve
`Refused(RATE_LIMITED, retry_after=...)` o `Refused(QUOTA_EXHAUSTED)`, y la conexión no se toca. Cada red
declara qué significa cada uno de sus códigos de error, y el núcleo decide igual para todas.

## Publicar

```python
from omnisocial import Done, Draft, Media, MediaKind, PublicationStatus, Refusal, Refused

draft = Draft(
    "Llegó el menú de invierno 🍲",
    media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/menu.jpg", alt_text="El menú"),),
    first_comment="Reservas por mensaje privado.",
)
result = await social.publish.execute(instagram.id, draft, idempotency_key=f"menu-invierno:{instagram.id}")
match result:
    case Done(value=publication) if publication.status is PublicationStatus.PENDING:
        ...  # la red la está procesando: guardar publication.id y consultarla después
    case Done(value=publication):
        ...  # PUBLISHED o PUBLISHED_WITH_ERROR: publication.post_id, publication.url
    case Refused(reason=Refusal.INVALID_DRAFT, problems=problems):
        ...  # no entra en ese activo; no se llamó a la red
    case Refused(reason=reason):
        ...  # MISSING_PERMISSION, RATE_LIMITED, QUOTA_EXHAUSTED, CONTENT_REJECTED…

later = await social.check_publication.execute(publication.id)  # retoma una pendiente
```

- **Se valida antes de llamar a la red.** Cada tipo de activo declara lo que acepta (largo del texto,
  cantidad y tipo de medios, si admite link o primer comentario). `social.validate_draft` devuelve los
  problemas sin publicar, para mostrarlos mientras alguien escribe.
- **Los medios van por URL pública (https) o como archivo**, según la red. Meta y TikTok los van a buscar
  a una URL; YouTube, LinkedIn y X piden el archivo, que se sube por partes sin cargarlo en memoria
  (`Media(MediaKind.VIDEO, file=PathFile.open("video.mp4", "video/mp4"))`). Si la subida se corta, vuelve
  `Refused(NOT_PUBLISHED)`: con certeza no salió y se puede reintentar.
- **En etapas.** Instagram, TikTok y Threads procesan los medios antes de publicar: la publicación queda `PENDING` y
  `check_publication` la retoma. Llamarlo dos veces no publica dos veces.
- **`PUBLISHED_WITH_ERROR`** quiere decir que salió, pero un paso posterior falló (el primer comentario, por
  ejemplo). No hay que repetirla.
- **Con `idempotency_key`, repetir el pedido no publica de nuevo**: devuelve la publicación que ya existe. Si
  la red dijo con certeza que no salió, la clave se libera y se puede reintentar. Si no se sabe qué pasó (la
  red no respondió), la publicación queda `STARTED`: está en duda, y la librería no la repite sola.
- **Hilos**, donde la red los tiene: `Draft("Uno", thread=(Draft("Dos"), Draft("Tres")))`. Si se corta a
  mitad de camino, lo que salió queda: `PUBLISHED_WITH_ERROR`, con la parte que falló.
- **Las opciones propias de una red** van tipadas en `options` (`TikTokOptions(privacy_level=...)`).
- **Hay redes donde hay que elegir a dónde va**: un pin va a un tablero, una publicación de Reddit a una
  comunidad. Ahí las opciones son obligatorias, y lo que se puede elegir se le pide a la red:

  ```python
  boards = await social.list_choices.execute(pinterest.id, "boards")
  flairs = await social.list_choices.execute(reddit.id, "flairs", parent="cocina")
  draft = Draft("…", media=(...), options=PinterestOptions(board_id=boards.value[0].id))
  ```

  `social.list_choices.available(asset_id)` dice qué consultas ofrece un activo.
- `social.delete_post` borra donde la red lo permite; si no, `Refused(ACTION_NOT_OFFERED)`.

Las publicaciones en curso se guardan con `publications=PostgresPublicationRepository(pool)` en
`Omnisocial.build`. Sin eso quedan en memoria: alcanza para probar, pero no sobreviven a un reinicio.

Publicar pide permisos propios, que no están en los de conexión por defecto: ver la página de cada red.
Cuándo publicar (programar, colas) es de la app; la librería publica cuando se lo piden.

## Mantener vivas las conexiones

```python
async def avisar(change: ConnectionChange) -> None:
    if change.lost:
        ...  # venció, la red rechazó el token o se desconectó: pedirle a la persona que reconecte
    if change.recovered:
        ...  # alguien reconectó


social = Omnisocial.build(..., on_connection_change=avisar)

# Desde un planificador, una vez por día:
report = await social.refresh_expiring.execute(within=timedelta(days=7))
# report.refreshed, report.lost, report.not_refreshable, report.errored
```

Un token se renueva solo cuando alguien usa la conexión. Una cuenta que nadie toca durante semanas vence
sin aviso, y en las redes que renuevan el mismo token (Threads, por ejemplo) ya no se recupera.
`refresh_expiring` renueva lo que está por vencer aunque nadie lo use, y dice cuáles no se pueden renovar
para avisarle a la persona antes. `on_connection_change` se llama con el cambio ya guardado; reconectar
conserva el id de la conexión y el de sus activos.

## Operar en producción

```python
social = Omnisocial.build(..., observer=OtelObserver())  # cada llamada a una red: cuál, qué, cómo y cuánto
reddit = reddit_provider(config, transport, rate_limits=PostgresRateLimitStore(pool))  # entre procesos
```

- **Observar**: un gancho por cada llamada a una red y otro por cada pedido HTTP, con OpenTelemetry como
  extra (`omnisocial[otel]`). Nunca sale un token, el mensaje de un error ni una ruta con ids.
- **Límites compartidos**: con un almacén, varios procesos se reparten los turnos de una red y, cuando
  la red pide esperar, esperan todos.
- **Qué tan probada está cada red**: la columna "Soporte" de la matriz. Hoy todas son experimentales:
  están probadas contra respuestas simuladas, no contra la API real.

Ver [operar en producción](operar.md).

## Cuentas ajenas

Los perfiles públicos se buscan por nombre o por URL. Instagram solo los muestra a través de una cuenta
profesional propia, que se pasa como mirador:

```python
perfil = await social.lookup_profile.execute(
    "meta", network="instagram", handle="https://www.instagram.com/marca/", viewer_asset_id=instagram.id
)
match perfil:
    case Done(value=p):
        ...  # p.external_id es la identidad estable; p.followers, p.posts, p.bio…
    case Refused(reason=Refusal.PROFILE_NOT_FOUND):
        ...  # no existe o no es una cuenta profesional
```

`omnisocial.parse_handle(network, texto)` normaliza `@marca`, URLs y variantes de las redes principales.

## Usuario de sistema

Cuando la organización administra las páginas desde su propio portfolio de la red, no hace falta que cada
dueño autorice: se registra el token del usuario de sistema y se descubren sus activos igual.

```python
result = await social.register_system_connection.execute(
    "meta", owner="agencia", token=Token(TokenKind.SYSTEM, os.environ["META_SYSTEM_USER_TOKEN"])
)
match result:
    case Connected(assets=assets):
        ...  # páginas y cuentas de Instagram que ve el token
    case Refused(reason=reason):
        ...  # PROVIDER_DENIED (token rechazado), MISSING_PERMISSION o NO_ASSETS
```

Antes de guardar el token se comprueba que sirve y que administra al menos un activo.

Para esto **no hace falta una app propia**: `MetaConfig(api_version="v24.0")` sin `app_id` ni
`app_secret` arma Meta en modo token, con todo menos OAuth y webhooks.
