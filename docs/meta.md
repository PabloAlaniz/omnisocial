# Meta: permisos, revisión de la app y lo que conviene saber

## Qué cubre

| Capacidad | Página de Facebook | Cuenta de Instagram |
|-----------|--------------------|---------------------|
| Login (Facebook Login) | sí | — |
| Activos (`me/accounts`) | sí | sí, la conectada a cada página |
| Publicaciones | `/{page}/posts` | `/{ig}/media` |
| Comentarios: leer, responder, ocultar | sí | sí |
| Mensajes privados | Messenger | Instagram Direct, por la página |
| Métricas | `/{page}/insights` | `/{ig}/insights` |
| Webhooks | `feed`, `messages` | `comments`, `mentions`, `messages` |

Las cuentas de Instagram usan el token de su página: en el flujo de Facebook Login no existen tokens
propios de Instagram.

## Publicar

Hacen falta `pages_manage_posts` (páginas) e `instagram_content_publish` (Instagram), que no están en los
permisos de conexión por defecto:

```python
from omnisocial.meta import CONNECT_SCOPES, PUBLISH_SCOPES, MetaConfig

MetaConfig(..., connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES)
```

Quien ya estaba conectado tiene que volver a autorizar para darlos, y los activos guardados antes de esta
versión no tienen la capacidad `publishing`: `social.sync_assets` los actualiza.

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
- **Instagram tiene un tope de publicaciones por API cada 24 horas.** La documentación de Meta da números
  distintos según la página (50 o 100); el valor real se consulta en `content_publishing_limit`. Cuando se
  llega, vuelve `Refused(QUOTA_EXHAUSTED)` (código 9, subcódigo 2207042).
- **Borrar en Instagram existe en la API, pero pide `instagram_manage_contents`** y todavía no se ofrece:
  `delete_post` devuelve `Refused(ACTION_NOT_OFFERED)`.
- **El video de una página se crea en otro servidor** (`graph-video.facebook.com`, `MetaConfig.video_url`).
  Queda publicado aunque Facebook siga procesándolo.
- **El contenido va en el cuerpo del pedido**, no en la URL: un texto largo no entra en una URL.

## Tokens

- El código se canjea por un token de usuario de corta duración y enseguida se estira al de **larga
  duración (unos 60 días)**.
- Los **tokens de página** que se obtienen con un token de larga duración **no vencen**. Son los que se usan
  para todo lo que es de la página.
- Meta **no renueva** tokens de usuario sin la persona. Cuando vence, la conexión pasa a `expired` y hay que
  volver a conectar. Los tokens de página siguen funcionando mientras la conexión exista, pero la librería
  no los usa si la conexión venció o fue revocada.
- Un **usuario de sistema** del portfolio de la organización tiene un token que no vence y ve las páginas
  que tiene asignadas. Se registra con `register_system_connection`.
- Cada llamada va firmada con `appsecret_proof`. Conviene activar **Require App Secret** en la
  configuración avanzada de la app.
- `MetaOAuth.debug_token` dice tipo, vencimiento y permisos concedidos de cualquier token.

## Modo token (sin app)

Mientras no hay una app con acceso avanzado (o mientras la verificación del negocio está pendiente), se
puede trabajar solo con el token de un **usuario de sistema** del portfolio que administra las páginas:

```python
provider = meta_provider(MetaConfig(api_version="v24.0"), RetryingTransport(HttpxTransport()))
await social.register_system_connection.execute("meta", owner=..., token=Token(TokenKind.SYSTEM, token))
```

- Sin `app_id` ni `app_secret` el proveedor no trae OAuth ni webhooks, y las llamadas van sin
  `appsecret_proof`. Si la app del usuario de sistema tiene activado "Require App Secret", hace falta
  configurarla con su `app_id` y `app_secret`.
- El dueño del token se identifica con `/me?fields=id,name`: un usuario de sistema no tiene email ni foto.
- Antes de guardar se descubren los activos (`/me/accounts`). Un token rechazado, sin permisos o que no
  administra ninguna página no se guarda.
- Cuando la app está lista, se carga `app_id` y `app_secret` y aparecen OAuth y webhooks sin cambiar nada más.

## Permisos y revisión de la app

`CONNECT_SCOPES` pide lo necesario para todas las capacidades. Cada permiso que no sea básico necesita
**acceso avanzado** para usarse con cuentas que no tienen un rol en la app, y el acceso avanzado necesita:

1. **Verificación del negocio** del portfolio dueño de la app.
2. **Revisión de la app**, permiso por permiso, con un video del uso real.

Mientras tanto, la app funciona en modo desarrollo con las personas que tengan un rol en ella, y con un
usuario de sistema sobre las páginas que el portfolio tenga asignadas.

Si solo hace falta una parte, conviene pedir menos permisos: `MetaConfig(connect_scopes=(...))` o
`start_authorization(..., scopes=[...])`. Cada permiso que se pide es uno más para revisar.

## Cosas que se aprendieron a los golpes

- **Algunos permisos ya no se pueden pedir por el diálogo.** Meta rechaza con *Invalid Scopes* ciertos
  permisos en Facebook Login aunque la Graph API los siga exigiendo. Hoy pasa con
  `pages_read_user_content`: sin él, `/{page}/posts` niega los contadores de likes y comentarios (error 10).
  La librería reintenta sin contadores y devuelve las publicaciones con `like_count=None`. Con un token de
  usuario de sistema el permiso se asigna en el portfolio y los contadores vuelven.
- **Los permisos `instagram_business_*` son de otro flujo** (Instagram Login, `instagram.com/oauth`), no de
  Facebook Login. Mezclarlos da *Invalid Scopes*.
- **`/{ig}/media` ignora `since` y `until`.** La ventana se aplica por código mientras se pagina.
- **Métricas que cambian de nombre.** `impressions` de Instagram se reemplazó por `views` desde la v22; el
  catálogo lo tiene en cuenta por versión. Varias métricas de cuenta de Instagram solo existen como total
  del período (`metric_type=total_value`); la librería las pide aparte (`INSTAGRAM_TOTAL_VALUE_METRICS`).
- **`follower_count` de Instagram son seguidores nuevos por día**, no el total. Por eso no se traduce a
  `CanonicalMetric.FOLLOWERS`.
- **Ventana de métricas:** no más de ~93 días por llamada. La librería parte en tramos de 90
  (`MetaConfig.insights_max_span`).
- **Error 2500** también aparece en pedidos mal armados. Solo 190 y 102 se toman como token muerto: la
  conexión queda inválida y no se vuelve a llamar con ese token (`Refused(CONNECTION_INVALID)`).
- **Error 10 y 200–299 son permisos faltantes**, no tokens muertos. Vuelven como
  `Refused(MISSING_PERMISSION)` y la conexión sigue sana: se arregla reconectando con el permiso.
- **El autor de un comentario es `from.id`**, no el nombre de usuario, que puede cambiar.
- **No hay like de comentarios en Instagram.** `like_comment` devuelve `Refused(ACTION_NOT_OFFERED)` sin
  llamar a la red: no es un permiso que falte.
- **Una escritura que responde 200 sin `id` no se publicó.** Se trata como error.
- **El token viaja en la query.** Por eso las fallas de red (`TransportError`) dicen solo el host, y conviene
  no loguear las URLs de la Graph API.
- **Paginación:** las URLs de `paging.next` ya traen cursor, token y firma; se piden sin agregar parámetros.
- **Reintentos:** `RetryingTransport(HttpxTransport())` repite lecturas ante 429, 5xx y fallas de red, con
  backoff y jitter. Las escrituras no se repiten solas.

## Borrado de datos

Para publicar la app, Meta exige un callback de borrado de datos: cuando alguien quita la app, Meta manda un
`signed_request` (firmado con el secreto de la app) y espera una URL de estado y un código de confirmación.

```python
from omnisocial.meta import DeletionReceipt, MetaDeletionRequests
from omnisocial.starlette import meta_data_deletion_routes


async def borrar(request) -> DeletionReceipt:
    codigo = await agendar_borrado(request.user_id)  # el id de la persona para esta app
    return DeletionReceipt(f"https://app.ejemplo.com/borrado/{codigo}", codigo)


app.router.routes.extend(meta_data_deletion_routes(MetaDeletionRequests(config), on_request=borrar))
```

Una firma inválida responde 400 sin llamar a `on_request`. Acepta también `previous_app_secrets`, para rotar.

## El catálogo de métricas

`DEFAULT_CATALOG` traduce los nombres comunes a los de Meta. Meta da de baja métricas seguido, así que
**antes de depender de una entrada conviene confirmarla contra la referencia de la versión fijada en
`api_version`**. Se puede pasar un catálogo propio:

```python
from omnisocial import CanonicalMetric, CatalogEntry, MetricCatalog
from omnisocial.meta import DEFAULT_CATALOG, FACEBOOK_PAGE, meta_provider

catalog = MetricCatalog(
    (
        CatalogEntry(FACEBOOK_PAGE, CanonicalMetric.VIEWS, "page_media_view", since="v24.0"),
        *DEFAULT_CATALOG.entries,
    )
)
provider = meta_provider(config, transport, catalog=catalog)
```

Las entradas se recorren en orden: la primera que aplica gana.

## Mensajes privados

Solo se puede escribir dentro de las **24 horas** desde el último mensaje de la persona. `send_message`
lo verifica antes de llamar a Meta y devuelve `Refused(OUTSIDE_REPLY_WINDOW)`; insistir fuera de la ventana
puede terminar en restricciones para la página. Las etiquetas especiales para escribir después (como la de
agente humano) no están soportadas.

## Webhooks

1. En el panel de la app, suscribir la URL `https://.../webhooks/meta` con el mismo
   `webhook_verify_token` de `MetaConfig`. El `GET` de verificación lo responde `webhook_routes`.
2. Suscribir cada página a la app (`POST /{page}/subscribed_apps` con su token y los campos que interesan).
3. Cada aviso llega firmado con `X-Hub-Signature-256` (HMAC-SHA256 del cuerpo crudo con el secreto de la
   app). Lo verifica omniwebhook; sin firma válida no se traduce nada.

Meta no manda un id de entrega, así que cada aviso se identifica por la huella de su cuerpo. Los reintentos
de Meta llegan con el mismo cuerpo y se responden 200 sin volver a procesarse. Meta tampoco firma una marca
de tiempo, así que no hay control de frescura: la firma y la deduplicación son la defensa.

**Rotar el secreto de la app.** Al resetearlo en el panel, los avisos en vuelo pueden llegar firmados con el
anterior. Durante el cambio:

```python
MetaConfig(app_secret=nuevo, previous_app_secrets=(anterior,), ...)
```

y después de un rato se saca el anterior.

Los avisos se enrutan a todos los activos guardados con ese id: si dos dueños conectaron la misma página,
los dos lo reciben.
