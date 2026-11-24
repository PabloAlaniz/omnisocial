# TikTok: Login Kit, Display API y lo que conviene saber

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

## Armado

```python
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.tiktok import TikTokConfig, tiktok_provider

tiktok = tiktok_provider(
    TikTokConfig(
        client_key=os.environ["TIKTOK_CLIENT_KEY"], client_secret=os.environ["TIKTOK_CLIENT_SECRET"]
    ),
    RetryingTransport(HttpxTransport()),
)
```

## Permisos y revisión de la app

| Permiso             | Para qué                                                   |
|---------------------|------------------------------------------------------------|
| `user.info.basic`   | `open_id`, nombre visible y avatar.                        |
| `user.info.profile` | Nombre de usuario, bio, verificado.                        |
| `user.info.stats`   | Seguidores, seguidos, likes recibidos, cantidad de videos. |
| `video.list`        | Los videos públicos.                                       |

Mientras la app no pasa la revisión de TikTok funciona en sandbox, solo con las cuentas de prueba que se
cargan en el portal. Para cuentas reales hay que enviar la app a revisión con cada permiso justificado.

## Publicar

Hace falta el permiso `video.publish`, que no está en los de conexión por defecto y tiene su propia
revisión:

```python
from omnisocial.tiktok import CONNECT_SCOPES, PUBLISH_SCOPES, TikTokConfig, TikTokOptions

TikTokConfig(..., connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES)

draft = Draft(
    "Así se hace 👇",
    media=(Media(MediaKind.VIDEO, "https://cdn.ejemplo.com/receta.mp4"),),
    options=TikTokOptions(privacy_level="PUBLIC_TO_EVERYONE"),
)
```

- **Siempre queda `PENDING`.** TikTok descarga y procesa el video o las fotos; el estado se consulta con
  `check_publication` (hasta 30 consultas por minuto por cuenta). Iniciar publicaciones admite 6 por minuto
  por cuenta.
- **Una app sin auditar solo publica en privado.** Por eso `TikTokOptions` usa `SELF_ONLY` si no se dice otra
  cosa. Con otra privacidad, TikTok responde `unaudited_client_can_only_post_to_private_accounts` y vuelve
  `Refused(CONTENT_REJECTED)`.
- **La auditoría revisa la pantalla de publicación de la app**: tiene que mostrar la cuenta, dejar elegir
  la privacidad entre las opciones que TikTok informa para esa cuenta y pedir consentimiento. Sin eso la
  rechazan. Las opciones de cada cuenta salen de `creator_info`, que la librería todavía no consulta.
- **La URL del medio tiene que ser de un dominio verificado** en el portal de la app, https y sin
  redirecciones. Si no, `url_ownership_unverified` → `Refused(CONTENT_REJECTED)`.
- **El id de la publicación solo vuelve si es pública.** En privado sale igual (`PUBLISHED`), con `post_id`
  vacío.
- **Texto:** hasta 2.200 unidades UTF-16 (un emoji puede contar dos). En una publicación de fotos el texto va
  como descripción y el título (hasta 90) es `TikTokOptions.photo_title` o el comienzo del texto.
- **Sin primer comentario, sin link adjunto y sin borrado:** la API no los ofrece.
- **Errores:** `spam_risk_too_many_posts` vuelve como `Refused(RATE_LIMITED)` y `reached_active_user_cap`
  (el tope diario de cuentas que publican con la app) como `Refused(QUOTA_EXHAUSTED)`. Algunos llegan con
  HTTP 200: manda el código del cuerpo.
- Si el procesamiento falla, la publicación queda `FAILED` con el motivo de TikTok (`video_pull_failed`,
  `duration_check_failed`, `spam_risk`…).

## Tokens

- **El access token dura 2 horas** y el refresh token, 180 días (lo dicen `expires_in` y
  `refresh_expires_in`; conviene no fijarlos en el código). La librería renueva sola antes de usar el token.
- **El refresh token rota.** Cada renovación devuelve uno nuevo y el anterior deja de servir. La conexión se
  guarda con compare-and-swap: si dos procesos renuevan a la vez, el que pierde relee y usa el token que guardó
  el otro, en vez de quemar el refresh token. Por lo mismo, **una cuenta de TikTok no puede estar conectada a
  dos sistemas con la misma app**: cada uno invalidaría el refresh token del otro.
- `invalid_grant` al renovar es terminal: la conexión queda inválida hasta que la persona vuelva a autorizar.
- En web no hay PKCE: el canje va del servidor con el secreto de la app.

## Cosas que conviene saber

- **`fields` va en la query, también en los POST.** Listar videos es un `POST` con el cursor en el cuerpo y
  los campos en la URL. Como es una lectura, el transporte lo reintenta igual que un `GET`.
- **No hay filtro por fecha.** Los videos vienen del más nuevo al más viejo y el cursor es un instante en
  milisegundos: la librería arranca desde el final de la ventana y corta al pasar el principio.
- **La portada (`cover_image_url`) vence a las 6 horas.** Si hace falta mostrarla después, conviene copiar la
  imagen en el momento.
- **Los contadores no tienen historia.** `read_insights` devuelve una foto del momento (`Period.LIFETIME`);
  para la evolución de seguidores, la app guarda una lectura por día.
- **Errores:** `access_token_invalid` deja la conexión inválida; `scope_not_authorized` y
  `scope_permission_missed` vuelven como `Refused(MISSING_PERMISSION)`; `rate_limit_exceeded` (429) lo reintenta
  el transporte. El límite por defecto es de 600 pedidos por minuto por endpoint.

## Webhooks

Se configura una sola URL de callback en el portal (`https://.../webhooks/tiktok` con `webhook_routes`). No
hay saludo de verificación.

- Cada aviso llega con `TikTok-Signature: t=<segundos>,s=<hex>`: HMAC-SHA256 de `"<t>.<cuerpo>"` con el
  secreto de la app. Lo verifica el esquema `tiktok` de omniwebhook. Se rechazan los avisos con más de 5
  minutos (`webhook_tolerance_seconds`).
- TikTok reintenta hasta 72 horas y puede mandar el mismo aviso más de una vez: la deduplicación es por huella
  del cuerpo, como en Meta.
- **`authorization.removed`**: la persona quitó la app desde TikTok (o la cuenta se borró o se suspendió). La
  conexión queda revocada antes de llamar a `on_events`, y el token ya no sirve.
- `video.publish.completed` y `video.upload.failed` son de las publicaciones hechas con Content Posting API.
- Para rotar el secreto: `TikTokConfig(client_secret=nuevo, previous_client_secrets=(anterior,))`.
