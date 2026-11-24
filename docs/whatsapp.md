# WhatsApp Business: la ventana de 24 horas, las plantillas y lo que conviene saber

Es la plataforma de WhatsApp Business de Meta (la API en la nube). Es otra red (`whatsapp`), con su
propia configuración: no usa el adaptador de Meta.

## Qué cubre

| Capacidad   | Qué hace |
|-------------|----------|
| `login`     | El diálogo de Facebook, con la configuración de la app. |
| `assets`    | Los números de teléfono (`whatsapp_number`) de las cuentas a las que el token tiene acceso. |
| `messaging` | Mandar un texto, una imagen o un video, citar un mensaje y mandar plantillas. |
| `webhooks`  | Los mensajes que llegan, con sus adjuntos, y el estado de los que se mandaron. |

**Sin historial.** No hay forma de pedir los mensajes pasados: llegan por avisos y hay que guardarlos.
`list_conversations` y `list_messages` devuelven `Refused(NOT_SUPPORTED)`, y `read_inbox` no trae nada.

## Armado

```python
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.whatsapp import WhatsAppConfig, whatsapp_provider

whatsapp = whatsapp_provider(
    WhatsAppConfig(
        app_id="...",
        app_secret="...",
        config_id="...",  # la configuración de "Facebook Login for Business"
        webhook_verify_token="...",
    ),
    RetryingTransport(HttpxTransport()),
)
```

## Conectar

Hay dos caminos, y los dos terminan igual:

- **Con el diálogo** (`start_authorization`): la persona elige a qué cuentas de WhatsApp Business da
  acceso. `config_id` es la configuración que define qué se pide.
- **Con un token que ya se tiene** (`register_system_connection`): el de un usuario de sistema del propio
  portfolio, o el que devuelve el alta embebida de Meta, que corre en el navegador y no pasa por este
  diálogo.

```python
connected = await social.register_system_connection.execute(
    "whatsapp", owner=owner, token=Token(TokenKind.SYSTEM, "EAAG...")
)
```

- **Las cuentas salen del token.** Meta dice a cuáles tiene acceso con cada permiso; para saberlo se
  consulta con las credenciales de la app. Si el token tiene acceso a todo un portfolio y no lo detalla,
  hace falta `business_id` (y el permiso `business_management`, en `BUSINESS_SCOPES`).
- **El alta de un número no la hace la librería**: suscribir la app a la cuenta y registrar el número son
  pasos del alta embebida.
- Un token de integración no trae vencimiento.

## La ventana de 24 horas

Cada mensaje de la persona abre 24 horas para escribirle libremente. Fuera de eso solo sale una
plantilla aprobada.

Como no hay historial, la librería no puede saber cuándo escribió por última vez: se lo dice la app, que
lo guardó cuando llegó el aviso.

```python
from omnisocial import OutboundMessage, Recipient, TemplateRef

to = Recipient(event.conversation_external_id, last_inbound_at=event.occurred_at)
sent = await social.send_message.execute(number.id, text="¡Hola, Ana!", to=to)
# Refused(OUTSIDE_REPLY_WINDOW) si pasaron las 24 horas o no se sabe cuándo escribió.

template = OutboundMessage(template=TemplateRef("recordatorio", "es_AR", components=(...)))
sent = await social.send_message.execute(number.id, message=template, to=Recipient("5491155550199"))
```

- **Las plantillas de la cuenta** salen de `list_choices.execute(number.id, "templates")`, con su idioma
  y su estado. Solo las `APPROVED` se pueden mandar.
- **Los valores de las variables** van en `components`, en la forma que pide WhatsApp.
- **WhatsApp puede aceptar un mensaje y avisar después que no salió.** El pedido responde bien y más
  tarde llega un aviso con estado `FAILED` y el motivo. Hay que mirar los avisos, no solo la respuesta.

## Mandar

- **Texto** hasta 4096 caracteres. **Un adjunto** por mensaje, por URL: una imagen (5 MB) o un video
  (16 MB), con un texto de hasta 1024 caracteres.
- **Citar un mensaje**: `OutboundMessage("…", reply_to=event.object_external_id)`.
- **El destinatario es el teléfono con código de país, o el id de usuario** que vino en el aviso.
  WhatsApp ya no siempre manda el teléfono: cuando la persona tiene nombre de usuario puede venir solo
  un id propio del negocio (`AR.1349…`). Los dos sirven para responder: conviene guardar el que vino en
  `conversation_external_id` y no asumir que es un teléfono.

## Avisos

```python
received = await social.handle_webhook.execute("whatsapp", request=request, on_events=guardar)
```

- **Mensajes que llegan**: `EventKind.MESSAGE` con `EventAction.CREATED`. Traen quién escribió
  (`actor_id`, `actor_name`), el texto y los adjuntos. `inbox_item_from_event` les da la forma de la
  bandeja.
- **Los adjuntos traen un id, no una URL** (`Attachment.media_id`). El archivo se le pide a Meta con ese
  id y el token; el id vence a los 7 días.
- **Estado de lo que se mandó**: `EventAction.UPDATED` con `status` (`SENT`, `DELIVERED`, `READ`,
  `FAILED`). Si falló, `text` dice por qué.
- **La firma** es la de Meta (`X-Hub-Signature-256`, con el secreto de la app), y la URL se confirma con
  `webhook_verify_token`.
- El activo de un aviso es el número (`phone_number_id`).

## Lo que conviene saber

- **Meta cobra por mensaje** desde julio de 2025: las plantillas se cobran, las respuestas dentro de la
  ventana no.
- **El número tiene una calificación de calidad** (`quality_rating` en los datos del activo). Si la gente
  marca los mensajes como no deseados, baja, y WhatsApp limita al número: vuelve
  `Refused(RATE_LIMITED)`.
- **"Fuera de la ventana" dicho por WhatsApp** (código 131047) no vuelve como negativa sino como un error
  de la red, porque la librería ya lo comprueba antes con lo que le dijo la app.
- Sin verificar: el estado HTTP con que llega cada código de error, y si los tokens del alta embebida
  vencen. Nada se probó contra la API real.
