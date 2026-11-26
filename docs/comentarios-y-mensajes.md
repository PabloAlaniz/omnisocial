# Comentarios, mensajes y bandeja

Los ejemplos suponen un `social` armado como en [Instalar y armar](instalar-y-armar.md) y un `asset_id`
sacado de [`list_assets`](conectar.md#usar-los-activos). Todas las operaciones devuelven `Done` o
[`Refused`](referencia/negativas.md).

## Publicaciones y comentarios

```python
from datetime import datetime, timedelta, timezone

from omnisocial import Done, TimeWindow

until = datetime.now(timezone.utc)
posts = await social.list_posts.execute(
    asset_id, window=TimeWindow(until - timedelta(days=7), until), limit=50
)
if isinstance(posts, Done):
    for post in posts.value:
        comments = await social.list_comments.execute(asset_id, object_id=post.external_id)
```

Para moderar:

```python
await social.reply_to_comment.execute(asset_id, comment_id=comment_id, text="¡Gracias!")
await social.set_comment_hidden.execute(asset_id, comment_id=comment_id, hidden=True)
await social.delete_comment.execute(asset_id, comment_id=comment_id)
await social.like_comment.execute(asset_id, comment_id=comment_id)
```

Si la red no ofrece la acción para ese activo, vuelve `Refused(ACTION_NOT_OFFERED)` (en Instagram no se
puede dar like a un comentario, por ejemplo).

Las URLs de imágenes que devuelven las redes suelen ser de un CDN firmado y vencen. Si hace falta
mostrarlas después, conviene copiarlas en el momento.

## Mensajes privados

En las redes que guardan el historial (Meta), las conversaciones se leen y se responden por su id:

```python
conversations = await social.list_conversations.execute(asset_id)
if isinstance(conversations, Done):
    conversation = conversations.value[0]
    messages = await social.list_messages.execute(asset_id, conversation_id=conversation.external_id)
    sent = await social.send_message.execute(asset_id, conversation_id=conversation.external_id, text="Hola")
```

Muchas redes solo dejan responder durante un tiempo después del último mensaje de la persona (24 horas
en Meta y WhatsApp). Pasado ese tiempo vuelve `Refused(OUTSIDE_REPLY_WINDOW)`.

### Redes sin historial: WhatsApp y Telegram

WhatsApp y Telegram no dejan leer las conversaciones: los mensajes llegan por [avisos](webhooks.md), y
para responder hay que decir a quién. La app lo sabe porque guardó el aviso:

```python
from omnisocial import Media, MediaKind, OutboundMessage, Recipient, TemplateRef

# `event` es el SocialEvent del mensaje que llegó.
to = Recipient(event.conversation_external_id, last_inbound_at=event.occurred_at)

await social.send_message.execute(asset_id, text="¡Hola!", to=to)

imagen = Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/foto.jpg")
await social.send_message.execute(asset_id, message=OutboundMessage("Mirá", attachments=(imagen,)), to=to)

# Fuera de la ventana de 24 horas, WhatsApp solo deja mandar una plantilla aprobada.
plantilla = OutboundMessage(template=TemplateRef("recordatorio", "es_AR"))
await social.send_message.execute(asset_id, message=plantilla, to=to)
```

Un mensaje que no entra en lo que acepta la red vuelve `Refused(INVALID_MESSAGE)` sin llamarla. Sin `to`
en una red que lo necesita, `Refused(NO_RECIPIENT)`.

## La bandeja

Comentarios, mensajes y reseñas de cualquier red, con la misma forma:

```python
from datetime import datetime, timedelta, timezone

from omnisocial import Done

inbox = await social.read_inbox.execute(asset_id, since=datetime.now(timezone.utc) - timedelta(days=1))
if isinstance(inbox, Done):
    for item in inbox.value.items:  # de lo más nuevo a lo más viejo
        item.kind, item.author_name, item.text, item.rating, item.thread_external_id
    for skipped in inbox.value.skipped:
        ...  # lo que no se pudo leer (un permiso que falta); lo demás igual vino
```

`read_inbox` sirve para ponerse al día: hace una llamada por publicación y otra por conversación. Lo que
llega después conviene recibirlo por avisos, que se convierten a la misma forma:

```python
from omnisocial import inbox_item_from_event

item = inbox_item_from_event(event)  # None si el aviso no es algo que alguien escribió
```

La librería no guarda la bandeja ni sabe qué se respondió: eso es de la app.
