# Conectar cuentas

Una **conexión** es una autorización guardada: el token que una persona le dio a la app para usar su
cuenta en una red. Pertenece a un **dueño**, que para la librería es opaco: un usuario, un proyecto, un
cliente. Lo decide la app, a partir de su propia sesión.

Al conectar se descubren los **activos**: lo que esa conexión permite manejar. Una conexión de Meta trae
cada página y cada cuenta de Instagram que administra la persona; una de YouTube, el canal. Casi todo lo
demás (publicar, leer comentarios, métricas) se hace sobre un activo.

Hay cuatro formas de conectar, según la red:

| Forma | Cuándo | Redes |
|---|---|---|
| [Con el diálogo de la red (OAuth)](#con-el-dialogo-de-la-red) | La persona autoriza en la página de la red | La mayoría |
| [En un servidor federado](#en-un-servidor-federado) | OAuth, pero la persona dice en qué servidor está | Mastodon, Pixelfed |
| [Con una credencial](#con-una-credencial) | La red no tiene diálogo: se carga una contraseña o un token | Bluesky, Telegram, Discord (webhook) |
| [Con un usuario de sistema](#con-un-usuario-de-sistema) | La organización ya tiene un token propio | Meta |

Los ejemplos suponen un `social` armado como en [Instalar y armar](instalar-y-armar.md).

## Con el diálogo de la red

```python
from omnisocial import Purpose, Refused

started = await social.start_authorization.execute(
    "meta",
    purpose=Purpose.CONNECT,
    owner="proyecto:42",
    return_url="https://app.ejemplo.com/conexiones",
)
if isinstance(started, Refused):
    ...  # RETURN_URL_NOT_ALLOWED u OWNER_REQUIRED
else:
    ...  # redirigir a la persona a started.url
```

La persona autoriza en la red, y la red vuelve al callback (`redirect_uri_for`). Las
[rutas de Starlette](instalar-y-armar.md#las-rutas-web) lo resuelven y vuelven a `return_url` con:

- `?status=connected&connection_id=...`: la conexión y sus activos ya quedaron guardados.
- `?status=error&reason=...`: el motivo es una de las [negativas](referencia/negativas.md), por ejemplo
  `provider_denied` si la persona canceló.

Sin Starlette, el callback se completa a mano con
`social.complete_authorization.execute(state=..., code=..., error=...)`, que devuelve `Connected` o
`Refused`.

Volver a conectar una cuenta que ya estaba conectada conserva el id de la conexión y los de sus activos.

## En un servidor federado

En Mastodon y Pixelfed cada servidor es independiente: la app se registra sola en cada uno la primera vez
que alguien de ese servidor conecta, y ese registro se guarda. Por eso esas redes se arman con un almacén
de apps:

```python
from omnisocial.httpx import HttpxTransport
from omnisocial.mastodon import MastodonConfig, mastodon_provider
from omnisocial.postgres import PostgresServerAppStore

mastodon = mastodon_provider(
    MastodonConfig(client_name="Mi app"),
    HttpxTransport(),
    apps=PostgresServerAppStore(pool, cipher),
)
```

Al autorizar, se dice en qué servidor está la cuenta:

```python
started = await social.start_authorization.execute(
    "mastodon", purpose=Purpose.CONNECT, owner="proyecto:42", server="mastodon.social"
)
```

Antes de hacerle un pedido, se valida que el servidor sea un dominio público: si no, vuelve
`Refused(INVALID_SERVER)`. Detalles en [Mastodon y Pixelfed](mastodon.md).

## Con una credencial

Las redes sin diálogo de autorización piden un dato que la persona saca de la red:

```python
from omnisocial import Connected, Refused

connected = await social.connect_with_credentials.execute(
    "bluesky",
    owner="proyecto:42",
    credentials={"identifier": "ana.bsky.social", "password": "abcd-efgh-ijkl-mnop"},
)
match connected:
    case Connected(connection=connection, assets=assets):
        ...
    case Refused(reason=reason, detail=detail):
        ...  # CREDENTIALS_REQUIRED (detail dice cuál falta), PROVIDER_DENIED…
```

| Red | Credencial |
|---|---|
| Bluesky | `identifier` y `password` (una contraseña de aplicación, que se cambia por un token y no se guarda) |
| Telegram | `token` del bot |
| Discord (webhook) | `webhook_url` |

Qué pide cada una está en su página.

## Con un usuario de sistema

Cuando la organización administra las páginas desde su propio portfolio en Meta, no hace falta que cada
persona autorice: se registra el token del usuario de sistema y sus activos se descubren igual.

```python
import os

from omnisocial import Connected, Refused, Token, TokenKind

result = await social.register_system_connection.execute(
    "meta", owner="agencia", token=Token(TokenKind.SYSTEM, os.environ["META_SYSTEM_USER_TOKEN"])
)
match result:
    case Connected(assets=assets):
        ...  # las páginas y cuentas de Instagram que ve el token
    case Refused(reason=reason):
        ...  # PROVIDER_DENIED (token rechazado), MISSING_PERMISSION o NO_ASSETS
```

Antes de guardar el token se comprueba que sirve y que administra al menos un activo.

Para esto no hace falta una app propia: `MetaConfig(api_version="v24.0")` sin `app_id` ni `app_secret`
arma Meta en **modo token**, con todo menos OAuth y avisos. Ver [Meta](meta.md).

## Usar los activos

```python
assets = await social.list_assets.execute("proyecto:42", provider="meta")
for asset in assets:
    asset.id, asset.kind, asset.name  # asset.id es lo que piden las demás operaciones
```

Si la persona sumó una página después de conectar, `social.sync_assets.execute(connection_id)` vuelve a
descubrirlos.

## Desconectar

```python
await social.disconnect.execute(connection_id)
```

Revoca el token en la red cuando la red lo permite (`revoke_remote=False` para no hacerlo) y marca la
conexión como desconectada.
