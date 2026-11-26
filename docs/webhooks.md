# Avisos (webhooks)

Algunas redes avisan cuando pasa algo: un comentario nuevo, un mensaje, un cambio en un mensaje enviado.
La librería recibe el aviso, comprueba la firma, lo traduce a un `SocialEvent` y le dice a la app a qué
activos guardados corresponde.

Qué redes mandan avisos está en la columna "Webhooks" de la [matriz](index.md). Cómo suscribirse en cada
red está en su página.

## Recibirlos

```python
from collections.abc import Sequence

from omnisocial import RoutedEvent
from omnisocial.starlette import webhook_routes


async def encolar(events: Sequence[RoutedEvent]) -> None:
    for routed in events:
        for asset in routed.assets:  # un aviso puede corresponder a varios dueños
            await cola.put((asset.owner, asset.id, routed.event))


app.router.routes.extend(webhook_routes(social, on_events=encolar))  # /webhooks/{provider}
```

`GET /webhooks/{provider}` responde el saludo con que la red confirma la suscripción, y
`POST /webhooks/{provider}` recibe los avisos.

Conviene que `on_events` solo encole y responda rápido: las redes reintentan, o desactivan la
suscripción, si la respuesta tarda.

## Qué responde

Los avisos pasan por [omniwebhook](https://pypi.org/project/omniwebhook/), que verifica la firma y reserva
cada aviso antes de procesarlo:

| Llega | Respuesta | `on_events` |
|---|---|---|
| Aviso firmado y nuevo | 200 | se llama una vez |
| El mismo aviso otra vez | 200 | no se vuelve a llamar |
| `on_events` lanza una excepción | 500 | la red reintenta y entra |
| Firma inválida o ausente | 401 | no se llama |
| Sin secreto configurado | 500 | no se llama |

La deduplicación es por entrega: si una entrega trae varios eventos y `on_events` falla, se reprocesa
entera. Conviene que lo que haga `on_events` sea idempotente por evento.

## Qué trae un aviso

| Campo de `SocialEvent` | Qué es |
|---|---|
| `provider`, `kind`, `action` | La red, de qué es (comentario, mensaje…) y qué pasó (creado, editado, borrado…) |
| `asset_external_id` | El activo en la red. `RoutedEvent.assets` ya trae los activos guardados que le corresponden |
| `object_external_id` | El comentario, mensaje o publicación |
| `actor_id`, `actor_name`, `text`, `occurred_at` | Quién, qué escribió y cuándo |
| `conversation_external_id` | En un mensaje, la conversación. Es lo que hay que guardar para [responder](comentarios-y-mensajes.md#redes-sin-historial-whatsapp-y-telegram) |
| `attachments` | Los adjuntos de un mensaje |
| `status` | En un aviso sobre un mensaje enviado, hasta dónde llegó: enviado, entregado, leído o fallido |

Para mostrar avisos junto con lo que se lee de la red, `inbox_item_from_event` los convierte a la forma de
la [bandeja](comentarios-y-mensajes.md#la-bandeja).

## Borrado de datos en Meta

Meta exige un callback de borrado de datos para publicar una app. `omnisocial.starlette` trae la ruta
(`meta_data_deletion_routes`): ver [Meta](meta.md).
