# Meta

Páginas de Facebook y cuentas de Instagram conectadas a ellas, con una sola app de Meta.

## Qué cubre

| Capacidad | Página de Facebook | Cuenta de Instagram |
|-----------|--------------------|---------------------|
| Login (Facebook Login) | sí | — |
| Activos (`me/accounts`) | sí | sí, la conectada a cada página |
| Publicaciones | `/{page}/posts` | `/{ig}/media` |
| Publicar | sí | sí, en etapas |
| Comentarios: leer, responder, ocultar | sí | sí |
| Mensajes privados | Messenger | Instagram Direct, por la página |
| Métricas | `/{page}/insights` | `/{ig}/insights` |
| Avisos | `feed`, `messages` | `comments`, `mentions`, `messages` |
| Perfiles públicos | — | sí, con una cuenta propia como mirador |

Las cuentas de Instagram usan el token de su página: en el flujo de Facebook Login no existen tokens
propios de Instagram. Para una cuenta de Instagram sin página, ver
[Instagram con login propio](instagram.md).

## Antes de empezar

- Una **cuenta de Meta para desarrolladores** y un **portfolio comercial** (Business Manager).
- Las **páginas de Facebook** que se van a administrar. Cada cuenta de Instagram tiene que ser profesional
  (empresa o creador) y estar conectada a una página.
- Para usar la app con cuentas ajenas: **verificación del negocio** y **revisión de la app** (ver
  [Permisos](#permisos)). Mientras tanto se puede trabajar en [modo token](#modo-token-sin-app).

## Crear la app

1. En [developers.facebook.com/apps](https://developers.facebook.com/apps), *Crear app*, del tipo
   **Empresa**, asociada al portfolio.
2. Agregar los productos **Facebook Login para empresas** y, si se usan avisos, **Webhooks**.
3. En *Facebook Login → Configuración*, cargar la URL de retorno: `https://api.ejemplo.com/oauth/meta/callback`
   (la que devuelve `redirect_uri_for("meta")`).
4. En *Configuración → Básica*, copiar el **ID de la app** y la **clave secreta**.
5. En *Configuración → Avanzada*, activar **Require App Secret**: cada llamada va firmada con
   `appsecret_proof`.

Documentación oficial: [Facebook Login](https://developers.facebook.com/docs/facebook-login/) y
[Graph API](https://developers.facebook.com/docs/graph-api/) (verificado 2026-11).

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.meta import MetaConfig, meta_provider

meta = meta_provider(
    MetaConfig(
        api_version="v26.0",
        app_id=os.environ["META_APP_ID"],
        app_secret=os.environ["META_APP_SECRET"],
        webhook_verify_token=os.environ["META_WEBHOOK_VERIFY_TOKEN"],
    ),
    RetryingTransport(HttpxTransport()),
)
```

La versión de la Graph API se fija a propósito: Meta saca una cada pocos meses, retira cada una a los dos
años y entre versiones cambian métricas y campos. La última es la
[v26.0, de julio de 2026](https://developers.facebook.com/docs/graph-api/changelog/versions/)
(verificado 2026-11). Conviene subirla a conciencia, revisando el changelog.

## Conectar

Con el diálogo de Facebook Login, como en [Conectar cuentas](conectar.md#con-el-dialogo-de-la-red). Al
conectar se guardan como activos cada página que administra la persona y la cuenta de Instagram de cada
una.

### Modo token (sin app)

Mientras no hay una app con acceso avanzado (o mientras la verificación del negocio está pendiente), se
puede trabajar solo con el token de un **usuario de sistema** del portfolio que administra las páginas:

```python
import os

from omnisocial import Token, TokenKind
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.meta import MetaConfig, meta_provider

meta = meta_provider(MetaConfig(api_version="v26.0"), RetryingTransport(HttpxTransport()))

# Con `social` armado con ese proveedor:
result = await social.register_system_connection.execute(
    "meta", owner="agencia", token=Token(TokenKind.SYSTEM, os.environ["META_SYSTEM_USER_TOKEN"])
)
```

- Sin `app_id` ni `app_secret` el proveedor no trae OAuth ni avisos, y las llamadas van sin
  `appsecret_proof`. Si la app del usuario de sistema tiene activado "Require App Secret", hace falta
  configurarla con su `app_id` y `app_secret`.
- El dueño del token se identifica con `/me?fields=id,name`: un usuario de sistema no tiene email ni foto.
- Antes de guardar se descubren los activos (`/me/accounts`). Un token rechazado, sin permisos o que no
  administra ninguna página no se guarda.
- Cuando la app está lista, se cargan `app_id` y `app_secret` y aparecen OAuth y avisos sin cambiar nada
  más.

## Permisos

`CONNECT_SCOPES` pide lo necesario para todas las capacidades menos publicar:

| Permiso | Para qué |
|---|---|
| `public_profile` | Saber quién es la persona |
| `pages_show_list` | Listar las páginas que administra |
| `pages_read_engagement` | Leer publicaciones, comentarios y datos de la página |
| `pages_manage_engagement` | Responder, ocultar y borrar comentarios; el primer comentario |
| `pages_manage_metadata` | Suscribir la página a los avisos |
| `pages_messaging` | Mensajes de Messenger |
| `read_insights` | Métricas de la página |
| `business_management` | Ver las páginas asignadas por un portfolio |
| `instagram_basic` | La cuenta de Instagram y sus publicaciones |
| `instagram_manage_comments` | Comentarios de Instagram |
| `instagram_manage_messages` | Mensajes de Instagram Direct |

Para publicar se suman `PUBLISH_SCOPES`, que no van por defecto porque cada uno necesita su propia
revisión:

| Permiso | Para qué |
|---|---|
| `pages_manage_posts` | Publicar en la página |
| `instagram_content_publish` | Publicar en Instagram |

```python
from omnisocial.meta import CONNECT_SCOPES, PUBLISH_SCOPES, MetaConfig

config = MetaConfig(api_version="v26.0", connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES)
```

Quien ya estaba conectado tiene que volver a autorizar para darlos, y después `social.sync_assets` le
suma la capacidad `publishing` a sus activos.

**Revisión de la app.** Cada permiso que no sea básico necesita **acceso avanzado** para usarse con cuentas
que no tienen un rol en la app, y el acceso avanzado necesita:

1. **Verificación del negocio** del portfolio dueño de la app.
2. **Revisión de la app**, permiso por permiso, con un video del uso real.

Mientras tanto, la app funciona en modo desarrollo con las personas que tengan un rol en ella, y con un
usuario de sistema sobre las páginas que el portfolio tenga asignadas.

Si solo hace falta una parte, conviene pedir menos permisos: `MetaConfig(connect_scopes=(...))` o
`start_authorization(..., scopes=[...])`. Cada permiso que se pide es uno más para revisar.

## Tokens

- El código se canjea por un token de usuario de corta duración y enseguida se estira al de **larga
  duración (unos 60 días)**.
- Los **tokens de página** que se obtienen con un token de larga duración **no vencen**. Son los que se usan
  para todo lo que es de la página.
- Meta **no renueva** tokens de usuario sin la persona. Cuando vence, la conexión pasa a `expired` y hay que
  volver a conectar ([Mantener vivas las conexiones](conexiones.md)). Los tokens de página siguen
  funcionando mientras la conexión exista, pero la librería no los usa si la conexión venció o fue
  revocada.
- Un **usuario de sistema** del portfolio de la organización tiene un token que no vence y ve las páginas
  que tiene asignadas.
- `MetaOAuth.debug_token` dice tipo, vencimiento y permisos concedidos de cualquier token.

## Publicar

Ver [Publicar](publicar-contenido.md) para lo común a todas las redes.

| | Página de Facebook | Cuenta de Instagram |
|---|---|---|
| Texto | Hasta 63.206 | Hasta 2.200 |
| Solo texto | Sí | No: siempre con medios |
| Imágenes | Hasta 10 | Hasta 20 (carrusel) |
| Videos | 1 | Hasta 20; uno solo sale como reel |
| Mezclar fotos y videos | No | Sí, en carrusel |
| Link adjunto | Sí, sin medios | No |
| Primer comentario | Sí | Sí |
| Borrar | Sí | No (ver abajo) |
| Cómo sale | En una llamada | En etapas |

- **Los medios son URLs públicas.** Meta los descarga: una URL firmada que vence antes de que termine no
  sirve.
- **Instagram publica en etapas.** Se arma un contenedor, Instagram procesa los medios y recién ahí se
  publica. Una imagen suele salir en la misma llamada; un video queda `PENDING` y conviene consultarlo una
  vez por minuto. Un contenedor vence a las 24 horas: si nadie lo retomó, la publicación queda `FAILED`.
- **Si se pierde la respuesta al publicar en Instagram**, al retomar el contenedor figura como publicado:
  la publicación queda `PUBLISHED_WITH_ERROR`, sin id, en vez de salir dos veces.
- **El primer comentario pide otro permiso** (`pages_manage_engagement` o `instagram_manage_comments`, que
  sí están en los de conexión). Si falla, la publicación queda `PUBLISHED_WITH_ERROR`.
- **Borrar en Instagram existe en la API, pero pide `instagram_manage_contents`** y todavía no se ofrece:
  `delete_post` devuelve `Refused(ACTION_NOT_OFFERED)`.
- **El video de una página se crea en otro servidor** (`graph-video.facebook.com`, `MetaConfig.video_url`).
  Queda publicado aunque Facebook siga procesándolo.
- **El contenido va en el cuerpo del pedido**, no en la URL: un texto largo no entra en una URL.

## Mensajes privados

Solo se puede escribir dentro de las **24 horas** desde el último mensaje de la persona. `send_message`
lo verifica antes de llamar a Meta y devuelve `Refused(OUTSIDE_REPLY_WINDOW)`; insistir fuera de la ventana
puede terminar en restricciones para la página. Las etiquetas especiales para escribir después (como la de
agente humano) no están soportadas. Ver [Comentarios, mensajes y bandeja](comentarios-y-mensajes.md).

## El catálogo de métricas

`DEFAULT_CATALOG` traduce las [métricas comunes](metricas.md) a los nombres de Meta. Meta da de baja
métricas seguido, así que **antes de depender de una entrada conviene confirmarla contra la referencia de
la versión fijada en `api_version`**. Se puede pasar un catálogo propio:

```python
from omnisocial import CanonicalMetric, CatalogEntry, MetricCatalog
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.meta import DEFAULT_CATALOG, FACEBOOK_PAGE, MetaConfig, meta_provider

catalog = MetricCatalog(
    (
        CatalogEntry(FACEBOOK_PAGE, CanonicalMetric.VIEWS, "page_media_view", since="v24.0"),
        *DEFAULT_CATALOG.entries,
    )
)
meta = meta_provider(MetaConfig(api_version="v26.0"), RetryingTransport(HttpxTransport()), catalog=catalog)
```

Las entradas se recorren en orden: la primera que aplica gana.

- **Métricas que cambian de nombre.** `impressions` de Instagram se reemplazó por `views` desde la v22; el
  catálogo lo tiene en cuenta por versión. Varias métricas de cuenta de Instagram solo existen como total
  del período (`metric_type=total_value`); la librería las pide aparte (`INSTAGRAM_TOTAL_VALUE_METRICS`).
- **`follower_count` de Instagram son seguidores nuevos por día**, no el total. Por eso no se traduce a
  `CanonicalMetric.FOLLOWERS`.
- **No más de ~93 días por llamada.** La librería parte la ventana en tramos de 90
  (`MetaConfig.insights_max_span`).

## Borrado de datos

Para publicar la app, Meta exige un callback de borrado de datos: cuando alguien quita la app, Meta manda un
`signed_request` (firmado con el secreto de la app) y espera una URL de estado y un código de confirmación.

```python
import os

from omnisocial.meta import DeletionReceipt, DeletionRequest, MetaConfig, MetaDeletionRequests
from omnisocial.starlette import meta_data_deletion_routes

config = MetaConfig(
    api_version="v26.0", app_id=os.environ["META_APP_ID"], app_secret=os.environ["META_APP_SECRET"]
)


async def borrar(request: DeletionRequest) -> DeletionReceipt:
    codigo = await agendar_borrado(request.user_id)  # el id de la persona para esta app; lo agenda la app
    return DeletionReceipt(f"https://app.ejemplo.com/borrado/{codigo}", codigo)


app.router.routes.extend(meta_data_deletion_routes(MetaDeletionRequests(config), on_request=borrar))
```

La ruta es `POST /meta/data-deletion`, que se carga en *Configuración → Básica → URL de devolución de
llamada de eliminación de datos*. Una firma inválida responde 400 sin llamar a `on_request`. Acepta también
`previous_app_secrets`, para rotar.

## Avisos

1. En el panel de la app, *Webhooks*, suscribir la URL `https://api.ejemplo.com/webhooks/meta` con el
   mismo `webhook_verify_token` de `MetaConfig`. El `GET` de verificación lo responde `webhook_routes`.
2. Suscribir cada página a la app (`POST /{page}/subscribed_apps` con su token y los campos que
   interesan).
3. Cada aviso llega firmado con `X-Hub-Signature-256` (HMAC-SHA256 del cuerpo crudo con el secreto de la
   app). Lo verifica omniwebhook; sin firma válida no se traduce nada.

Meta no manda un id de entrega, así que cada aviso se identifica por la huella (un hash) de su cuerpo: un
reintento llega con el mismo cuerpo y no se procesa dos veces. Meta tampoco firma una marca de tiempo, así
que no hay control de frescura: la firma y la deduplicación son la defensa. El resto, en
[Avisos](webhooks.md).

**Rotar el secreto de la app.** Al resetearlo en el panel, los avisos en vuelo pueden llegar firmados con el
anterior. Durante el cambio se aceptan los dos, y después de un rato se saca el anterior:

```python
import os

from omnisocial.meta import MetaConfig

config = MetaConfig(
    api_version="v26.0",
    app_id=os.environ["META_APP_ID"],
    app_secret=os.environ["META_APP_SECRET"],
    previous_app_secrets=(os.environ["META_APP_SECRET_ANTERIOR"],),
)
```

## Límites

- **Instagram tiene un tope de publicaciones por API cada 24 horas.** La documentación de Meta da números
  distintos según la página (50 o 100); el valor real se consulta en `content_publishing_limit`. Cuando se
  llega, vuelve `Refused(QUOTA_EXHAUSTED)`.
- **Límites de uso** de la app, de la persona, de la página y de cada producto: vuelven como
  `Refused(RATE_LIMITED)` (ver Errores).
- **Reintentos:** `RetryingTransport(HttpxTransport())` repite lecturas ante 429, 5xx y fallas de red, con
  backoff y jitter. Las escrituras no se repiten solas.

## Errores

Lo que declara `ERRORS` en `spec.py` ([qué hace la librería con cada clase](referencia/negativas.md)):

| Código | Qué quiere decir | Resultado |
|---|---|---|
| 190, 102 | Token vencido, revocado o inválido | La conexión queda inválida: `CONNECTION_INVALID` |
| 10, 200–299 | Falta un permiso | `Refused(MISSING_PERMISSION)`; la conexión sigue sana |
| 4, 17, 32, 341, 613, 80001, 80002, 80006 | Límite de uso (de la app, la persona, la página o un producto) | `Refused(RATE_LIMITED)` |
| 9 con subcódigo 2207042 | Tope de publicaciones de Instagram en 24 horas | `Refused(QUOTA_EXHAUSTED)` |
| 100, 352, 9004, 36000, 36001, 36003 | Pedido inválido: parámetro, formato de video, medio que Instagram no pudo bajar o no acepta | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |

El **2500** queda afuera a propósito: Meta también lo devuelve ante pedidos mal armados, no solo con un
token muerto.

## Lo que conviene saber

- **Algunos permisos ya no se pueden pedir por el diálogo.** Meta rechaza con *Invalid Scopes* ciertos
  permisos en Facebook Login aunque la Graph API los siga exigiendo. Hoy pasa con
  `pages_read_user_content`: sin él, `/{page}/posts` niega los contadores de likes y comentarios (error 10).
  La librería reintenta sin contadores y devuelve las publicaciones con `like_count=None`. Con un token de
  usuario de sistema el permiso se asigna en el portfolio y los contadores vuelven.
- **Los permisos `instagram_business_*` son de otro flujo** (Instagram Login, `instagram.com/oauth`), no de
  Facebook Login. Mezclarlos da *Invalid Scopes*. Ver [Instagram con login propio](instagram.md).
- **`/{ig}/media` ignora `since` y `until`.** La ventana se aplica por código mientras se pagina.
- **El autor de un comentario es `from.id`**, no el nombre de usuario, que puede cambiar.
- **No hay like de comentarios en Instagram.** `like_comment` devuelve `Refused(ACTION_NOT_OFFERED)` sin
  llamar a la red: no es un permiso que falte.
- **Una escritura que responde 200 sin `id` no se publicó.** Se trata como error.
- **El token viaja en la query.** Por eso las fallas de red (`TransportError`) dicen solo el host, y conviene
  no registrar las URLs de la Graph API.
- **Paginación:** las URLs de `paging.next` ya traen cursor, token y firma; se piden sin agregar parámetros.

!!! warning "A confirmar con la API real"
    - **Carrusel de Instagram de hasta 20.** La librería acepta 20, como la app de Instagram, pero la
      [guía de publicación](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
      todavía dice 10 (verificado 2026-11).
    - **El tope de publicaciones de Instagram por API**: 50 o 100 cada 24 horas, según la página de la
      documentación.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
