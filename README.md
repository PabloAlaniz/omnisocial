# omnisocial

Redes sociales con las mismas reglas: login, conexiones, activos, publicaciones, comentarios, mensajes
privados, métricas y webhooks, con un núcleo común y un adaptador por red.

[![PyPI](https://img.shields.io/pypi/v/omnisocial)](https://pypi.org/project/omnisocial/)

> La API puede cambiar entre versiones menores hasta la 1.0.

Cada producto que trabaja con redes termina escribiendo lo mismo: el diálogo de OAuth, dónde guardar el
token, cuándo renovarlo, qué páginas administra la persona, cómo leer métricas que cambian de nombre en
cada versión de la API, cómo responder un mensaje sin que la red bloquee la cuenta. `omnisocial` separa
esas reglas de cada red:

- **Un núcleo para todas las redes.** Autorizar, guardar conexiones, renovar tokens con
  compare-and-swap, descubrir activos y enrutar webhooks se hace igual para Meta que para la próxima red.
- **Capacidades, no herencia.** Cada red implementa solo lo que soporta (`login`, `assets`, `content`,
  `comments`, `messaging`, `insights`, `webhooks`, `public_profiles`). Si una red no tiene mensajes privados, el caso de uso
  lo dice con un resultado, no con una excepción a mitad de camino.
- **Resultados tipados.** Las decisiones de negocio (el `state` venció, la conexión fue revocada, pasó la
  ventana para responder) vuelven como `Refused(reason)`. Las excepciones quedan para lo que el código no
  puede decidir.
- **Webhooks con [omniwebhook](https://pypi.org/project/omniwebhook/).** Cada aviso se verifica y se
  reserva antes de procesarlo: un reintento de la red no se procesa dos veces, y si el procesamiento falla,
  el reintento entra.
- **Cualquier base, cualquier cliente HTTP.** Son puertos: hay adaptadores en memoria y para PostgreSQL, y
  un transporte con httpx.

Redes disponibles:

- **Meta**: páginas de Facebook y cuentas profesionales de Instagram. Todas las capacidades.
- **TikTok**: login, la cuenta, videos, contadores y webhooks. Sin comentarios ni mensajes, porque su API no
  los ofrece.

La arquitectura está pensada para sumar otras sin tocar el núcleo: ver [Sumar una red](docs/nueva-red.md) y
lo que ya se sabe de [YouTube, X y LinkedIn](docs/redes-pendientes.md).

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

Cada red se carga recién cuando se importa su módulo (`omnisocial.meta`, `omnisocial.tiktok`): quien usa una
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

Los tokens se renuevan solos cuando la red lo permite. Si la red rechaza un token, la conexión queda
marcada como inválida y todas las operaciones devuelven `Refused(CONNECTION_INVALID)` hasta que alguien
vuelva a conectar. Si al token le falta un permiso, la operación devuelve `Refused(MISSING_PERMISSION)` y la
conexión sigue sana.

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
await social.register_system_connection.execute(
    "meta", owner="agencia", token=Token(TokenKind.SYSTEM, os.environ["META_SYSTEM_USER_TOKEN"])
)
```

## Documentación

- [Arquitectura en capas](docs/adr/0001-arquitectura-en-capas.md)
- [Capacidades por red](docs/adr/0002-capacidades-por-red.md)
- [Webhooks con omniwebhook](docs/adr/0003-webhooks-con-omniwebhook.md)
- [Reglas estáticas de diseño](docs/adr/0004-reglas-estaticas-de-diseno.md)
- [Perfiles públicos y mirador](docs/adr/0005-perfiles-publicos-y-mirador.md)
- [Cada red paga lo suyo](docs/adr/0006-cada-red-paga-lo-suyo.md)
- [Meta: permisos, revisión de la app y lo que conviene saber](docs/meta.md)
- [TikTok: Login Kit, Display API y lo que conviene saber](docs/tiktok.md)
- [Redes pendientes: YouTube, X y LinkedIn](docs/redes-pendientes.md)
- [Sumar una red](docs/nueva-red.md)
- [Cómo se publica una versión](docs/publicar.md)

## Desarrollo

```bash
uv sync
uv run pytest                 # unitarios, con cobertura
uv run pytest -m integration  # contra PostgreSQL (OMNISOCIAL_PG_URL)
uv run ruff check . && uv run mypy && uv run lint-imports
```

## Licencia

MIT
