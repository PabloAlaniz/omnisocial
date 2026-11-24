# Mastodon y Pixelfed: una app por servidor y lo que conviene saber

Mastodon no es un servicio: es una red de miles de servidores independientes que se hablan entre sí.
Pixelfed (fotos) habla el mismo protocolo, y por eso comparte el adaptador. Para la librería son dos
redes, `mastodon` y `pixelfed`.

## Qué cubre

| Capacidad         | Mastodon | Pixelfed |
|-------------------|----------|----------|
| `login`           | Sí, en el servidor que elige la persona. | Igual. |
| `assets`          | La cuenta de quien autorizó (`mastodon_account`). | `pixelfed_account`. |
| `content`         | Las publicaciones propias, sin respuestas ni impulsos. | Igual. |
| `publishing`      | Una publicación o un hilo, con hasta 4 imágenes o un video. Borrar. | Hasta 4 fotos, siempre con medios. Borrar. |
| `comments`        | Leer las respuestas, responder y marcar como favorita. | Igual. |
| `insights`        | Contadores de la cuenta: seguidores, seguidos y publicaciones. | Igual. |
| `public_profiles` | Cualquier cuenta, preguntándole a su servidor. | No. |

**Sin mensajes, sin webhooks, sin ocultar ni borrar respuestas ajenas.** El protocolo no tiene avisos por
cuenta (sí un flujo en tiempo real, que no se integra), y no deja ocultar ni borrar lo que escribió otro.

## Armado

**No hay app que registrar de antemano.** La librería registra una en cada servidor la primera vez que
alguien de ese servidor conecta, y la guarda en `apps`.

```python
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.mastodon import CONNECT_SCOPES, PUBLISH_SCOPES, MastodonConfig, mastodon_provider
from omnisocial.pixelfed import PixelfedConfig, pixelfed_provider
from omnisocial.postgres import PostgresServerAppStore

apps = PostgresServerAppStore(pool, cipher)
transport = RetryingTransport(HttpxTransport())
mastodon = mastodon_provider(
    MastodonConfig(client_name="Mi Producto", connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES),
    transport,
    apps=apps,
)
pixelfed = pixelfed_provider(PixelfedConfig(client_name="Mi Producto"), transport, apps=apps)
```

`InMemoryServerAppStore` sirve para probar; en producción las apps tienen que sobrevivir a un reinicio,
porque los tokens ya emitidos dependen de ellas para renovarse y revocarse.

## Conectar

Hay que decir en qué servidor está la cuenta:

```python
started = await social.start_authorization.execute(
    "mastodon", purpose=Purpose.CONNECT, owner=owner, server="mastodon.social"
)
match started:
    case AuthorizationStarted(url=url):
        ...  # redirigir
    case Refused(reason=Refusal.SERVER_REQUIRED):
        ...  # faltó el servidor
    case Refused(reason=Refusal.INVALID_SERVER):
        ...  # no es un dominio público
```

- **El servidor se valida antes de hacerle un solo pedido.** Lo escribe la persona y la librería después
  le habla: se rechazan las direcciones IP, `localhost`, los nombres internos, los puertos y `http://`.
  **No cubre un dominio público que resuelve a una dirección interna**: eso se controla en la salida a la
  red de quien despliega (un proxy de salida o reglas de firewall).
- `normalize_server("https://Mastodon.Social/")` devuelve `mastodon.social`, y `parse_handle` entiende
  `@ana@mastodon.social`: de ahí se puede sacar el servidor sin preguntarlo aparte.
- **La identidad lleva el servidor** (`109@mastodon.social`): el id de una cuenta vale solo en el suyo, y
  la misma persona puede tener cuentas en varios.
- **El token recuerda de qué servidor es**, y se guarda cifrado con él.

## La app de cada servidor

- **Se registra con el máximo de permisos que se le va a pedir a alguien** (`MastodonConfig.app_scopes`).
  Si después se agrandan, las apps ya registradas no los tienen: hay que registrarlas de nuevo.
- **Queda atada a la URL de retorno.** Si cambia, la app de ese servidor se registra de nuevo sola.
- **`client_name` es lo que la persona ve** cuando autoriza: conviene que sea el nombre del producto.
- Un servidor puede no dejar registrar apps (un Pixelfed con OAuth apagado responde 404): el error se ve al
  empezar a autorizar.

## Permisos

| | Mastodon | Pixelfed |
|---|---|---|
| Entrar | `read:accounts` | `read` |
| Leer | `read:accounts`, `read:statuses` | `read` |
| Publicar (`PUBLISH_SCOPES`) | `write:statuses`, `write:media` | `write` |
| Marcar favoritas (`MODERATE_SCOPES`) | `write:favourites` | `write` |

Pixelfed no tiene permisos finos: `write` cubre todo lo que escribe.

## Tokens

- **Un token de Mastodon no vence ni se renueva.** Un 401 quiere decir que la persona quitó el acceso: la
  conexión queda inválida.
- **Uno de Pixelfed vence al año** (356 días) y trae token de renovación: se renueva solo.
- PKCE se manda a Mastodon (lo soporta desde la versión 4.3) y no a Pixelfed, donde no se pudo confirmar.

## Publicar

```python
from omnisocial import Draft, Media, MediaKind, PathFile
from omnisocial.mastodon import MastodonOptions

draft = Draft(
    "Abrimos el local nuevo 🎉",
    media=(Media(MediaKind.IMAGE, file=PathFile.open("local.jpg", "image/jpeg"), alt_text="El frente"),),
    thread=(Draft("Estamos en Av. Siempreviva 742."),),
    options=MastodonOptions(visibility="public", language="es"),
)
```

- **Los medios van como archivo**, al servidor de la cuenta. Una imagen queda lista enseguida; un video se
  procesa, y la publicación queda `PENDING` hasta que termina.
- **Cada publicación lleva una clave de idempotencia** que el servidor recuerda una hora: repetir el pedido
  no publica dos veces. La clave se guarda con el plan, así que retomar tampoco duplica. Por eso, a
  diferencia de otras redes, el transporte sí puede reintentar el pedido que publica.
- **Los límites son los que trae un servidor por defecto**: 500 caracteres, 4 imágenes de hasta 16 MB o un
  video. Cada servidor puede cambiarlos: si acepta menos, rechaza la publicación y vuelve
  `Refused(CONTENT_REJECTED)`; si acepta más, la librería no lo aprovecha.
- **El largo se cuenta por caracteres.** Mastodon cuenta cada link como 23 sin importar su largo, así que
  un texto con links largos puede rechazarse de más.
- **Pixelfed no acepta publicaciones sin medios**, ni videos por defecto, ni hilos.
- `MastodonOptions`: `visibility` (`public`, `unlisted`, `private`, `direct`), `sensitive`, `spoiler_text`
  (la advertencia de contenido), `language` y `reply_to`.
- **Un hilo es una cadena de respuestas.** Si se corta, lo anterior ya salió: `PUBLISHED_WITH_ERROR`.

## Lo que conviene saber

- **El texto de una publicación viene como HTML.** Se devuelve como texto, con los saltos de línea.
- **`list_comments` trae todas las respuestas de la conversación**, de cualquier nivel: cada una dice a
  cuál responde (`object_external_id`).
- **Los errores no tienen código**, solo un mensaje. El permiso faltante se reconoce por el texto ("outside
  the authorized scopes"); cualquier otro 403 es una excepción y la conexión sigue sana.
- **El límite de uso dice cuándo vuelve con una fecha** (`X-RateLimit-Reset`). Por defecto son 300 pedidos
  cada 5 minutos, y 30 subidas cada 30 minutos.
- **El perfil público de una cuenta se le pide a su servidor**, sin autorizar. Algunos servidores lo
  exigen: en ese caso la búsqueda falla.
- Nada de esto se probó contra un servidor real. En Pixelfed, además, lo que no es login y publicar sale
  de leer su código, no su documentación.
