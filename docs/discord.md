# Discord: por bot o por webhook, y lo que conviene saber

Hay dos formas de publicar en un canal de Discord, y son dos redes distintas para la librería:

| | `discord` | `discord_webhook` |
|---|---|---|
| Qué hace falta | Una app de Discord con su bot. | Nada: la URL de un webhook del canal. |
| Cómo se conecta | La persona autoriza y suma el bot a un servidor. | Pega la URL. |
| El activo | El servidor (`discord_guild`). | El webhook (`discord_webhook`), que es de un canal. |
| Dónde publica | En cualquier canal que el bot vea. | En ese canal. |
| Con qué nombre | El del bot. | El del webhook, o el que se indique en cada publicación. |

Las dos publican y borran lo que publicaron. **Ninguna recibe mensajes**: Discord solo entrega los
mensajes de los canales por una conexión permanente, que esta librería no mantiene.

## Con el bot de la app

```python
from omnisocial.discord import DiscordConfig, discord_provider
from omnisocial.httpx import HttpxTransport, RetryingTransport

discord = discord_provider(
    DiscordConfig(
        client_id="...",
        client_secret="...",
        bot_token="...",
        app_url="https://miproducto.ejemplo.com",
    ),
    RetryingTransport(HttpxTransport()),
)
```

- **Al autorizar, la persona suma el bot a un servidor que administra**, con los permisos de
  `DiscordConfig.permissions` (por defecto ver canales, escribir, mostrar links y adjuntar archivos).
- **Los activos son los servidores que administra y donde está el bot.** Si administra uno pero no sumó
  el bot, no aparece.
- **Publica el bot, con su propio token.** El de la persona solo dice qué servidores administra. Si
  Discord rechaza el token del bot, es un problema de la configuración de la app: no invalida la
  conexión de nadie.
- **`app_url` va en el `User-Agent`** de todos los pedidos, que Discord exige.

```python
from omnisocial import Draft
from omnisocial.discord import DiscordOptions

channels = await social.list_choices.execute(guild.id, "channels")
# Done([Choice(id="500", name="#general", data={"type": "text"}), ...])

draft = Draft("Abrimos el sábado 🎉", options=DiscordOptions(channel_id="500"))
```

- **Sin `DiscordOptions` no se publica.** Los canales salen de la consulta `channels`, con su tipo:
  `text`, `announcement` o `forum`.
- **Un foro pide título**: `DiscordOptions("502", thread_name="Idea: horario extendido")`.
- **Un anuncio se puede repartir** a los servidores que siguen el canal con `crosspost=True`. Si eso
  falla, la publicación ya salió: `PUBLISHED_WITH_ERROR`.
- **Repetir el pedido no publica dos veces**: cada mensaje lleva una marca que Discord reconoce durante
  unos minutos. Por eso el transporte sí puede reintentarlo. Una publicación de foro no la lleva.

## Con un webhook de canal

```python
from omnisocial.discord_webhook import DiscordWebhookConfig, DiscordWebhookOptions, discord_webhook_provider

by_webhook = discord_webhook_provider(
    DiscordWebhookConfig(app_url="https://miproducto.ejemplo.com"), RetryingTransport(HttpxTransport())
)
connected = await social.connect_with_credentials.execute(
    "discord_webhook",
    owner=owner,
    credentials={"webhook_url": "https://discord.com/api/webhooks/111222333/…"},
)
```

- **La URL se crea en Discord**: Editar canal → Integraciones → Webhooks.
- **La URL es el secreto**: quien la tiene, publica. Se guarda cifrada, y solo su id y su clave.
- **Solo se acepta una URL de webhook de Discord.** De lo que pega la persona se toman el id y la clave;
  a dónde se hacen los pedidos lo decide la configuración.
- **Si borran el webhook**, la conexión queda inválida: no hay con qué publicar.
- **Desconectar no borra el webhook** del canal.
- `DiscordWebhookOptions`: `username` y `avatar_url` para que una publicación salga con otro nombre,
  `thread_id` para un hilo, `thread_name` para un foro.

## Lo que vale para las dos

- **Las menciones no avisan salvo que se pida.** Un `@everyone` en el texto no notifica a nadie si no se
  pone `mentions=True`. Importa cuando el texto viene de otra parte.
- **Una imagen por URL sale incrustada; un archivo, adjunto.** Un video va siempre como archivo: por URL
  Discord no lo muestra.
- **Hasta 2000 caracteres y 10 medios**, de hasta 20 MB cada uno. El pedido entero no pasa de 25 MB.
- `silent=True` publica sin notificación y `suppress_embeds=True` no muestra la vista previa de los links.
- **El id de una publicación** es `canal:mensaje` con el bot, y el del mensaje con un webhook.

## Lo que conviene saber

- **Al bot le puede faltar un permiso en un canal en particular**: vuelve `Refused(MISSING_PERMISSION)`.
  Se arregla en el servidor, o sumando el bot de nuevo.
- **Un canal en modo lento** vuelve `Refused(RATE_LIMITED)`, con los segundos a esperar.
- **Muchos pedidos rechazados seguidos bloquean a la app**: Discord corta por un rato a quien acumula
  10.000 respuestas 401, 403 o 429 en diez minutos. Conviene no reintentar una negativa.
- **Mensajes privados**: un bot puede escribirle a alguien con quien comparte un servidor, pero Discord
  desaconseja hacerlo en cantidad. No se ofrece.
- Sin verificar: la forma de la dirección de un mensaje (es la que usa la app de Discord, no está en su
  documentación), con qué estado HTTP llega cada código de error, y si el token de renovación anterior
  deja de valer al renovar. Nada se probó contra la API real.
