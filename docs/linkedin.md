# LinkedIn

El perfil de quien autoriza y las páginas de empresa que administra.

## Qué cubre

| Capacidad    | Perfil (`linkedin_member`)        | Página de empresa (`linkedin_organization`)     |
|--------------|-----------------------------------|-------------------------------------------------|
| `publishing` | Texto, link, imágenes o un video. | Lo mismo, más el primer comentario.             |
| `content`    | —                                 | Las publicaciones de la página.                 |
| `comments`   | —                                 | Leer, responder, borrar y reaccionar.           |
| `insights`   | —                                 | Seguidores y estadísticas de las publicaciones. |

Además, `login` (Sign In with LinkedIn, por OpenID Connect) y `assets`: el perfil de quien autorizó y las
páginas que administra.

**Lo que una app recién creada puede hacer es entrar y publicar como persona.** Todo lo de páginas de
empresa necesita la Community Management API, que LinkedIn aprueba aparte. Sin eso, al conectar se descubre
solo el perfil.

**Sin mensajes, sin ocultar comentarios, sin leer las publicaciones de un perfil.** La API no tiene
mensajes privados ni forma de ocultar un comentario (solo cerrar los de toda una publicación), y leer lo
que publicó una persona pide un permiso restringido. Los avisos (webhooks) existen para páginas, pero solo
para apps con un caso de uso aprobado, y todavía no se integran.

## Crear la app

1. En [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps), crear una app asociada a una
   página de empresa (la página tiene que verificar la app).
2. En *Auth*, cargar la URL de retorno `https://api.ejemplo.com/oauth/linkedin/callback` y copiar el
   **client id** y el **client secret**.
3. En *Products*, activar los productos que hagan falta:

| Producto | Permisos | Revisión | Constante |
|----------|----------|----------|-----------|
| Sign In with LinkedIn using OpenID Connect | `openid`, `profile`, `email` | No | `LOGIN_SCOPES`, `CONNECT_SCOPES` |
| Share on LinkedIn | `w_member_social` | No | `PUBLISH_SCOPES` |
| Community Management API | `rw_organization_admin`, `r_organization_social`, `w_organization_social`, `r_organization_social_feed`, `w_organization_social_feed` | Sí | `ORGANIZATION_SCOPES` |

- **La Community Management API tiene dos niveles.** El de desarrollo se aprueba primero, con pocas
  llamadas por día y por un tiempo limitado; el estándar llega después de otra revisión.
- **Los permisos terminados en `_feed` son los de comentarios y reacciones.** Son más nuevos que los de
  publicar: una app aprobada antes puede no tenerlos.

Documentación oficial: [LinkedIn API](https://learn.microsoft.com/linkedin/) (verificado 2026-11).

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.linkedin import (
    CONNECT_SCOPES,
    ORGANIZATION_SCOPES,
    PUBLISH_SCOPES,
    LinkedInConfig,
    linkedin_provider,
)

linkedin = linkedin_provider(
    LinkedInConfig(
        client_id=os.environ["LINKEDIN_CLIENT_ID"],
        client_secret=os.environ["LINKEDIN_CLIENT_SECRET"],
        api_version="202611",
        connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES,  # + ORGANIZATION_SCOPES con la API de páginas
    ),
    RetryingTransport(HttpxTransport()),
)
```

### La versión de la API

`api_version` es obligatoria y tiene la forma `AAAAMM`. LinkedIn saca una versión por mes y **retira cada
una al año**: con una versión retirada todas las llamadas fallan con un 426 (`NONEXISTENT_VERSION`). No es
un problema del token y la conexión no se invalida, pero nada anda hasta actualizarla. Conviene revisarla
un par de veces al año.

## Permisos

Cada permiso viene con un producto de la app (ver [Crear la app](#crear-la-app)):

| Constante | Permisos | Para qué |
|---|---|---|
| `LOGIN_SCOPES` | `openid`, `profile`, `email` | Saber quién es la persona |
| `CONNECT_SCOPES` | los de login | Conectar el perfil |
| `PUBLISH_SCOPES` | `w_member_social` | Publicar en el perfil |
| `ORGANIZATION_SCOPES` | `rw_organization_admin`, `r_organization_social`, `w_organization_social`, `r_organization_social_feed`, `w_organization_social_feed` | Las páginas: descubrirlas, publicar, leer, comentar y medir |

Pedir un permiso que la app no tiene hace fallar la autorización entera. Por eso los de páginas no se
piden por defecto.

## Tokens

- **El token dura 60 días.** Solo las apps aprobadas como socias reciben un token de renovación (dura un
  año y no se extiende al usarlo). Sin él, la conexión vence sola a los 60 días y la persona tiene que
  volver a autorizar.
- **No hay forma documentada de revocar un token por API**: `disconnect` marca la conexión como revocada,
  pero el token sigue sirviendo en LinkedIn hasta que vence o la persona quita el acceso.
- **El id de la persona (`sub`) es propio de cada app.** La misma persona tiene otro id en otra app.

## Publicar

```python
from omnisocial import Draft, Media, MediaKind, PathFile
from omnisocial.linkedin import LinkedInOptions

draft = Draft(
    "Sumamos a tres personas al equipo (¡bienvenidas!) #equipo",
    media=(Media(MediaKind.IMAGE, file=PathFile.open("equipo.jpg", "image/jpeg"), alt_text="El equipo"),),
    first_comment="Seguimos buscando: escribinos.",  # solo en páginas
)
result = await social.publish.execute(asset_id, draft, idempotency_key="equipo-nuevo")
```

| | Perfil | Página de empresa |
|---|---|---|
| Texto | Hasta 3.000 | Hasta 3.000 |
| Imágenes | Hasta 20 | Hasta 20 |
| Videos | 1 (hasta 500 MB y 30 minutos) | 1 |
| Mezclar fotos y video | No | No |
| Link adjunto | Sí, sin medios | Sí, sin medios |
| Primer comentario | No | Sí |
| Borrar | Sí | Sí |
| Cómo sale | En una llamada | En una llamada |

- **Los medios van como archivo.** LinkedIn no va a buscar una URL: cada imagen o video se sube antes y
  la publicación los referencia. Si una subida falla, con certeza no salió: `Refused(NOT_PUBLISHED)`.
- **El texto se escapa solo.** LinkedIn usa un formato propio donde `( ) [ ] { } < > @ | * _ ~ \` son
  reservados: sin escapar, un paréntesis puede cortar el texto o hacer rechazar la publicación. Los `#`
  no se escapan, así los hashtags siguen andando.
- **Para mencionar**, el texto va ya escrito en el formato propio de LinkedIn (su *little text*, el mismo
  que tiene los caracteres reservados) y con `LinkedInOptions(little_text=True)`:
  `"Gracias @[Mi Empresa](urn:li:organization:123)"`. Ahí no se escapa nada: es responsabilidad de quien
  llama.
- **La tarjeta de un link no se arma sola.** LinkedIn no lee la página: el título y la descripción van en
  `LinkedInOptions(link_title=..., link_description=...)`. Sin título se muestra la URL.
- **Si LinkedIn rechaza el contenido** (un 4xx al crear la publicación), vuelve
  `Refused(CONTENT_REJECTED)` o `Refused(NOT_PUBLISHED)`. Un 5xx deja la publicación en duda.
- **El primer comentario pide los permisos `_feed`.** Si falla, la publicación queda
  `PUBLISHED_WITH_ERROR`.
- `LinkedInOptions(visibility="CONNECTIONS")` publica solo para los contactos (en un perfil).

## Publicaciones, comentarios y métricas de una página

- **Las publicaciones se piden por fecha de creación.** Con el orden por defecto (última modificación) una
  publicación vieja que alguien editó aparece primera.
- **Los contadores de cada publicación no vienen en el listado** (`like_count` y `comment_count` quedan en
  `None`): están en otra API, de a una publicación por llamada.
- **El id de un comentario es su URN** (`urn:li:comment:(urn:li:activity:123,456)`), que lleva adentro la
  publicación. Para leer las respuestas de un comentario, `list_comments` con ese URN como `object_id`.
- **Se responde y se reacciona como la página.**
- **Métricas:** `firstDegreeSize` son los seguidores de hoy. Las de publicaciones (`impressionCount`,
  `uniqueImpressionsCount`, `clickCount`, `likeCount`, `commentCount`, `shareCount`, `engagement`) son el
  total de los últimos 12 meses, o un punto por día con `Period.DAY` y una ventana con los dos extremos.
  LinkedIn no guarda más de 12 meses. `engagement` es una tasa, no una cantidad.

## Límites

- **LinkedIn no publica sus límites.** Cada endpoint tiene un tope diario por app y otro por persona, que se
  ven en el portal (Analytics) recién después de la primera llamada del día. Vuelven a medianoche UTC.
- Al llegar, responde 429: vuelve `Refused(RATE_LIMITED)`. Reintentar en el momento no sirve.

## Errores

| Respuesta | Resultado |
|---|---|
| 401 | Siempre es el token (falta, es inválido, venció o lo revocaron): la conexión queda inválida |
| 403 con `ACCESS_DENIED`, o código 100 | Falta un permiso o un producto: `Refused(MISSING_PERMISSION)` |
| Otro 403 | Nunca es el token: `ProviderError`, y la conexión sigue sana |
| 429, `TOO_MANY_REQUESTS` | `Refused(RATE_LIMITED)` |
| 400, 422, `FIELD_LENGTH_TOO_LONG`, `UNPROCESSABLE_ENTITY` | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |
| 426, `NONEXISTENT_VERSION` | La versión de la API está retirada: hay que actualizar `api_version` ([ver arriba](#la-version-de-la-api)) |

## Lo que conviene saber

- **Las URLs se arman a mano.** El protocolo de LinkedIn quiere los URN codificados pero los paréntesis y
  las comas de `List(...)` sin codificar; un cliente HTTP común codifica todo y LinkedIn no lo entiende.
- **La subida de una imagen lleva el token y la de un video no.**
- **Según la respuesta, la página administrada viene en `organization` o en `organizationTarget`.**
- **Las respuestas de error viejas no traen `code`**, solo `serviceErrorCode`.

!!! warning "A confirmar con la API real"
    - El límite de 3.000 caracteres: es el que se conoce de la interfaz; la documentación de la API no da
      el número.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
