# Capacidades de una red

Referencia para quien escribe un adaptador: los puertos, lo que el núcleo espera de cada uno y cómo se
declara lo que la red acepta. El paso a paso para empezar está en [Sumar una red](nueva-red.md).

## Los puertos

Cada capacidad es un [puerto](referencia/glosario.md) (`Protocol`) de `omnisocial.application.ports`,
también exportado en `omnisocial.network`. La lista vigente está en ese archivo; por qué son puertos
separados, en el [ADR 0002](adr/0002-capacidades-por-red.md).

| Puerto | Campo de `Provider` | Para qué |
|---|---|---|
| `OAuthClient` | `oauth` | URL de autorización, canje del código, identidad, renovación y revocación |
| `ServerOAuth` | `server_oauth` | El OAuth de una red federada: cada servidor es una app distinta |
| `CredentialLogin` | `credentials` | Conectar con una credencial (contraseña de aplicación, token de bot) |
| `IdentityReader` | `identity` | Quién es el dueño de un token, cuando no lo resuelve el `OAuthClient` |
| `AssetDirectory` | `assets` | Qué activos administra un token |
| `ContentReader` | `content` | Publicaciones de un activo en una ventana |
| `CommentGateway` | `comments` | Leer, responder, ocultar, borrar y dar like a comentarios |
| `MessagingGateway` | `messaging` | Conversaciones, mensajes, enviar y la ventana para responder |
| `InsightsReader` | `insights` | Métricas por nombre propio, con su catálogo de nombres comunes |
| `Publisher` | `publisher` | Publicar un borrador, retomar una publicación en etapas y borrarla |
| `LookupReader` | `lookups` | Las consultas auxiliares para publicar (tableros, comunidades) |
| `ProfileLookup` | `profiles` | Perfiles públicos de cuentas ajenas |
| `WebhookParser` | `webhooks` | Saludo de suscripción, esquema de firma y traducción de los avisos |

`OAuthClient`, `ServerOAuth` y `CredentialLogin` comparten `TokenRefresher`: renovar y revocar. Una red
trae uno de los tres.

Cada adaptador **hereda del puerto** y marca sus métodos con `@override`. Mypy lo exige
(`explicit-override`), y así un cambio en el puerto se detecta en la definición de la clase
([ADR 0004](adr/0004-reglas-estaticas-de-diseno.md)):

```python
from typing_extensions import override

from omnisocial.network import ContentReader


class TikTokVideos(ContentReader):
    @override
    async def list_posts(self, asset, token, *, window, limit): ...
```

Ruff no deja leer el reloj, generar ids o leer variables de entorno fuera de los adaptadores de sistema:
si la red necesita la hora, recibe un `Clock`.

## Lo que el núcleo espera

- `exchange_code` devuelve el mejor token que la red permita (el de mayor duración).
- `can_refresh` dice la verdad: si la red no renueva, devuelve `False` y la conexión vence sola. Si solo
  renueva en ciertas condiciones (un token vigente y emitido hace más de un día, por ejemplo), las
  comprueba ahí, con el `Clock` ([ADR 0010](adr/0010-salud-de-las-conexiones.md)).
- `WebhookParser.verifier` es un esquema de [omniwebhook](https://pypi.org/project/omniwebhook/)
  (`hmac_body_scheme`, `stripe_scheme`…), no una verificación propia
  ([ADR 0003](adr/0003-webhooks-con-omniwebhook.md)).
- Los tipos de activo son texto libre, propio de la red (`tiktok_account`), y cada uno declara en la
  descripción qué capacidades habilita.
- Se guarda el id estable de las cuentas, no el nombre de usuario.
- Una red no suma dependencias obligatorias ni importa a otra red
  ([ADR 0006](adr/0006-cada-red-paga-lo-suyo.md)).

## Otras formas de conectar

Si la red no conecta con el diálogo de siempre, trae otra cosa en lugar de `oauth`
([ADR 0011](adr/0011-redes-federadas-y-credenciales.md)):

- **`server_oauth`** (un `ServerOAuth`) si es federada: la persona elige el servidor, que llega ya
  validado, y el token vuelve con `server` anotado. Los demás adaptadores le hablan a `token.server`.
- **`credentials`** (un `CredentialLogin`) si se conecta con una credencial: declara qué datos pedir
  (`fields`) y cuáles son secretos, y cambia la credencial por un token.

En los dos casos la identidad la lee un `IdentityReader` aparte, y renovar y revocar se implementan ahí.
El arnés dice el servidor de prueba (`server()`) o la credencial de prueba (`credentials()`), y el
contrato conecta como lo hace esa red.

## Publicar

Lo que cada tipo de activo acepta se declara en la descripción, y el núcleo valida el borrador antes de
llamar al adaptador ([ADR 0008](adr/0008-publicar.md)):

```python
SPEC = NetworkSpec(
    ...,
    publishing={
        TIKTOK_ACCOUNT: PublishLimits(
            max_text=2200,
            text_count=TextCount.UTF16,
            max_images=35,
            max_videos=1,
            media_required=True,
            options=TikTokOptions,
        )
    },
)
```

El `Publisher` recibe un borrador que ya entra y devuelve un `Outcome`:

| Estado | Cuándo |
|---|---|
| `PUBLISHED` | Salió en la llamada. Lleva el id y la URL |
| `PENDING` | La red publica en etapas. Lleva lo necesario para retomarla en `resume`, sin tokens (se guarda sin cifrar). `resume` tiene que poder llamarse dos veces sin publicar dos veces |
| `PUBLISHED_WITH_ERROR` | Salió y un paso posterior falló. Nunca una excepción después de haber publicado |
| `FAILED` | La red la rechazó mientras la procesaba |

- **Un error antes de publicar** se lanza con la tabla de errores, como en cualquier capacidad. Lo que la
  red rechaza por el contenido va como `INVALID_REQUEST`: vuelve `Refused(CONTENT_REJECTED)`.
- **Hilos**: `PublishLimits.max_thread` dice cuántas partes después de la primera. Cada parte se crea como
  respuesta a la anterior; si una falla después de la primera, `PUBLISHED_WITH_ERROR` con el id del primer
  post.
- **Archivos** (`media_by_file=True`): el adaptador los lee por partes con `MediaFile.read` y los manda con
  `content=` en el transporte. Si abandona la subida antes de que la red cree algo, lanza `NotPublished`;
  si no puede afirmarlo, un `ProviderError` común, y la publicación queda en duda
  ([ADR 0009](adr/0009-cuota-y-subida-por-partes.md)).
- `PublishLimits.video_by_url=False` si la red toma las imágenes de una URL pero pide el video como
  archivo.
- **Cuota diaria de la app**: el cliente la cuenta con un `QuotaBudget` antes de cada llamada y lanza
  `QuotaExhausted` cuando no entra. Ver `adapters/providers/youtube/client.py`.
- El pedido que publica no lleva `retry_safe`: el transporte no lo repite solo.
- Las opciones propias de la red son un `PublishOptions` que se declara en `PublishLimits.options`. Validan
  lo suyo al construirse (`__post_init__`): un destino vacío no llega al adaptador. El arnés las da en
  `options(kind)` si la red no publica sin ellas.

### Consultas auxiliares

Si hay que elegir a dónde va la publicación (un tablero, una comunidad), las opciones son obligatorias y la
red ofrece consultas ([ADR 0012](adr/0012-consultas-auxiliares-y-ritmo.md)):

```python
BOARDS = LookupSpec("boards", "Los tableros de la cuenta.")
SECTIONS = LookupSpec("board_sections", "Las secciones de un tablero.", parent="boards")

SPEC = NetworkSpec(
    ...,
    publishing={ACCOUNT: PublishLimits(..., options=PinOptions, options_required=True)},
    lookups={ACCOUNT: (BOARDS, SECTIONS)},
)
```

El `LookupReader` va en `Provider.lookups` y devuelve `Choice`: el `id` es lo que después va en las
opciones. Recibe solo consultas declaradas, y `parent` ya viene si la consulta depende de otra. El arnés
deja sus respuestas en `script_lookups()`.

## El ritmo

Si la red pide pocos pedidos a la vez o espaciados, se declara en `NetworkSpec.pace` (`Pace`) y la fábrica
envuelve el transporte con `paced(transport, pace)`. Conviene que `pace` sea un parámetro de la fábrica,
para que quien despliega lo ajuste y las pruebas lo saquen. Para repartirlo entre procesos, la fábrica
acepta `rate_limits` ([ADR 0014](adr/0014-operar-en-produccion.md)).

## Mensajes

El `MessagingGateway` declara lo que acepta con `limits_for(asset)` (`MessagingLimits`): el largo del
texto, cuántos adjuntos, si tiene plantillas y si deja leer las conversaciones. `send` recibe un
`OutboundMessage` que ya entra en esos límites
([ADR 0013](adr/0013-mensajes-sin-historial-y-bandeja.md)).

- **Si la red no deja leer las conversaciones**, `history=False`: el núcleo no llama a
  `list_conversations` ni a `list_messages`, y quien manda dice a quién. Los mensajes entran por el
  `WebhookParser`.
- **Un evento de mensaje** lleva `conversation_external_id` (lo que hay que guardar para responder),
  `actor_name`, `attachments` y, si es sobre algo enviado, `status`.
- **Si el aviso no dice de qué cuenta es**, el adaptador pone el id en la URL al registrarla y lo lee de
  `query` en `parse`. El secreto tiene que quedar atado a ese id, para que el de una cuenta no sirva para
  otra.

Si una capacidad se atiende con una credencial de la app y no con el token de la conexión (el token de un
bot), un rechazo de esa credencial no se lanza como `TokenRejected`: no es la conexión la que murió. El
arnés lo declara en `app_token_capabilities()`.

## Perfiles públicos de otra fuente

`ProfileLookup` sirve también para una fuente que no es la API oficial de una red (un servicio propio, por
ejemplo). Se implementa en un paquete aparte y se registra como cualquier red
([ADR 0005](adr/0005-perfiles-publicos-y-mirador.md)):

```python
from typing_extensions import override

from omnisocial import Asset, Handle, Network, Provider, ProviderId, PublicProfile, Token
from omnisocial.network import ProfileLookup


class MiFuente(ProfileLookup):
    def __init__(self, cliente: MiCliente) -> None:
        self._cliente = cliente

    @property
    @override
    def networks(self) -> frozenset[Network]:
        return frozenset({Network.INSTAGRAM})

    @override
    def viewer_kinds(self, network: Network) -> frozenset[str]:
        return frozenset()  # no necesita cuenta propia

    @override
    async def lookup(
        self, handle: Handle, *, viewer: Asset | None, token: Token | None
    ) -> PublicProfile | None:
        datos = await self._cliente.perfil(handle.value)
        return PublicProfile(
            Network.INSTAGRAM, datos["id"], username=handle.value, followers=datos["seguidores"]
        )


Provider(id=ProviderId("mi-fuente"), profiles=MiFuente(cliente))
```

## Secretos en lo observado

El contrato comprueba que nada de lo que se observa de la red lleve un secreto. Si la red manda una clave
en la ruta de la URL, no hace falta nada: los tramos que no son un nombre se enmascaran
([Operar en producción](operar.md#lo-que-nunca-sale)).
