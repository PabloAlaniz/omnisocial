# Discord

Publicar en canales de Discord, con el bot de una app o con el webhook de un canal.

## Qué cubre

Hay dos formas de publicar en un canal de Discord, y son dos redes distintas para la librería:

| | `discord` | `discord_webhook` |
|---|---|---|
| Qué hace falta | Una app de Discord con su bot. | Nada: la URL de un webhook del canal. |
| Cómo se conecta | La persona autoriza y suma el bot a un servidor. | Pega la URL. |
| El activo | El servidor (`discord_guild`). | El webhook (`discord_webhook`), que es de un canal. |
| Dónde publica | En cualquier canal que el bot vea. | En ese canal. |
| Con qué nombre | El del bot. | El del webhook, o el que se indique en cada publicación. |

Las dos publican y borran lo que publicaron. **Ninguna recibe mensajes**: Discord solo entrega los
mensajes de los canales por una conexión permanente, que esta librería no mantiene. **Tampoco manda
mensajes privados**: un bot puede escribirle a alguien con quien comparte un servidor, pero Discord
desaconseja hacerlo en cantidad.

## Crear la app

Solo para `discord`; con un webhook no hace falta.

1. En el [portal de desarrolladores](https://discord.com/developers/applications), *New Application*.
2. En *OAuth2*, cargar la URL de retorno `https://api.ejemplo.com/oauth/discord/callback` y copiar el
   **client id** y el **client secret**.
3. En *Bot*, copiar el **token del bot**.

El webhook de un canal se crea en Discord, en *Editar canal → Integraciones → Webhooks*, y su URL es lo
que se carga al conectar.

Documentación oficial: [Discord API](https://discord.com/developers/docs/intro) (verificado 2026-11).

## Armado

### Con el bot

```python
import os

from omnisocial.discord import DiscordConfig, discord_provider
from omnisocial.httpx import HttpxTransport, RetryingTransport

discord = discord_provider(
    DiscordConfig(
        client_id=os.environ["DISCORD_CLIENT_ID"],
        client_secret=os.environ["DISCORD_CLIENT_SECRET"],
        bot_token=os.environ["DISCORD_BOT_TOKEN"],
        app_url="https://miproducto.ejemplo.com",
    ),
    RetryingTransport(HttpxTransport()),
)
```

### Con un webhook

```python
from omnisocial.discord_webhook import DiscordWebhookConfig, discord_webhook_provider
from omnisocial.httpx import HttpxTransport, RetryingTransport

discord_webhook = discord_webhook_provider(
    DiscordWebhookConfig(app_url="https://miproducto.ejemplo.com"), RetryingTransport(HttpxTransport())
)
```

**`app_url` va en el `User-Agent`** de todos los pedidos, que Discord exige. Para repartir el ritmo de
pedidos entre procesos, `rate_limits=` ([Operar](operar.md#limites-de-uso-entre-varios-procesos)).

## Conectar

**Con el bot**, con el diálogo de Discord ([Conectar cuentas](conectar.md#con-el-dialogo-de-la-red)):

- **Al autorizar, la persona suma el bot a un servidor que administra.**
- **Los activos son los servidores que administra y donde está el bot.** Si administra uno pero no sumó
  el bot, no aparece.

**Con un webhook**, con la URL como credencial:

```python
connected = await social.connect_with_credentials.execute(
    "discord_webhook",
    owner="proyecto:42",
    credentials={"webhook_url": "https://discord.com/api/webhooks/111222333/…"},
)
```

- **La URL es el secreto**: quien la tiene, publica. Se guarda cifrada, y solo su id y su clave.
- **Solo se acepta una URL de webhook de Discord.** De lo que pega la persona se toman el id y la clave;
  a dónde se hacen los pedidos lo decide la configuración.
- **Desconectar no borra el webhook** del canal.

## Permisos

| Qué | Valor | Para qué |
|---|---|---|
| `LOGIN_SCOPES` | `identify` | Saber quién es la persona |
| `CONNECT_SCOPES` | `identify`, `guilds`, `bot` | Qué servidores administra y sumar el bot al que elija |
| `DiscordConfig.permissions` | Ver canales, enviar mensajes, insertar links y adjuntar archivos | Lo que el bot pide al sumarse a un servidor |

## Tokens

- **Publica el bot, con su propio token.** El de la persona solo dice qué servidores administra. Si
  Discord rechaza el token del bot, es un problema de la configuración de la app: no invalida la
  conexión de nadie.
- El token de la persona se renueva solo, y el de renovación rota
  ([Mantener vivas las conexiones](conexiones.md)).
- Un webhook no tiene token: **si borran el webhook**, la conexión queda inválida, porque no hay con qué
  publicar.

## Publicar

```python
from omnisocial import Done, Draft
from omnisocial.discord import DiscordOptions

channels = await social.list_choices.execute(asset_id, "channels")
# Done([Choice(id="500", name="#general", data={"type": "text"}), ...])

draft = Draft("Abrimos el sábado 🎉", options=DiscordOptions(channel_id="500"))
result = await social.publish.execute(asset_id, draft)
```

- **Con el bot, sin `DiscordOptions` no se publica.** Los canales salen de la consulta `channels`, con su
  tipo: `text`, `announcement` o `forum`.
- **Un foro pide título**: `DiscordOptions("502", thread_name="Idea: horario extendido")`.
- **Un anuncio se puede repartir** a los servidores que siguen el canal con `crosspost=True`. Si eso
  falla, la publicación ya salió: `PUBLISHED_WITH_ERROR`.
- **Repetir el pedido no publica dos veces**: cada mensaje lleva una marca que Discord reconoce durante
  unos minutos. Por eso el transporte sí puede reintentarlo. Una publicación de foro no la lleva.
- **Con un webhook**, `DiscordWebhookOptions` (de `omnisocial.discord_webhook`): `username` y
  `avatar_url` para que una publicación salga con otro nombre, `thread_id` para un hilo, `thread_name`
  para un foro.
- **Las menciones no avisan salvo que se pida.** Un `@everyone` en el texto no notifica a nadie si no se
  pone `mentions=True`. Importa cuando el texto viene de otra parte.
- **Una imagen por URL sale incrustada; un archivo, adjunto.** Un video va siempre como archivo: por URL
  Discord no lo muestra.
- `silent=True` publica sin notificación y `suppress_embeds=True` no muestra la vista previa de los links.
- **El id de una publicación** es `canal:mensaje` con el bot, y el del mensaje con un webhook.

## Límites

| Qué | Límite |
|---|---|
| Texto | 2.000 caracteres |
| Medios | Hasta 10 por mensaje, de hasta 20 MB cada uno |
| Pedido entero | 25 MB |
| Canal en modo lento | `Refused(RATE_LIMITED)`, con los segundos a esperar |

**Muchos pedidos rechazados seguidos bloquean a la app**: Discord corta por un rato a quien acumula
10.000 respuestas 401, 403 o 429 en diez minutos. Conviene no reintentar una negativa.

## Errores

| Código | Resultado |
|---|---|
| 401 | La conexión queda inválida |
| 50001, 50013 | Al bot le falta acceso o un permiso en ese canal: `Refused(MISSING_PERMISSION)`. Se arregla en el servidor, o sumando el bot de nuevo |
| 20016, 20028, 20029 | Modo lento o límites de escritura: `Refused(RATE_LIMITED)` |
| 10015, 50027 (webhook) | Borraron el webhook, o su clave no vale: la conexión queda inválida |
| 10003, 10004, 10008, 50006, 50035, 40005, 40067, 240000, 400 | Pedido inválido (canal o mensaje que no existe, mensaje vacío, archivo muy grande…): `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |

## Lo que conviene saber

- Para un canal donde publica una sola cuenta, el webhook es lo más simple: no hay app, ni bot, ni
  permisos que pedir.

!!! warning "A confirmar con la API real"
    - **El tope por archivo.** Discord subió en agosto de 2026 el límite de las cuentas gratuitas de 10 a
      20 MB ([Discord](https://support.discord.com/hc/en-us/articles/25444343291031), verificado
      2026-11); falta confirmar que valga igual para bots y webhooks.
    - La forma de la dirección de un mensaje: es la que usa la app de Discord, no está en su
      documentación.
    - Con qué estado HTTP llega cada código de error.
    - Si el token de renovación anterior deja de valer al renovar.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
