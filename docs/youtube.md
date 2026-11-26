# YouTube

El canal de YouTube de quien autoriza, con la YouTube Data API v3: videos, subidas, comentarios y
contadores. También perfiles públicos de cualquier canal.

## Qué cubre

| Capacidad         | Qué hace                                                                          |
|-------------------|-----------------------------------------------------------------------------------|
| `login`           | OAuth de Google: autorizar, canjear el código, renovar, revocar.                  |
| `assets`          | El canal de quien autorizó es el único activo (`youtube_channel`).                |
| `content`         | Los videos del canal, con vistas, likes y comentarios.                            |
| `publishing`      | Subir un video por partes, saber cómo terminó el procesamiento y borrarlo.        |
| `comments`        | Leer hilos, responder, ocultar y rechazar.                                        |
| `insights`        | Contadores del canal: suscriptores, vistas y cantidad de videos.                  |
| `public_profiles` | Cualquier canal por `@nombre` o por id, con una clave de API y sin que nadie autorice. |

**Sin avisos, sin mensajes, sin like a comentarios.** YouTube avisa de videos nuevos con otro mecanismo
(PubSubHubbub, con XML y firma SHA-1) que todavía no se integra; no tiene mensajes privados, y su API no
permite dar like a un comentario. Las publicaciones de la pestaña Comunidad tienen API, pero solo para
proyectos aprobados en un piloto.

## Crear la app

1. En [Google Cloud](https://console.cloud.google.com/), un proyecto con la **YouTube Data API v3**
   activada.
2. Una **pantalla de consentimiento** de OAuth.
3. Una credencial OAuth del tipo **aplicación web**, con la URL de retorno
   `https://api.ejemplo.com/oauth/youtube/callback`.
4. Para perfiles públicos, una **clave de API**.

- **Mientras la pantalla de consentimiento está en "Testing", los tokens de renovación vencen a los 7
  días.** Hay que pasarla a producción para que duren.
- Los permisos de YouTube son "sensibles": pasar a producción con ellos pide la verificación de Google.

Documentación oficial: [YouTube Data API](https://developers.google.com/youtube/v3) (verificado 2026-11).

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.postgres import PostgresQuotaLedger
from omnisocial.youtube import (
    CONNECT_SCOPES,
    MODERATE_SCOPES,
    PUBLISH_SCOPES,
    YouTubeConfig,
    youtube_provider,
)

youtube = youtube_provider(
    YouTubeConfig(
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        api_key=os.environ["YOUTUBE_API_KEY"],  # opcional: para perfiles públicos
        connect_scopes=CONNECT_SCOPES + MODERATE_SCOPES + PUBLISH_SCOPES,
    ),
    RetryingTransport(HttpxTransport()),
    quota=PostgresQuotaLedger(pool),  # opcional: ver "Límites"
)
```

`pool` es el de [Instalar y armar](instalar-y-armar.md#armar-omnisocial). Solo con
`YouTubeConfig(api_key=...)`, sin app, el proveedor ofrece perfiles públicos y nada más.

## Permisos

| Constante         | Permiso | Para qué |
|-------------------|---------|----------|
| `CONNECT_SCOPES`  | `https://www.googleapis.com/auth/youtube.readonly` | El canal, sus videos, contadores y comentarios. |
| `MODERATE_SCOPES` | `https://www.googleapis.com/auth/youtube.force-ssl` | Responder y moderar comentarios, y borrar videos. |
| `PUBLISH_SCOPES`  | `https://www.googleapis.com/auth/youtube.upload` | Subir videos. |

Los dos últimos no se piden por defecto. Sin ellos, la operación vuelve `Refused(MISSING_PERMISSION)`.

## Tokens

- El token de acceso dura una hora y se renueva solo.
- **Google manda el token de renovación solo la primera vez que la persona autoriza.** Por eso el login pide
  siempre el consentimiento (`prompt=consent`), y al reconectar se conserva el anterior si no llega uno nuevo.
- Un token de renovación deja de servir si no se usa en 6 meses, si la persona quita el acceso o si la app
  acumula más de 100 por cuenta. Renovar responde `invalid_grant` y la conexión queda inválida.

## Publicar

```python
from omnisocial import Draft, Media, MediaKind, PathFile
from omnisocial.youtube import YouTubeOptions

draft = Draft(
    "Guiso de lentejas\n\nPaso a paso, en 20 minutos.",
    media=(Media(MediaKind.VIDEO, file=PathFile.open("guiso.mp4", "video/mp4")),),
    options=YouTubeOptions(privacy_status="unlisted", tags=("cocina",)),
)
result = await social.publish.execute(asset_id, draft, idempotency_key="guiso-lentejas")
```

- **El video va como archivo.** YouTube no va a buscar una URL. `PathFile` lo lee del disco de a partes, sin
  cargarlo en memoria; `BytesFile` sirve si ya está en memoria.
- **La subida es reanudable.** El archivo va en partes de 8 MB (`upload_chunk_bytes`, múltiplo de 256 KB).
  Si una parte falla, se le pregunta a YouTube hasta dónde recibió y se sigue desde ahí; después de tres
  fallas seguidas (`upload_attempts`) se abandona.
- **Una subida abandonada con certeza no salió**: vuelve `Refused(NOT_PUBLISHED)` y se puede reintentar con
  la misma clave. La excepción es la última parte: si se pierde su respuesta, YouTube pudo haber creado el
  video, y la publicación queda en duda (`STARTED`) en vez de arriesgar un duplicado.
- **Queda `PENDING` mientras YouTube lo procesa**, ya con `post_id` y `url`. `check_publication` dice cómo
  terminó: `PUBLISHED`, o `FAILED` con el motivo (`codec`, `duplicate`, `copyright`…). Cada consulta cuesta
  una unidad.
- **El texto es la descripción** (hasta 5.000 bytes: las letras con tilde cuentan dos). El título es
  `YouTubeOptions.title` o la primera línea del texto, hasta 100 caracteres. Ninguno admite `<` ni `>`.
- **Si no se dice otra cosa, sale público**, igual que en la API. `made_for_kids` hay que declararlo.
- **Un Short es un video común**: YouTube lo clasifica solo, por la forma (vertical o cuadrado) y la
  duración.
- Sin miniatura propia ni primer comentario, por ahora.

## Comentarios

- **Ocultar es retener para revisión** (`heldForReview`): deja de verse y se puede volver a publicar.
- **Borrar es rechazar** (`rejected`): lo saca para todos, con sus respuestas, y no tiene vuelta atrás. La
  API solo deja borrar de verdad un comentario a su autor.
- Las respuestas de un hilo pueden venir incompletas; `reply_count` dice cuántas hay.

## Límites

La cuota es **del proyecto de Google, no de cada canal**: todos los clientes de la app comparten la misma,
y se reinicia a medianoche, hora del Pacífico.

| Qué | Cupo por día (valores por defecto) | Costo |
|-----|-----------------------------------|-------|
| Leer (canal, playlist, videos, comentarios) | 10.000 unidades | 1 por llamada |
| Escribir (responder, moderar, borrar un video) | las mismas 10.000 | 50 por llamada: 200 respuestas agotan el día |
| Subir un video | 100 subidas, en un cupo aparte | 1 por subida |
| Buscar | 100 búsquedas, en un cupo aparte | no se usa |

Los cupos separados para subir y buscar rigen desde el 1 de junio de 2026; antes, subir un video costaba
cientos de unidades del cupo general
([historial de cambios](https://developers.google.com/youtube/v3/revision_history),
[calculadora de cuota](https://developers.google.com/youtube/v3/determine_quota_cost), verificado
2026-11). Conviene confirmar los números del proyecto en la consola de Google Cloud.

- **Nunca se busca.** Los videos de un canal salen de su playlist de subidas, y un canal se encuentra por id
  o por `@nombre`. Una cuenta que no existe no gasta el cupo de búsquedas.
- **Presupuesto propio.** Con `quota=` el proveedor anota lo que gasta cada llamada y, cuando el día se
  agota, devuelve `Refused(QUOTA_EXHAUSTED)` sin llamar a YouTube (`detail` lo dice; el código del error es
  `local_budget`). `YouTubeConfig(quota_units=8000)` deja una reserva para lo que la app haga por fuera.
  `InMemoryQuotaLedger` sirve en un solo proceso; `PostgresQuotaLedger` lo comparte entre varios.
- **El canal tiene su propio tope diario de subidas**, además del cupo del proyecto.

## Errores

YouTube dice el motivo en `error.errors[0].reason`. Un 403 no siempre es la cuota:

| Motivo | Resultado |
|---|---|
| `authError` (401) | La conexión queda inválida. Como el token se renueva antes de vencer, quiere decir que la persona quitó el acceso |
| `insufficientPermissions` | `Refused(MISSING_PERMISSION)` |
| `quotaExceeded`, `dailyLimitExceeded` | `Refused(QUOTA_EXHAUSTED)` |
| `rateLimitExceeded`, `userRateLimitExceeded`, `uploadRateLimitExceeded`, `uploadLimitExceeded` | `Refused(RATE_LIMITED)` |
| `invalidTitle`, `invalidDescription`, `invalidVideoMetadata`, `invalidCategoryId`, `forbiddenPrivacySetting`, `commentTextTooLong`, `commentTextRequired` | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |
| `backendError` | `ProviderError`, pasajero |
| `commentsDisabled` | No es un error: un video sin comentarios devuelve una lista vacía |

## Lo que conviene saber

- **Un token es de un solo canal.** Al autorizar, Google hace elegir uno; quien administra varios conecta
  cada uno por separado. Una cuenta de Google sin canal no se puede conectar.
- **Los suscriptores vienen redondeados a tres cifras**, y no vienen si el canal los oculta.
- **Los contadores no tienen historia.** `read_insights` devuelve una foto del momento; para la evolución,
  la app guarda una lectura por día. Las series históricas están en YouTube Analytics, que todavía no se usa.
- **Likes ocultos o comentarios desactivados**: el contador no viene, y eso no es cero.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
