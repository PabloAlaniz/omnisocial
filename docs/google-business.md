# Google Business Profile: sedes, novedades, reseñas y lo que conviene saber

## Qué cubre

| Capacidad    | Qué hace |
|--------------|----------|
| `login`      | Login con Google. |
| `assets`     | Las sedes que la persona administra (`google_business_location`), de todas sus cuentas. |
| `content`    | Las novedades de una sede. |
| `publishing` | Una novedad con fotos y un botón; un evento o una oferta. Borrar. |
| `comments`   | Las reseñas, con sus estrellas: leerlas, responderlas y borrar la respuesta. |
| `insights`   | Impresiones, llamadas, visitas al sitio, pedidos de indicaciones, por día o en total. |

**Sin mensajes y sin webhooks.** Google cerró la mensajería de las fichas en 2024. Los avisos de reseñas
nuevas salen solo por Cloud Pub/Sub, que no se integra.

## Antes de integrar

**Google aprueba cada proyecto antes de darle acceso a estas APIs.** Se pide con un formulario. Hasta
entonces el cupo del proyecto es cero y todo vuelve `Refused(RATE_LIMITED)`.

## Armado

```python
from omnisocial.google_business import GoogleBusinessConfig, google_business_provider
from omnisocial.httpx import HttpxTransport, RetryingTransport

google_business = google_business_provider(
    GoogleBusinessConfig(client_id="...", client_secret="...", language_code="es"),
    RetryingTransport(HttpxTransport()),
)
```

- **Un solo permiso cubre todo** (`business.manage`): ver las sedes, publicar y responder reseñas. Ya
  está en los permisos de conexión por defecto.
- **El token de acceso dura una hora** y se renueva solo.
- **El id de una sede lleva la cuenta por delante** (`accounts/111/locations/456`). Si la misma sede se
  ve desde dos cuentas, queda una vez.

## Publicar

```python
from omnisocial import Draft, Media, MediaKind
from omnisocial.google_business import GoogleBusinessOptions

draft = Draft(
    "Llegó el menú de otoño.",
    media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/menu.jpg"),),
    options=GoogleBusinessOptions(action="ORDER", action_url="https://ejemplo.com/pedir"),
)
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

Se leen con las operaciones de comentarios:

```python
reviews = await social.list_comments.execute(location.id, object_id=location.external_id)
for review in reviews.value:
    review.rating, review.text, review.author_name, review.replies
await social.reply_to_comment.execute(location.id, comment_id=review.external_id, text="¡Gracias!")
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

## Lo que conviene saber

- **Son cuatro APIs en cuatro dominios** (cuentas, sedes, novedades y reseñas, métricas). Las novedades
  y las reseñas siguen en la versión 4.
- **300 pedidos por minuto por proyecto, y 10 cambios por minuto en una misma sede.** Ese segundo tope
  no se puede subir.
- **"Sin permiso" a secas no es un permiso faltante**: la cuenta no administra esa sede.
- Sin verificar: el límite de 1500 caracteres y el de 10 fotos por novedad, el orden en que vienen las
  novedades, y qué responde Google al publicar en una sede sin verificar. Nada se probó contra la API
  real.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
