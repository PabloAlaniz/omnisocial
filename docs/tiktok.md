# TikTok: Login Kit, Display API y lo que conviene saber

## Qué cubre

| Capacidad   | Qué hace                                                                 |
|-------------|--------------------------------------------------------------------------|
| `login`     | Login Kit web: autorizar, canjear el código, renovar, revocar.           |
| `assets`    | La cuenta de quien autorizó es el único activo (`tiktok_account`).       |
| `content`   | Los videos públicos de la cuenta, con vistas, likes, comentarios y compartidos. |
| `insights`  | Contadores de la cuenta: seguidores, seguidos, likes recibidos y videos.  |
| `webhooks`  | Avisos firmados; `authorization.removed` revoca la conexión sola.         |

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
