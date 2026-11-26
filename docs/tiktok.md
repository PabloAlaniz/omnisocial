# TikTok

La cuenta de TikTok de quien autoriza, con Login Kit, la Display API y la Content Posting API.

## Qué cubre

| Capacidad   | Qué hace                                                                 |
|-------------|--------------------------------------------------------------------------|
| `login`     | Login Kit web: autorizar, canjear el código, renovar, revocar.           |
| `assets`    | La cuenta de quien autorizó es el único activo (`tiktok_account`).       |
| `content`   | Los videos públicos de la cuenta, con vistas, likes, comentarios y compartidos. |
| `insights`  | Contadores de la cuenta: seguidores, seguidos, likes recibidos y videos.  |
| `webhooks`  | Avisos firmados; `authorization.removed` revoca la conexión sola.         |
| `publishing`| Un video o hasta 35 fotos, con la Content Posting API (publicación directa). |

**Sin comentarios ni mensajes.** La Display API no tiene endpoint para leer comentarios: solo el contador
`comment_count` de cada video. Los comentarios están en la Research API, que es para investigación académica
y no sirve para administrar una cuenta.

## Crear la app

1. En [developers.tiktok.com](https://developers.tiktok.com/), *Manage apps → Connect an app*.
2. Agregar los productos **Login Kit** (web) y, para publicar, **Content Posting API** con la publicación
   directa activada.
3. En Login Kit, cargar la URL de retorno: `https://api.ejemplo.com/oauth/tiktok/callback`.
4. Para publicar desde una URL, **verificar el dominio** de donde salen los medios (*URL properties*).
5. Para recibir avisos, cargar la URL `https://api.ejemplo.com/webhooks/tiktok` en *Webhooks*.
6. Copiar el **client key** y el **client secret**.

Documentación oficial: [Login Kit](https://developers.tiktok.com/doc/login-kit-web/) y
[Content Posting API](https://developers.tiktok.com/doc/content-posting-api-get-started/) (verificado
2026-11).

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.tiktok import CONNECT_SCOPES, PUBLISH_SCOPES, TikTokConfig, tiktok_provider

tiktok = tiktok_provider(
    TikTokConfig(
        client_key=os.environ["TIKTOK_CLIENT_KEY"],
        client_secret=os.environ["TIKTOK_CLIENT_SECRET"],
        connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES,  # sin PUBLISH_SCOPES si no se publica
    ),
    RetryingTransport(HttpxTransport()),
)
```

## Permisos

| Permiso             | Constante | Para qué                                                   |
|---------------------|-----------|------------------------------------------------------------|
| `user.info.basic`   | `CONNECT_SCOPES` | `open_id`, nombre visible y avatar.                 |
| `user.info.profile` | `CONNECT_SCOPES` | Nombre de usuario, bio, verificado.                 |
| `user.info.stats`   | `CONNECT_SCOPES` | Seguidores, seguidos, likes recibidos, cantidad de videos. |
| `video.list`        | `CONNECT_SCOPES` | Los videos públicos.                                |
| `video.publish`     | `PUBLISH_SCOPES` | Publicar. Tiene su propia revisión.                 |

Mientras la app no pasa la revisión de TikTok funciona en sandbox, solo con las cuentas de prueba que se
cargan en el portal. Para cuentas reales hay que enviar la app a revisión con cada permiso justificado.

## Tokens

- **El access token dura 24 horas** y el refresh token, 365 días
  ([Login Kit](https://developers.tiktok.com/doc/oauth-user-access-token-management), verificado 2026-11).
  La librería lee `expires_in` y `refresh_expires_in` de cada respuesta en vez de fijarlos, y renueva sola
  antes de usar el token.
- **El refresh token rota.** Cada renovación devuelve uno nuevo y el anterior deja de servir; la librería
  lo maneja aunque dos procesos renueven a la vez ([Mantener vivas las conexiones](conexiones.md)). Por
  lo mismo, **una cuenta de TikTok no puede estar conectada a dos sistemas con la misma app**: cada uno
  invalidaría el refresh token del otro.
- `invalid_grant` al renovar es terminal: la conexión queda inválida hasta que la persona vuelva a autorizar.
- En web no hay PKCE: el canje va del servidor con el secreto de la app.

## Publicar

Hace falta `video.publish` (`PUBLISH_SCOPES`, ver [Armado](#armado)).

```python
from omnisocial import Draft, Media, MediaKind
from omnisocial.tiktok import TikTokOptions

draft = Draft(
    "Así se hace 👇",
    media=(Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/receta.mp4"),),
    options=TikTokOptions(privacy_level="PUBLIC_TO_EVERYONE"),
)
result = await social.publish.execute(asset_id, draft)
```

- **Siempre queda `PENDING`.** TikTok descarga y procesa el video o las fotos; el estado se consulta con
  `check_publication`.
- **Una app sin auditar solo publica en privado.** Por eso `TikTokOptions` usa `SELF_ONLY` si no se dice otra
  cosa. Con otra privacidad, TikTok responde `unaudited_client_can_only_post_to_private_accounts`.
- **La auditoría revisa la pantalla de publicación de la app**: tiene que mostrar la cuenta, dejar elegir
  la privacidad entre las opciones que TikTok informa para esa cuenta y pedir consentimiento. Sin eso la
  rechazan. Las opciones de cada cuenta salen de `creator_info`, que la librería todavía no consulta.
- **La URL del medio tiene que ser de un dominio verificado** en el portal de la app, https y sin
  redirecciones. Si no, `url_ownership_unverified`.
- **El id de la publicación solo vuelve si es pública.** En privado sale igual (`PUBLISHED`), con `post_id`
  vacío.
- **Texto:** hasta 2.200 unidades UTF-16 (un emoji puede contar dos). En una publicación de fotos el texto va
  como descripción y el título (hasta 90) es `TikTokOptions.photo_title` o el comienzo del texto.
- **Sin primer comentario, sin link adjunto y sin borrado:** la API no los ofrece.
- Si el procesamiento falla, la publicación queda `FAILED` con el motivo de TikTok (`video_pull_failed`,
  `duration_check_failed`, `spam_risk`…).

## Avisos

Se configura una sola URL de callback en el portal, que atiende `webhook_routes` ([Avisos](webhooks.md)).
No hay saludo de verificación.

- Cada aviso llega con `TikTok-Signature: t=<segundos>,s=<hex>`: HMAC-SHA256 de `"<t>.<cuerpo>"` con el
  secreto de la app. Se rechazan los avisos con más de 5 minutos (`webhook_tolerance_seconds`).
- TikTok reintenta hasta 72 horas y puede mandar el mismo aviso más de una vez: no se procesa dos veces.
- **`authorization.removed`**: la persona quitó la app desde TikTok (o la cuenta se borró o se suspendió). La
  conexión queda revocada antes de llamar a `on_events`, y el token ya no sirve.
- `video.publish.completed` y `video.upload.failed` son de las publicaciones hechas con Content Posting API.
- Para rotar el secreto, se pasa el anterior mientras dura el cambio:
  `TikTokConfig(..., client_secret=nuevo, previous_client_secrets=(anterior,))`.

## Límites

| Qué | Límite |
|---|---|
| Pedidos en general | 600 por minuto por endpoint |
| Iniciar publicaciones | 6 por minuto por cuenta |
| Consultar el estado de una publicación | 30 por minuto por cuenta |
| Medios por publicación | 1 video o hasta 35 fotos |
| Texto | 2.200 unidades UTF-16 |

## Errores

Algunos llegan con HTTP 200: manda el código del cuerpo.

| Código | Resultado |
|---|---|
| `access_token_invalid` | La conexión queda inválida |
| `scope_not_authorized`, `scope_permission_missed` | `Refused(MISSING_PERMISSION)` |
| `rate_limit_exceeded` (429) | Lo reintenta el transporte; si sigue, `Refused(RATE_LIMITED)` |
| `spam_risk_too_many_posts`, `spam_risk_too_many_pending_share` | `Refused(RATE_LIMITED)` |
| `reached_active_user_cap` | Tope diario de cuentas que publican con la app: `Refused(QUOTA_EXHAUSTED)` |
| `unaudited_client_can_only_post_to_private_accounts`, `url_ownership_unverified`, `privacy_level_option_mismatch` | `Refused(CONTENT_REJECTED)` al publicar |
| `invalid_param` | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |
| `internal_error` | `ProviderError`, pasajero |

## Lo que conviene saber

- **`fields` va en la query, también en los POST.** Listar videos es un `POST` con el cursor en el cuerpo y
  los campos en la URL. Como es una lectura, el transporte lo reintenta igual que un `GET`.
- **No hay filtro por fecha.** Los videos vienen del más nuevo al más viejo y el cursor es un instante en
  milisegundos: la librería arranca desde el final de la ventana y corta al pasar el principio.
- **La portada (`cover_image_url`) vence a las 6 horas.** Si hace falta mostrarla después, conviene copiar la
  imagen en el momento.
- **Los contadores no tienen historia.** `read_insights` devuelve una foto del momento (`Period.LIFETIME`);
  para la evolución de seguidores, la app guarda una lectura por día.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
