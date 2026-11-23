# Sumar una red

Una red es un `Provider` con las capacidades que implementa. No hace falta implementar todas.

## 1. Las capacidades

Cada una es un `Protocol` de `omnisocial.application.ports`:

| Puerto | Para qué |
|--------|----------|
| `OAuthClient` | URL de autorización, canje del código, identidad, renovación y revocación. |
| `AssetDirectory` | Qué activos administra un token. |
| `ContentReader` | Publicaciones de un activo en una ventana. |
| `CommentGateway` | Leer, responder y ocultar comentarios. |
| `MessagingGateway` | Conversaciones, mensajes, enviar y la ventana para responder. |
| `InsightsReader` | Métricas por nombre propio, con su catálogo de nombres comunes. |
| `WebhookParser` | Saludo de suscripción, esquema de firma (omniwebhook) y traducción de los avisos. |

Cada adaptador **hereda del puerto** y marca sus métodos con `@override`. Mypy lo exige
(`explicit-override`) y así un cambio en el puerto se detecta en la definición de la clase:

```python
from typing_extensions import override

from omnisocial.application.ports import ContentReader


class TikTokVideos(ContentReader):
    @override
    async def list_posts(self, asset, token, *, window, limit): ...
```

Además, ruff no deja leer el reloj, generar ids o leer variables de entorno fuera de los adaptadores de
sistema: si la red necesita la hora, recibe un `Clock`. Ver [ADR 0004](adr/0004-reglas-estaticas-de-diseno.md).

Reglas que el núcleo espera:

- `exchange_code` devuelve el mejor token que la red permita (el de mayor duración).
- Si la red rechaza un token, se lanza `TokenRejected`: la conexión queda inválida y no se reintenta.
- Cualquier otro error de la red es `ProviderError`.
- `can_refresh` dice la verdad: si la red no renueva, devuelve `False` y la conexión vence sola.
- `WebhookParser.verifier` es un esquema de [omniwebhook](https://pypi.org/project/omniwebhook/)
  (`hmac_body_scheme`, `stripe_scheme`…), no una verificación propia. Sin secreto configurado, omniwebhook
  rechaza todo.
- Los tipos de activo son texto libre, propio de la red (`tiktok_account`, por ejemplo).

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

Una red no suma dependencias obligatorias ni la importa el paquete raíz (ADR 0006). Si necesita una
biblioteca, va en un extra con su nombre (`omnisocial[mi-red]`); si es pesada, en un paquete aparte por entry
point. `tests/architecture/test_peso.py` falla si `import omnisocial` empieza a cargar una red.

## 2. El proveedor

```python
from omnisocial import Provider, ProviderId


def tiktok_provider(config, transport) -> Provider:
    return Provider(
        id=ProviderId("tiktok"),
        oauth=TikTokOAuth(config, transport),
        assets=TikTokAccounts(transport),
        content=TikTokVideos(transport),
        insights=TikTokInsights(transport),
    )
```

## 3. Publicarla aparte (opcional)

Una red se puede distribuir como paquete propio y registrarse por entry point:

```toml
[project.entry-points."omnisocial.providers"]
tiktok = "omnisocial_tiktok:tiktok_provider"
```

```python
from omnisocial.application.registry import load_entry_point

factory = load_entry_point("tiktok")
```

## 4. Probarla

Los casos de uso no cambian. Lo que hay que probar es la traducción entre la red y el dominio, con
respuestas grabadas y sin red de verdad: ver `tests/adapters/meta/` y el transporte falso de
`tests/adapters/meta/conftest.py`. La prueba de que la red encaja es que pase el mismo flujo de punta a
punta que `tests/adapters/meta/test_end_to_end.py`.
