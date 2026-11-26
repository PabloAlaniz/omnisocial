# Telegram

Un bot de Telegram: publicar en canales y grupos, y conversar con quien le escribe.

## Qué cubre

| Capacidad     | Qué hace |
|---------------|----------|
| `credentials` | Un bot se conecta con el token que da @BotFather. |
| `assets`      | El bot (`telegram_bot`). |
| `publishing`  | Un texto, una foto, un video o un álbum en un canal o en un grupo. Borrar. |
| `messaging`   | Escribirle a quien le escribió al bot. |
| `webhooks`    | Mensajes privados, mensajes de grupos, publicaciones de canales, y cuándo suman o sacan al bot. |

**Sin historial y sin lista de chats.** Telegram no deja leer los mensajes pasados ni dice en qué chats
está el bot: todo llega por avisos. Ver
[mensajes sin historial](comentarios-y-mensajes.md#redes-sin-historial-whatsapp-y-telegram).

## Crear la app

No hay app que registrar: se crea un **bot**.

1. En Telegram, escribirle a [@BotFather](https://t.me/BotFather) y mandar `/newbot`.
2. Elegir el nombre y el usuario del bot (tiene que terminar en `bot`).
3. @BotFather responde con el **token** del bot: es lo que se carga al conectar.
4. Para publicar en un canal, sumar el bot como administrador con permiso para publicar; en un grupo,
   como miembro.

Documentación oficial: [Bot API](https://core.telegram.org/bots/api) (verificado 2026-11).

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.telegram import TelegramConfig, telegram_provider

telegram = telegram_provider(
    TelegramConfig(webhook_secret=os.environ["TELEGRAM_WEBHOOK_SECRET"]),  # largo y al azar
    RetryingTransport(HttpxTransport()),
)
```

`webhook_secret` solo hace falta para recibir avisos.

## Conectar

```python
import os

connected = await social.connect_with_credentials.execute(
    "telegram", owner="proyecto:42", credentials={"token": os.environ["TELEGRAM_BOT_TOKEN"]}
)
```

- **El token es lo que se guarda**, cifrado: no hay nada por lo que cambiarlo. No vence ni se renueva;
  deja de valer cuando alguien lo revoca en @BotFather.
- **El token va en la URL de cada pedido.** Por eso se valida su forma antes de usarlo, y los errores se
  arman solo con lo que respondió Telegram. Conviene que el transporte no registre las URLs
  ([Operar](operar.md#lo-que-nunca-sale)).

## Publicar

Un bot no publica "en su cuenta": publica en un chat donde lo sumaron.

```python
from omnisocial import Draft, Media, MediaKind
from omnisocial.telegram import TelegramOptions

draft = Draft(
    "Abrimos el sábado 🎉",
    media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/local.jpg"),),
    options=TelegramOptions("@micanal"),
)
result = await social.publish.execute(asset_id, draft)
```

- **El chat es `@nombredelcanal` o su id numérico.**
- **No hay cómo listar los chats.** El id se obtiene del aviso que llega cuando suman al bot (ver
  [Avisos](#avisos)), o lo escribe la persona.
- **Un medio, o un álbum de 2 a 10**, por URL o como archivo, con fotos y videos mezclados.
- **Al pie de un medio entran 1024 caracteres.** Si el texto es más largo, sale aparte, como respuesta a
  lo publicado. Si ese segundo mensaje falla, vuelve `PUBLISHED_WITH_ERROR`.
- **El id de la publicación lleva el chat y todos sus mensajes** (`@micanal:50,51,52`): con eso
  `delete_post` los borra. Telegram deja borrar hasta 48 horas después.
- **La dirección** solo se puede armar si el chat tiene nombre público.
- `TelegramOptions`: `parse_mode` (`HTML` o `MarkdownV2`), `silent`, `protect`, `disable_preview` y
  `thread_id` para un tema de un grupo.

## Conversar

```python
from omnisocial import OutboundMessage, Recipient

# `event` es el SocialEvent del mensaje que llegó; `bot_id`, el activo del bot.
to = Recipient(event.conversation_external_id)
await social.send_message.execute(bot_id, text="¡Hola!", to=to)
await social.send_message.execute(
    bot_id, message=OutboundMessage("Sí, abrimos", reply_to=event.object_external_id), to=to
)
```

- **No hay ventana de respuesta, pero un bot no empieza conversaciones**: solo le escribe a quien ya le
  escribió. Si la persona lo bloqueó, Telegram lo rechaza y la conexión sigue sana.
- Un adjunto por mensaje, por URL.

## Avisos

Telegram no firma los avisos: manda, en una cabecera, un secreto que se le dio al registrar la URL. Y el
aviso no dice de qué bot es. La librería resuelve las dos cosas al registrar:

```python
import os

from omnisocial import Token, TokenKind
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.telegram import TelegramConfig, telegram_webhooks

config = TelegramConfig(webhook_secret=os.environ["TELEGRAM_WEBHOOK_SECRET"])
webhooks = telegram_webhooks(config, RetryingTransport(HttpxTransport()))
token = Token(TokenKind.USER, os.environ["TELEGRAM_BOT_TOKEN"])  # el mismo que se cargó al conectar
url = await webhooks.register(token, "https://api.ejemplo.com/webhooks/telegram")
# Queda registrada https://api.ejemplo.com/webhooks/telegram?bot=7001234567
```

- **La URL de cada bot lleva su id**, y **su secreto sale de ese id** y del `webhook_secret`: el de un
  bot no sirve para hacerse pasar por otro.
- Hay que registrarla una vez por bot, después de conectarlo. Mientras haya una URL registrada, Telegram
  no entrega los avisos de otra forma.
- Se reciben con `webhook_routes`, como en [Avisos](webhooks.md).

| Llega | Evento |
|---|---|
| Un mensaje privado | `MESSAGE`, con quién escribió, el texto y los adjuntos. |
| Un mensaje en un grupo | `COMMENT`: es parte de una charla de varios. |
| Una publicación en un canal | `POST`. |
| Una edición | El mismo evento, con `UPDATED`. |
| Suman, sacan o bloquean al bot | `OTHER`; `text` dice cómo quedó (`administrator`, `member`, `left`, `kicked`). |

- **`conversation_external_id` es el chat.** Del aviso de "sumaron al bot" sale el id de un canal donde
  ya se puede publicar.
- **Los comentarios de una publicación de un canal** llegan como mensajes del grupo de discusión
  vinculado, si el bot está ahí. No hay cómo pedirlos.
- **Los adjuntos traen un id** (`Attachment.media_id`): el archivo se le pide a Telegram con `getFile`.
- Telegram guarda un aviso sin entregar hasta 24 horas.

## Límites

| Qué | Límite |
|---|---|
| Mensajes | Unos 30 por segundo en total, uno por segundo en un mismo chat y 20 por minuto en un grupo |
| Álbum | De 2 a 10 medios |
| Texto al pie de un medio | 1.024 caracteres |
| Por URL | Fotos de hasta 5 MB, otros archivos de hasta 20 MB |
| Como archivo | Fotos de hasta 10 MB, otros archivos de hasta 50 MB (la librería valida estos topes) |

Si se pasa del ritmo, vuelve `Refused(RATE_LIMITED)` con los segundos a esperar. Para repartirlo entre
procesos, `rate_limits=` ([Operar](operar.md#limites-de-uso-entre-varios-procesos)).

## Errores

Telegram no tiene códigos propios: usa el estado HTTP y explica en el texto.

| Estado | Resultado |
|---|---|
| 401 | El token del bot no vale (lo revocaron en @BotFather): la conexión queda inválida |
| 403 | El bot no puede escribir ahí (lo bloquearon, no es miembro, no es administrador). No es un permiso que falte: `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |
| 429 | `Refused(RATE_LIMITED)`, con los segundos a esperar |
| 400 | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |

## Lo que conviene saber

- **Un bot no ve los mensajes de un grupo** salvo que lo mencionen, si tiene activado el modo privado
  (viene así por defecto). Se cambia en @BotFather con `/setprivacy`.

!!! warning "A confirmar con la API real"
    - El significado de cada estado de error: Telegram no los documenta.
    - La forma de la dirección de una publicación en un canal sin nombre público, que por eso no se arma.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
