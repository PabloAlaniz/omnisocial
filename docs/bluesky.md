# Bluesky: contraseñas de aplicación y lo que conviene saber

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

**Sin mensajes, sin webhooks, sin ocultar respuestas por ahora.** Bluesky tiene mensajes y un flujo de
eventos en tiempo real, que todavía no se integran. Ocultar una respuesta existe, pero es editar una regla
del hilo entero.

## Armado

**No hay app que registrar.** No hay clave ni secreto: cada persona conecta con una contraseña que genera
en su cuenta.

```python
from omnisocial.bluesky import BlueskyConfig, bluesky_provider
from omnisocial.httpx import HttpxTransport, RetryingTransport

bluesky = bluesky_provider(BlueskyConfig(), RetryingTransport(HttpxTransport()))
```

## Conectar

La persona genera una **contraseña de aplicación** en Bluesky (Configuración → Privacidad y seguridad →
Contraseñas de aplicación) y la carga junto con su nombre:

```python
result = await social.connect_with_credentials.execute(
    "bluesky",
    owner=f"proyecto:{project_id}",
    credentials={"identifier": "ana.bsky.social", "password": "abcd-efgh-ijkl-mnop"},
)
match result:
    case Connected(connection=connection, assets=assets): ...
    case Refused(reason=Refusal.PROVIDER_DENIED, detail=detail): ...  # no la aceptó
    case Refused(reason=Refusal.RATE_LIMITED, retry_after=seconds): ...  # demasiados intentos
```

- **La contraseña no se guarda.** Se cambia por una sesión y se descarta; lo que queda guardado, cifrado,
  es la sesión.
- **Tiene que ser una contraseña de aplicación, no la de la cuenta.** Con la verificación por mail
  activada, la de la cuenta no sirve y Bluesky pide un código: vuelve `Refused(PROVIDER_DENIED)` con un
  detalle que lo explica. Además, una contraseña de aplicación se puede quitar sin cambiar la de la cuenta.
- **Iniciar sesión tiene un límite bajo**: 30 intentos cada 5 minutos y 300 por día, por cuenta.
- Quien tiene su propio servidor de datos lo indica con `"server": "pds.ejemplo.com"`. Si no, se usa
  `bsky.social`. El servidor se valida: tiene que ser un dominio público.
- `omnisocial.bluesky.FIELDS` dice qué pedirle a la persona y cuál de los datos es secreto.
- Bluesky recomienda OAuth para las apps con su propio login, y deja las contraseñas de aplicación para
  herramientas y bots. Siguen soportadas y sin fecha de baja; el OAuth de Bluesky es bastante distinto del
  de las demás redes y todavía no se integra.

## La sesión

- **El token de acceso dura unas dos horas y el de renovación unos 90 días.** Se renueva solo, y el de
  renovación rota: cada renovación trae uno nuevo.
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
```

- **Los links y los hashtags se marcan solos.** Bluesky no los detecta: sin marcarlos, un link queda como
  texto sin enlace. Las menciones (`@ana.bsky.social`) todavía no se marcan: quedan como texto.
- **300 caracteres.** El límite real es de 300 grafemas (un emoji compuesto cuenta uno); acá se cuentan
  caracteres, que nunca son menos, así que un texto con muchos emojis compuestos puede rechazarse de más.
- **Hasta 4 imágenes (de hasta 2 MB cada una) o un video**, como archivo. El video se sube entero en un
  pedido, hasta 50 MB, y Bluesky lo procesa después de publicado: puede tardar en verse.
- **La tarjeta de un link no se arma sola**: `Draft(link=...)` con
  `BlueskyOptions(link_title=..., link_description=...)`. Sin título se muestra la URL. Va sin medios.
- **Sale en una sola etapa.** No queda nada pendiente.
- **Un hilo es una cadena de respuestas.** Si se corta, lo anterior ya salió: queda
  `PUBLISHED_WITH_ERROR`, con la dirección del primer post y la parte que falló.
- `BlueskyOptions(reply_to="at://…")` responde a un post.
- **Escribir tiene un presupuesto por puntos**: crear cuesta 3, con 5.000 puntos por hora y 35.000 por día.

## Lo que conviene saber

- **Un post se identifica con una dirección** (`at://did:plc:…/app.bsky.feed.post/…`): es el `post_id` y
  el id de los comentarios.
- **Para responder o dar like hace falta el contenido exacto del post** además de su dirección, así que
  cada una de esas acciones hace antes una lectura.
- **Los errores vienen con nombre** (`InvalidToken`, `ExpiredToken`…). Un token de acceso vencido no
  invalida la conexión: se renueva.
- **Una cuenta que no existe responde 400**, no 404.
- **El límite de uso dice a qué hora vuelve** (`ratelimit-reset`): `Refused(RATE_LIMITED)` trae los segundos
  que faltan.
- **Los perfiles públicos se leen de un servidor aparte** (`public.api.bsky.app`), sin sesión.
