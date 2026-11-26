# WhatsApp Business

Mensajes con la plataforma de WhatsApp Business de Meta (la API en la nube): la ventana de 24 horas, las
plantillas y los avisos.

## Qué cubre

| Capacidad   | Qué hace |
|-------------|----------|
| `login`     | El diálogo de Facebook, con la configuración de la app. |
| `assets`    | Los números de teléfono (`whatsapp_number`) de las cuentas a las que el token tiene acceso. |
| `messaging` | Mandar un texto, una imagen o un video, citar un mensaje y mandar plantillas. |
| `webhooks`  | Los mensajes que llegan, con sus adjuntos, y el estado de los que se mandaron. |

Es otra red (`whatsapp`), con su propia configuración: no usa el adaptador de [Meta](meta.md), aunque la
app sea la misma.

**Sin historial.** No hay forma de pedir los mensajes pasados: llegan por avisos y hay que guardarlos.
`list_conversations` y `list_messages` devuelven `Refused(NOT_SUPPORTED)`, y `read_inbox` no trae nada.
Ver [mensajes sin historial](comentarios-y-mensajes.md#redes-sin-historial-whatsapp-y-telegram).

## Antes de empezar

- Un **portfolio comercial** de Meta, verificado para pasar de los límites de prueba.
- Una **cuenta de WhatsApp Business** con un número dado de alta. El alta (registrar el número, suscribir
  la app a la cuenta) no la hace la librería: es parte del alta embebida de Meta o se hace en el panel.

## Crear la app

1. En [developers.facebook.com/apps](https://developers.facebook.com/apps), una app del tipo **Empresa**
   con el producto **WhatsApp**.
2. Agregar **Facebook Login para empresas** y crear una **configuración** que pida los permisos de
   WhatsApp: su id es el `config_id`.
3. Cargar la URL de retorno `https://api.ejemplo.com/oauth/whatsapp/callback`.
4. En *WhatsApp → Configuración*, suscribir la URL de avisos `https://api.ejemplo.com/webhooks/whatsapp`
   con el `webhook_verify_token`, y el campo `messages`.

Documentación oficial: [WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/)
(verificado 2026-11).

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.whatsapp import WhatsAppConfig, whatsapp_provider

whatsapp = whatsapp_provider(
    WhatsAppConfig(
        app_id=os.environ["META_APP_ID"],
        app_secret=os.environ["META_APP_SECRET"],
        config_id=os.environ["WHATSAPP_CONFIG_ID"],  # la configuración de Facebook Login para empresas
        webhook_verify_token=os.environ["WHATSAPP_WEBHOOK_VERIFY_TOKEN"],
    ),
    RetryingTransport(HttpxTransport()),
)
```

La versión de la Graph API es `v26.0` por defecto (`api_version`).

## Conectar

Hay dos caminos, y los dos terminan igual:

- **Con el diálogo** (`start_authorization`): la persona elige a qué cuentas de WhatsApp Business da
  acceso. `config_id` define qué se pide.
- **Con un token que ya se tiene** (`register_system_connection`): el de un usuario de sistema del propio
  portfolio, o el que devuelve el alta embebida de Meta, que corre en el navegador y no pasa por este
  diálogo.

```python
import os

from omnisocial import Token, TokenKind

connected = await social.register_system_connection.execute(
    "whatsapp", owner="agencia", token=Token(TokenKind.SYSTEM, os.environ["WHATSAPP_TOKEN"])
)
```

- **Las cuentas salen del token.** Meta dice a cuáles tiene acceso con cada permiso; para saberlo se
  consulta con las credenciales de la app. Si el token tiene acceso a todo un portfolio y no lo detalla,
  hace falta `business_id` (y el permiso `business_management`, en `BUSINESS_SCOPES`).

## Permisos

| Constante | Permisos | Para qué |
|---|---|---|
| `CONNECT_SCOPES` | `whatsapp_business_management`, `whatsapp_business_messaging` | Ver las cuentas, sus números y sus plantillas, y mandar mensajes |
| `BUSINESS_SCOPES` | los anteriores y `business_management` | Además, listar las cuentas de WhatsApp de un portfolio (`business_id`) |

## Tokens

Los tokens de usuario de sistema y los del alta embebida (tokens de *integración comercial*, que Meta emite
para una app y un portfolio) no traen vencimiento. Si la red los rechaza, la conexión queda inválida y hay
que volver a conectar.

## La ventana de 24 horas

Cada mensaje de la persona abre 24 horas para escribirle libremente. Fuera de eso solo sale una
plantilla aprobada.

Como no hay historial, la librería no puede saber cuándo escribió por última vez: se lo dice la app, que
lo guardó cuando llegó el aviso.

```python
from omnisocial import OutboundMessage, Recipient, TemplateRef

# `event` es el SocialEvent del mensaje que llegó; `number_id`, el activo del número.
to = Recipient(event.conversation_external_id, last_inbound_at=event.occurred_at)
sent = await social.send_message.execute(number_id, text="¡Hola, Ana!", to=to)
# Refused(OUTSIDE_REPLY_WINDOW) si pasaron las 24 horas o no se sabe cuándo escribió.

template = OutboundMessage(template=TemplateRef("recordatorio", "es_AR"))
sent = await social.send_message.execute(number_id, message=template, to=Recipient("5491155550199"))
```

- **Las plantillas de la cuenta** salen de `list_choices.execute(number_id, "templates")`, con su idioma
  y su estado. Solo las `APPROVED` se pueden mandar.
- **Los valores de las variables** van en `TemplateRef(..., components=(...))`, en la forma que pide
  WhatsApp.
- **WhatsApp puede aceptar un mensaje y avisar después que no salió.** El pedido responde bien y más
  tarde llega un aviso con estado `FAILED` y el motivo. Hay que mirar los avisos, no solo la respuesta.

## Mandar

- **Citar un mensaje**: `OutboundMessage("…", reply_to=event.object_external_id)`.
- **El destinatario es el teléfono con código de país, o el id de usuario** que vino en el aviso.
  WhatsApp ya no siempre manda el teléfono: cuando la persona tiene nombre de usuario puede venir solo
  un id propio del negocio (`AR.1349…`). Los dos sirven para responder: conviene guardar el que vino en
  `conversation_external_id` y no asumir que es un teléfono.

## Avisos

Se reciben con `webhook_routes`, como en [Avisos](webhooks.md).

- **Mensajes que llegan**: `EventKind.MESSAGE` con `EventAction.CREATED`. Traen quién escribió
  (`actor_id`, `actor_name`), el texto y los adjuntos.
- **Los adjuntos traen un id, no una URL** (`Attachment.media_id`). El archivo se le pide a Meta con ese
  id y el token. El id que llega en un aviso vence a los 7 días, y la URL de descarga que da Meta, a los 5
  minutos ([Media](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media/), verificado
  2026-11). Bajar adjuntos todavía no lo hace la librería.
- **Estado de lo que se mandó**: `EventAction.UPDATED` con `status` (`SENT`, `DELIVERED`, `READ`,
  `FAILED`). Si falló, `text` dice por qué.
- **La firma** es la de Meta (`X-Hub-Signature-256`, con el secreto de la app), y la URL se confirma con
  `webhook_verify_token`.
- El activo de un aviso es el número (`phone_number_id`).

## Límites

| Qué | Límite |
|---|---|
| Texto | 4.096 caracteres |
| Adjuntos | Uno por mensaje, por URL: una imagen (5 MB) o un video (16 MB) |
| Texto de un adjunto | 1.024 caracteres |

- **Meta cobra por mensaje** desde julio de 2025: las plantillas se cobran, las respuestas dentro de la
  ventana no.
- **El número tiene una calificación de calidad** (`quality_rating` en los datos del activo). Si la gente
  marca los mensajes como no deseados, baja, y WhatsApp limita al número: vuelve
  `Refused(RATE_LIMITED)`.

## Errores

| Código | Qué quiere decir | Resultado |
|---|---|---|
| 190 | Token vencido o revocado | La conexión queda inválida |
| 10, 200–299 | Falta un permiso | `Refused(MISSING_PERMISSION)` |
| 130429, 131056, 131048, 80007 | Tope de mensajes del número, al mismo destinatario, por calidad o de la cuenta | `Refused(RATE_LIMITED)` |
| 131047 | Pasaron más de 24 horas: solo sale una plantilla | `ProviderError` |
| 131026, 131009, 131051 | No se puede entregar (no usa WhatsApp, no aceptó los términos, versión vieja) | `ProviderError` |
| 132000, 132001 | La plantilla no existe, no está aprobada en ese idioma o sus variables no coinciden | `ProviderError` |

El 131047 no vuelve como `Refused(OUTSIDE_REPLY_WINDOW)` porque la librería ya lo comprueba antes, con lo
que le dijo la app: si llega, la app le pasó una fecha equivocada.

## Lo que conviene saber

- Guardar el `conversation_external_id` de cada aviso es lo único que permite responder: la librería no
  guarda nada.

!!! warning "A confirmar con la API real"
    - El estado HTTP con que llega cada código de error.
    - Si los tokens del alta embebida vencen.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
