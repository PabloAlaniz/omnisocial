# Google Business Profile

Las fichas de negocio en Google (las sedes que aparecen en Maps y en la Búsqueda): novedades, reseñas y
métricas.

## Qué cubre

| Capacidad    | Qué hace |
|--------------|----------|
| `login`      | Login con Google. |
| `assets`     | Las sedes que la persona administra (`google_business_location`), de todas sus cuentas. |
| `content`    | Las novedades de una sede. |
| `publishing` | Una novedad con fotos y un botón; un evento o una oferta. Borrar. |
| `comments`   | Las reseñas, con sus estrellas: leerlas, responderlas y borrar la respuesta. |
| `insights`   | Impresiones, llamadas, visitas al sitio, pedidos de indicaciones, por día o en total. |

**Sin mensajes y sin avisos.** Google cerró la mensajería de las fichas en 2024. Los avisos de reseñas
nuevas salen solo por Cloud Pub/Sub, que no se integra.

## Antes de empezar

**Google aprueba cada proyecto antes de darle acceso a estas APIs.** Se pide con un
[formulario](https://developers.google.com/my-business/content/prereqs) (verificado 2026-11). Hasta
entonces el cupo del proyecto es cero y todo vuelve `Refused(RATE_LIMITED)`.

## Crear la app

1. En [Google Cloud](https://console.cloud.google.com/), un proyecto con las APIs de Business Profile
   activadas: *My Business Account Management*, *My Business Business Information*, *Business Profile
   Performance* y *Google My Business* (novedades y reseñas).
2. Una pantalla de consentimiento de OAuth y una credencial del tipo **aplicación web**, con la URL de
   retorno `https://api.ejemplo.com/oauth/google_business/callback`.
3. Pedir el acceso con el formulario de arriba, con el número del proyecto.

## Armado

```python
import os

from omnisocial.google_business import GoogleBusinessConfig, google_business_provider
from omnisocial.httpx import HttpxTransport, RetryingTransport

google_business = google_business_provider(
    GoogleBusinessConfig(
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        language_code="es",
    ),
    RetryingTransport(HttpxTransport()),
)
```

Para repartir el ritmo de pedidos entre procesos, `rate_limits=` (ver
[Operar](operar.md#limites-de-uso-entre-varios-procesos)).

## Conectar

Con el diálogo de Google. **El id de una sede lleva la cuenta por delante** (`accounts/111/locations/456`).
Si la misma sede se ve desde dos cuentas, queda una vez.

## Permisos

| Constante | Permisos | Para qué |
|---|---|---|
| `LOGIN_SCOPES` | `openid`, `email`, `profile` | Saber quién es la persona |
| `CONNECT_SCOPES` | los anteriores y `https://www.googleapis.com/auth/business.manage` | Todo: ver las sedes, publicar y responder reseñas |

## Tokens

El token de acceso dura una hora y se renueva solo, como en todas las APIs de Google.

## Publicar

```python
from omnisocial import Draft, Media, MediaKind
from omnisocial.google_business import GoogleBusinessOptions

draft = Draft(
    "Llegó el menú de otoño.",
    media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/menu.jpg"),),
    options=GoogleBusinessOptions(action="ORDER", action_url="https://ejemplo.com/pedir"),
)
result = await social.publish.execute(asset_id, draft)
```

- **Las opciones son opcionales**: sin ellas sale una novedad común, en el idioma de la configuración.
- **El botón** es `BOOK`, `ORDER`, `SHOP`, `LEARN_MORE`, `SIGN_UP` o `CALL`. Todos llevan URL salvo
  `CALL`, que llama al teléfono de la sede.
- **Un evento o una oferta** (`topic="EVENT"` u `"OFFER"`) llevan título, comienzo y fin, **en la hora
  de la sede**. Una oferta puede llevar cupón, link y condiciones, y no lleva botón.
- **Las fotos van por URL.** No se publican videos ni novedades de producto.
- **Google puede dejar una novedad en revisión**: queda `PENDING`, y `check_publication` dice si salió o
  la rechazó.
- **Una sede sin verificar** puede no publicar: Google la rechaza y vuelve `Refused(CONTENT_REJECTED)`.

## Reseñas

Se leen con las operaciones de [comentarios](comentarios-y-mensajes.md):

```python
from omnisocial import Done

# `location` es el activo de la sede.
reviews = await social.list_comments.execute(location.id, object_id=location.external_id)
if isinstance(reviews, Done):
    for review in reviews.value:
        print(review.rating, review.author_name, review.text, len(review.replies))
    await social.reply_to_comment.execute(
        location.id, comment_id=reviews.value[0].external_id, text="¡Gracias!"
    )
```

- **Las reseñas son de la sede**, no de una publicación: `object_id` no se usa.
- **`rating` son las estrellas**, de 1 a 5. Una reseña puede no tener texto.
- **Una reseña tiene una sola respuesta.** Responder de nuevo la reemplaza; borrar borra la respuesta
  del negocio. La reseña de un cliente no se puede borrar ni ocultar.
- **La respuesta tiene hasta 4096 bytes** (no caracteres), y solo se puede responder en una sede
  verificada.

## Métricas

`BUSINESS_IMPRESSIONS` (la suma de las cuatro de Google: Maps y Búsqueda, en computadora y en celular),
las cuatro por separado, `CALL_CLICKS`, `WEBSITE_CLICKS`, `BUSINESS_DIRECTION_REQUESTS`,
`MESSAGING_CLICKS`, `BUSINESS_BOOKINGS` y `BUSINESS_FOOD_MENU_CLICKS`.

- Con período diario, un punto por día; si no, el total del tramo. Sin ventana, los últimos 30 días.
- **No hay métricas por novedad**: Google las retiró en 2023.

## Límites

| Qué | Límite |
|---|---|
| Pedidos | 300 por minuto por proyecto |
| Cambios en una misma sede | 10 por minuto. No se puede subir |
| Respuesta a una reseña | 4.096 bytes |

## Errores

Google dice qué pasó en `error.status`:

| Estado | Resultado |
|---|---|
| `UNAUTHENTICATED` (401) | La conexión queda inválida |
| `ACCESS_TOKEN_SCOPE_INSUFFICIENT` | `Refused(MISSING_PERMISSION)` |
| `RESOURCE_EXHAUSTED`, `RATE_LIMIT_EXCEEDED` | `Refused(RATE_LIMITED)`. También es lo que responde un proyecto sin acceso aprobado |
| `INVALID_ARGUMENT`, `FAILED_PRECONDITION` (400) | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)`. `FAILED_PRECONDITION` suele ser una sede sin verificar |

**`PERMISSION_DENIED` a secas no es un permiso faltante**: la cuenta no administra esa sede, y reconectar
no lo arregla.

## Lo que conviene saber

- **Son cuatro APIs en cuatro dominios** (cuentas, sedes, novedades y reseñas, métricas). Las novedades
  y las reseñas siguen en la versión 4.

!!! warning "A confirmar con la API real"
    - El límite de 1.500 caracteres y el de 10 fotos por novedad.
    - El orden en que vienen las novedades.
    - Qué responde Google al publicar en una sede sin verificar.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
