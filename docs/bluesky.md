# Bluesky

La cuenta de Bluesky de quien conecta, con una contraseña de aplicación: posts, hilos, respuestas y
contadores. También perfiles públicos de cualquier cuenta.

## Qué cubre

| Capacidad         | Qué hace                                                                    |
|-------------------|-----------------------------------------------------------------------------|
| `credentials`     | Conectar con una contraseña de aplicación. No hay diálogo de OAuth.         |
| `assets`          | La cuenta de quien conectó es el único activo (`bluesky_account`).          |
| `content`         | Los posts propios, sin reposts ni respuestas, con sus contadores.           |
| `publishing`      | Un post o un hilo, con hasta 4 imágenes, un video o una tarjeta de link. Borrar. |
| `comments`        | Leer las respuestas a un post, responder y dar like.                        |
| `insights`        | Contadores de la cuenta: seguidores, seguidos y posts.                      |
| `public_profiles` | Cualquier cuenta por nombre o por DID, sin que nadie conecte.               |

**Sin mensajes, sin avisos y sin ocultar respuestas, por ahora.** Bluesky tiene mensajes y un flujo de
eventos en tiempo real, que todavía no se integran. Ocultar una respuesta existe, pero es editar una regla
del hilo entero.

## Antes de empezar

**No hay app que registrar**, ni clave ni secreto: cada persona conecta con una contraseña de aplicación
que genera en su cuenta. Es la red con la que arranca [Primeros pasos](primeros-pasos.md).

## Armado

```python
from omnisocial.bluesky import BlueskyConfig, bluesky_provider
from omnisocial.httpx import HttpxTransport, RetryingTransport

bluesky = bluesky_provider(BlueskyConfig(), RetryingTransport(HttpxTransport()))
```

## Conectar

La persona genera una **contraseña de aplicación** en la configuración de Bluesky (en *Privacidad y
seguridad*) y la carga junto con su nombre:

```python
from omnisocial import Connected, Refusal, Refused

result = await social.connect_with_credentials.execute(
    "bluesky",
    owner="proyecto:42",
    credentials={"identifier": "ana.bsky.social", "password": "abcd-efgh-ijkl-mnop"},
)
match result:
    case Connected(connection=connection, assets=assets):
        ...
    case Refused(reason=Refusal.PROVIDER_DENIED, detail=detail):
        ...  # no la aceptó
    case Refused(reason=Refusal.RATE_LIMITED, retry_after=seconds):
        ...  # demasiados intentos
```

- **La contraseña no se guarda.** Se cambia por una sesión y se descarta; lo que queda guardado, cifrado,
  es la sesión.
- **Tiene que ser una contraseña de aplicación, no la de la cuenta.** Con la verificación por mail
  activada, la de la cuenta no sirve y Bluesky pide un código: vuelve `Refused(PROVIDER_DENIED)` con un
  detalle que lo explica. Además, una contraseña de aplicación se puede quitar sin cambiar la de la cuenta.
- Quien tiene su propio servidor de datos lo indica con `"server": "pds.ejemplo.com"`. Si no, se usa
  `bsky.social`. El servidor se valida: tiene que ser un dominio público.
- `omnisocial.bluesky.FIELDS` dice qué pedirle a la persona y cuál de los datos es secreto.
- Bluesky recomienda OAuth para las apps con su propio login, y deja las contraseñas de aplicación para
  herramientas y bots. Siguen soportadas y sin fecha de baja; el OAuth de Bluesky es bastante distinto del
  de las demás redes y todavía no se integra.

## Tokens

- **El token de acceso dura unas dos horas y el de renovación unos 90 días.** Se renueva solo, y el de
  renovación rota: cada renovación trae uno nuevo ([Mantener vivas las conexiones](conexiones.md)).
- Si nadie usa la conexión en 90 días, la sesión vence y hay que volver a cargar la contraseña. La
  renovación anticipada (`social.refresh_expiring`) no ayuda con esto: mira cuándo vence el token de
  acceso, no el de renovación.
- **La identidad es el DID** (`did:plc:…`), no el nombre. El nombre es un dominio y la persona lo puede
  cambiar; el DID no cambia.
- `disconnect` cierra la sesión en Bluesky.

## Publicar

```python
from omnisocial import Draft, Media, MediaKind, PathFile
from omnisocial.bluesky import BlueskyOptions

draft = Draft(
    "Abrimos el local nuevo 🎉 https://ejemplo.com/local #novedad",
    media=(Media(MediaKind.IMAGE, file=PathFile.open("local.jpg", "image/jpeg"), alt_text="El frente"),),
    thread=(Draft("Estamos en Av. Siempreviva 742."),),
    options=BlueskyOptions(langs=("es",)),
)
result = await social.publish.execute(asset_id, draft)
```

- **Los links y los hashtags se marcan solos.** Bluesky no los detecta: sin marcarlos, un link queda como
  texto sin enlace. Las menciones (`@ana.bsky.social`) todavía no se marcan: quedan como texto.
- **Los medios van como archivo.** El video se sube entero en un pedido, y Bluesky lo procesa después de
  publicado: puede tardar en verse.
- **La tarjeta de un link no se arma sola**: `Draft(link=...)` con
  `BlueskyOptions(link_title=..., link_description=...)`. Sin título se muestra la URL. Va sin medios.
- **Sale en una sola etapa.** No queda nada pendiente.
- **Un hilo es una cadena de respuestas.** Si se corta, lo anterior ya salió: queda
  `PUBLISHED_WITH_ERROR`, con la dirección del primer post y la parte que falló.
- `BlueskyOptions(reply_to="at://…")` responde a un post.

## Límites

| Qué | Límite |
|---|---|
| Texto | 300 grafemas (un emoji compuesto cuenta uno). La librería cuenta caracteres, que nunca son menos: un texto con muchos emojis compuestos puede rechazarse de más |
| Imágenes | Hasta 4, de hasta 2 MB cada una |
| Video | 1, hasta 50 MB en la librería |
| Iniciar sesión | 30 intentos cada 5 minutos y 300 por día, por cuenta |
| Escribir | Un presupuesto por puntos: crear cuesta 3, con 5.000 puntos por hora y 35.000 por día |

El límite de uso dice a qué hora vuelve (`ratelimit-reset`): `Refused(RATE_LIMITED)` trae los segundos que
faltan. Fuente: [Images and video](https://atproto.com/guides/images-and-video) y
[Rate limits](https://docs.bsky.app/docs/advanced-guides/rate-limits) (verificado 2026-11).

## Errores

Los errores vienen con nombre:

| Error | Resultado |
|---|---|
| `InvalidToken`, `AccountTakedown`, `AccountDeactivated` | La conexión queda inválida |
| `ExpiredToken` | No invalida la conexión: el token se renueva |
| `RateLimitExceeded` | `Refused(RATE_LIMITED)` |
| `InvalidRequest`, `BlobTooLarge`, `InvalidMimeType` | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |
| `UpstreamFailure` | `ProviderError`, pasajero |

## Lo que conviene saber

- **Un post se identifica con una dirección** (`at://did:plc:…/app.bsky.feed.post/…`): es el `post_id` y
  el id de los comentarios.
- **Para responder o dar like hace falta el contenido exacto del post** además de su dirección, así que
  cada una de esas acciones hace antes una lectura.
- **Una cuenta que no existe responde 400**, no 404.
- **Los perfiles públicos se leen de un servidor aparte** (`public.api.bsky.app`), sin sesión.

!!! warning "A confirmar con la API real"
    - **El tope de un video.** La librería acepta hasta 50 MB, pero Bluesky lo fue subiendo: fuentes de
      2025 dicen 100 MB y 3 minutos, y otras más nuevas, 300 MB y 10 minutos.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
