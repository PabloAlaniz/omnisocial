# Sumar una red

Una red es un `Provider` con las capacidades que implementa y una descripción que dice cuáles son. No hace
falta implementar todas: una red de solo login es válida.

## 1. El esqueleto

```bash
uv run python scripts/nueva_red.py mired --nombre "Mi Red"
```

Crea el adaptador (`src/omnisocial/adapters/providers/mired/`), su módulo público (`omnisocial.mired`), la
prueba de contrato y la página de documentación. Es una red de solo login que ya pasa todo; lo que hay que
completar está marcado con `PENDIENTE`.

Todo lo que un adaptador necesita se importa de `omnisocial.network`: los puertos, la descripción, el
transporte y los errores.

## 2. La descripción (`spec.py`)

Lo que se puede decir con datos no se programa ([ADR 0007](adr/0007-descripcion-y-contrato-de-una-red.md)):

```python
ERRORS = ErrorTable(
    codes={
        "access_token_invalid": ErrorKind.TOKEN_DEAD,
        "scope_not_authorized": ErrorKind.MISSING_PERMISSION,
        "rate_limit_exceeded": ErrorKind.RATE_LIMITED,
    }
)

SPEC = NetworkSpec(
    id=TIKTOK,
    name="TikTok",
    capabilities=frozenset({Capability.LOGIN, Capability.ASSETS, Capability.CONTENT, Capability.INSIGHTS}),
    assets={TIKTOK_ACCOUNT: frozenset({Capability.CONTENT, Capability.INSIGHTS})},
    errors=ERRORS,
    oauth=OAuthSpec(authorize_url=..., token_url=..., scope_separator=",", pkce=False),
    docs="docs/tiktok.md",
)
```

**La tabla de errores** es lo que más cuida a quien usa la librería. El cliente de la red lanza
`ERRORS.error(...)` y el núcleo decide igual para todas:

| Clase (`ErrorKind`)  | Qué hace el núcleo                                                   |
|----------------------|----------------------------------------------------------------------|
| `TOKEN_DEAD`         | La conexión queda inválida. No se reintenta.                         |
| `MISSING_PERMISSION` | `Refused(MISSING_PERMISSION)`. La conexión sigue sana.               |
| `RATE_LIMITED`       | `Refused(RATE_LIMITED)`, con `retry_after` si la red lo dijo.        |
| `QUOTA_EXHAUSTED`    | `Refused(QUOTA_EXHAUSTED)`. El token no tiene la culpa.              |
| `INVALID_REQUEST`, `TRANSIENT`, `UNKNOWN` | `ProviderError`, con la clase en `error.kind`.  |

Solo es `TOKEN_DEAD` lo que la red documenta como "este token ya no sirve". Un 401 o un 403 sin código
conocido no lo es: invalidar una conexión sana obliga a la persona a reconectar sin motivo.

**El OAuth**, si es el estándar, se declara en `OAuthSpec` y lo atiende `StandardOAuth`: la red solo escribe
un `IdentityReader`. Lo que se puede declarar: el separador de permisos, si usa PKCE, el nombre de los
parámetros de la app, parámetros fijos de la URL de autorización y si el token de renovación rota. Si el
flujo es distinto de verdad (un canje extra, por ejemplo), la red trae su propio `OAuthClient`.

## 3. Las capacidades

Cada una es un `Protocol` de `omnisocial.application.ports` (también en `omnisocial.network`):

| Puerto | Para qué |
|--------|----------|
| `OAuthClient` | URL de autorización, canje del código, identidad, renovación y revocación. |
| `AssetDirectory` | Qué activos administra un token. |
| `ContentReader` | Publicaciones de un activo en una ventana. |
| `CommentGateway` | Leer, responder y ocultar comentarios. |
| `MessagingGateway` | Conversaciones, mensajes, enviar y la ventana para responder. |
| `InsightsReader` | Métricas por nombre propio, con su catálogo de nombres comunes. |
| `Publisher` | Publicar un borrador, retomar una publicación en etapas y borrarla. |
| `WebhookParser` | Saludo de suscripción, esquema de firma (omniwebhook) y traducción de los avisos. |
| `ProfileLookup` | Perfiles públicos de cuentas ajenas. |

Cada adaptador **hereda del puerto** y marca sus métodos con `@override`. Mypy lo exige
(`explicit-override`) y así un cambio en el puerto se detecta en la definición de la clase:

```python
from typing_extensions import override

from omnisocial.network import ContentReader


class TikTokVideos(ContentReader):
    @override
    async def list_posts(self, asset, token, *, window, limit): ...
```

Ruff no deja leer el reloj, generar ids o leer variables de entorno fuera de los adaptadores de sistema: si
la red necesita la hora, recibe un `Clock`. Ver [ADR 0004](adr/0004-reglas-estaticas-de-diseno.md).

Reglas que el núcleo espera:

- `exchange_code` devuelve el mejor token que la red permita (el de mayor duración).
- `can_refresh` dice la verdad: si la red no renueva, devuelve `False` y la conexión vence sola.
- `WebhookParser.verifier` es un esquema de [omniwebhook](https://pypi.org/project/omniwebhook/)
  (`hmac_body_scheme`, `stripe_scheme`…), no una verificación propia. Sin secreto configurado, omniwebhook
  rechaza todo.
- Los tipos de activo son texto libre, propio de la red (`tiktok_account`, por ejemplo), y cada uno
  declara en la descripción qué capacidades habilita.
- Se guarda el id estable de las cuentas, no el nombre de usuario.

Al sumar una capacidad: el componente va al `Provider`, la capacidad a `SPEC.capabilities` (y al tipo de
activo que la habilita). El contrato falla si una de las dos partes quedó atrás.

### Publicar

Lo que cada tipo de activo acepta se declara en la descripción, y el núcleo valida el borrador antes de
llamar al adaptador:

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

- `PUBLISHED`, con el id y la URL, si salió en la llamada.
- `PENDING`, con lo necesario para retomarla en `resume` (sin tokens: se guarda sin cifrar), si la red
  publica en etapas. `resume()` tiene que poder llamarse dos veces sin publicar dos veces.
- `PUBLISHED_WITH_ERROR` si salió y un paso posterior falló. Nunca una excepción después de haber
  publicado: el núcleo no sabría que salió, y repetir el pedido la duplicaría.
- `FAILED` si la red la rechazó mientras la procesaba.

Un error antes de publicar se lanza con la tabla de errores, como en cualquier capacidad. Lo que la red
rechaza por el contenido va como `INVALID_REQUEST`: vuelve `Refused(CONTENT_REJECTED)`.

Si la red tiene hilos, `PublishLimits.max_thread` dice cuántas partes después de la primera. El adaptador
crea cada parte como respuesta a la anterior; si una falla después de la primera, devuelve
`PUBLISHED_WITH_ERROR` con el id del primer post.

Si la red recibe archivos (`media_by_file=True`), el adaptador los lee por partes con `MediaFile.read` y
los manda con `content=` en el transporte. Cuando una subida se abandona antes de que la red haya creado
nada, lanza `NotPublished`: el núcleo devuelve `Refused(NOT_PUBLISHED)` y libera la clave. Si no puede
afirmarlo (se perdió la respuesta al último paso), lanza un `ProviderError` común y la publicación queda en
duda.

Si la red tiene una cuota diaria para toda la app, el cliente la cuenta con un `QuotaBudget` antes de cada
llamada y lanza `QuotaExhausted` cuando no entra. Ver `adapters/providers/youtube/client.py`.

El pedido que publica no lleva `retry_safe`: el transporte no lo repite solo. Las opciones propias de la
red son un `PublishOptions` que se declara en `PublishLimits.options`.

### Perfiles públicos de otra fuente

`ProfileLookup` sirve también para una fuente que no es la API oficial de una red (un servicio propio, por
ejemplo). Se implementa en un paquete aparte y se registra como cualquier red:

```python
class MiFuente(ProfileLookup):
    networks = frozenset({Network.INSTAGRAM})

    def viewer_kinds(self, network: Network) -> frozenset[str]:
        return frozenset()  # no necesita cuenta propia

    async def lookup(self, handle, *, viewer, token):
        datos = await self._cliente.perfil(handle.value)
        return PublicProfile(
            Network.INSTAGRAM, datos["id"], username=handle.value, followers=datos["seguidores"]
        )


Provider(id=ProviderId("mi-fuente"), profiles=MiFuente(cliente))
```

### Lo que una red no puede hacer

Una red no suma dependencias obligatorias, no importa a otra red y no la importa el paquete raíz
([ADR 0006](adr/0006-cada-red-paga-lo-suyo.md)). Si necesita una biblioteca, va en un extra con su nombre
(`omnisocial[mi-red]`); si es pesada, en un paquete aparte. Lo vigilan `tests/architecture/test_peso.py` y
los contratos de import-linter, que encuentran las redes solos.

## 4. Probarla

**El contrato común** (`tests/adapters/<red>/test_contract.py`) es lo primero que tiene que pasar. La red
arma un `NetworkHarness`: cómo se construye el proveedor, qué responde la red cuando alguien conecta una
cuenta y cómo dice cada clase de error.

```python
from omnisocial.testing import FakeTransport, NetworkHarness, ProviderContract


class TestTikTokCumpleElContrato(ProviderContract):
    def harness(self) -> NetworkHarness:
        return TikTokHarness()
```

Con eso se comprueba, pasando por los casos de uso, que:

- La descripción dice la verdad: las capacidades declaradas son las del proveedor, y los activos
  descubiertos son los declarados.
- Cada adaptador hereda de su puerto.
- La URL de autorización lleva el `state`, la URL de retorno, los permisos y PKCE si corresponde.
- Conectar guarda la conexión y sus activos, y los tokens no aparecen en `repr`.
- Cada clase de error se traduce igual en toda capacidad y en todo tipo de activo, y solo un token muerto
  invalida la conexión.
- Un borrador que no entra en un activo se rechaza sin llamar a la red, y los límites declarados dejan
  pasar al menos un borrador mínimo.
- Un aviso sin firma no llega a la app.

**Después, la traducción de cada capacidad**, con respuestas copiadas de la API real (sin tokens ni datos
personales) y `FakeTransport`. Ver `tests/adapters/tiktok/`. Ningún test llama a la red.

## 5. Documentarla

La página de la red (`docs/<red>.md`) tiene siempre las mismas secciones: qué cubre, armado, cómo crear la
app, permisos y revisión, límites y cuotas, errores y lo que conviene saber. La última es la que más vale:
lo que no está en la documentación oficial y costó descubrir.

Después, `uv run python scripts/matriz.py` suma la red a la matriz del README.

## 6. Publicarla aparte (opcional)

Una red se puede distribuir como paquete propio y registrarse por entry point:

```toml
[project.entry-points."omnisocial.providers"]
mired = "omnisocial_mired:mired_provider"
```

```python
from omnisocial.network import load_entry_point

factory = load_entry_point("mired")
```

El paquete externo usa lo mismo que las redes de este repositorio: importa de `omnisocial.network` y corre
el contrato de `omnisocial.testing`.
