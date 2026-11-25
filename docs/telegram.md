# Telegram: bots, canales y lo que conviene saber

## Qué cubre

| Capacidad     | Qué hace |
|---------------|----------|
| `credentials` | Un bot se conecta con el token que da @BotFather. |
| `assets`      | El bot (`telegram_bot`). |
| `publishing`  | Un texto, una foto, un video o un álbum en un canal o en un grupo. Borrar. |
| `messaging`   | Escribirle a quien le escribió al bot. |
| `webhooks`    | Mensajes privados, mensajes de grupos, publicaciones de canales, y cuándo suman o sacan al bot. |

**Sin historial y sin lista de chats.** Telegram no deja leer los mensajes pasados ni dice en qué chats
está el bot: todo llega por avisos.

## Armado

```python
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.telegram import TelegramConfig, telegram_provider

telegram = telegram_provider(
    TelegramConfig(webhook_secret="un secreto propio, largo y al azar"),
    RetryingTransport(HttpxTransport()),
)
```

No hay app que registrar. `webhook_secret` solo hace falta para recibir avisos.

## Conectar

```python
connected = await social.connect_with_credentials.execute(
    "telegram", owner=owner, credentials={"token": "7001234567:AAH..."}
)
```

- **El token es lo que se guarda**, cifrado: no hay nada por lo que cambiarlo. No vence ni se renueva;
  deja de valer cuando alguien lo revoca en @BotFather.
- **El token va en la URL de cada pedido.** Por eso se valida su forma antes de usarlo, y los errores se
  arman solo con lo que respondió Telegram. Conviene que el transporte no registre las URLs.

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
```

- **El chat es `@nombredelcanal` o su id numérico.** En un canal el bot tiene que ser administrador con
  permiso para publicar; en un grupo, miembro.
- **No hay cómo listar los chats.** El id se obtiene del aviso que llega cuando suman al bot (ver
  abajo), o lo escribe la persona.
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

to = Recipient(event.conversation_external_id)
await social.send_message.execute(bot.id, text="¡Hola!", to=to)
await social.send_message.execute(
    bot.id, message=OutboundMessage("Sí, abrimos", reply_to=event.object_external_id), to=to
)
```

- **No hay ventana de respuesta, pero un bot no empieza conversaciones**: solo le escribe a quien ya le
  escribió. Si la persona lo bloqueó, Telegram lo rechaza y la conexión sigue sana.
- Un adjunto por mensaje, por URL.

## Avisos

Telegram no firma los avisos: manda, en una cabecera, un secreto que se le dio al registrar la URL. Y el
aviso no dice de qué bot es. La librería resuelve las dos cosas al registrar:

```python
from omnisocial.telegram import telegram_webhooks

webhooks = telegram_webhooks(config, transport)
await webhooks.register(token, "https://api.ejemplo.com/webhooks/telegram")
# Queda registrada https://api.ejemplo.com/webhooks/telegram?bot=7001234567
```

- **La URL de cada bot lleva su id**, y **su secreto sale de ese id** y del `webhook_secret`: el de un
  bot no sirve para hacerse pasar por otro.
- Hay que registrarla una vez por bot. Mientras haya una URL registrada, Telegram no entrega los avisos
  de otra forma.

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

## Lo que conviene saber

- **El ritmo**: unos 30 mensajes por segundo en total, uno por segundo en un mismo chat y 20 por minuto
  en un grupo. Si se pasa, vuelve `Refused(RATE_LIMITED)` con los segundos a esperar.
- **Los errores no tienen código**: un número de estado y un texto. Un 403 (bloqueado, no es miembro, no
  es administrador) se toma como un rechazo del contenido, no como un permiso que falta.
- **Por URL, Telegram acepta fotos de hasta 5 MB y otros archivos de hasta 20 MB**; como archivo, 10 y
  50. La librería valida los topes de archivo.
- Sin verificar: el significado de cada estado de error (Telegram no los documenta) y la forma de la
  dirección de una publicación en un canal sin nombre público, que por eso no se arma. Nada se probó
  contra la API real.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
