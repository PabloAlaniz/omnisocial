# Instalar y armar

## Instalar

Python 3.11 a 3.14.

```bash
pip install "omnisocial[httpx,postgres,crypto,starlette]"
```

| Extra       | Para qué                                                     |
|-------------|--------------------------------------------------------------|
| `httpx`     | El transporte HTTP de las redes.                             |
| `postgres`  | Guardar conexiones, activos y publicaciones en PostgreSQL.   |
| `crypto`    | Cifrar los tokens con AES-256-GCM antes de guardarlos.       |
| `starlette` | Las rutas del callback de OAuth y de los avisos (sirven en FastAPI). |
| `otel`      | Métricas y trazas con OpenTelemetry ([Operar](operar.md)).   |

Cada red vive en su módulo (`omnisocial.meta`, `omnisocial.tiktok`, `omnisocial.bluesky`…) y se carga
recién cuando se importa: quien usa una sola red no ejecuta el código de las otras, y ninguna suma
dependencias obligatorias.

## Armar `Omnisocial`

`Omnisocial.build` junta las redes con los almacenes. Se arma una vez, al arrancar la app, y se comparte.

```python
import os

from omniwebhook.postgres import AsyncPostgresIdempotencyStore, AsyncPsycopgClient
from psycopg_pool import AsyncConnectionPool

from omnisocial import Omnisocial, ReturnUrlPolicy, SystemClock
from omnisocial.crypto import AesGcmTokenCipher
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.meta import MetaConfig, meta_provider
from omnisocial.postgres import (
    PostgresAssetRepository,
    PostgresAuthorizationStateStore,
    PostgresConnectionRepository,
    PostgresPublicationRepository,
    create_schema,
)


async def build_social() -> Omnisocial:
    pool = AsyncConnectionPool(os.environ["DATABASE_URL"], open=False)
    await pool.open()
    await create_schema(pool)  # crea las tablas que falten; se puede correr en cada arranque

    cipher = AesGcmTokenCipher({"k1": os.environ["OMNISOCIAL_KEY_K1"]}, active="k1")

    return Omnisocial.build(
        providers=[
            meta_provider(
                MetaConfig(
                    api_version="v24.0",
                    app_id=os.environ["META_APP_ID"],
                    app_secret=os.environ["META_APP_SECRET"],
                    webhook_verify_token=os.environ["META_WEBHOOK_VERIFY_TOKEN"],
                ),
                RetryingTransport(HttpxTransport()),
            ),
        ],
        connections=PostgresConnectionRepository(pool, cipher),
        assets=PostgresAssetRepository(pool, cipher),
        states=PostgresAuthorizationStateStore(pool, cipher, SystemClock()),
        webhook_events=AsyncPostgresIdempotencyStore(AsyncPsycopgClient(pool.connection)),
        publications=PostgresPublicationRepository(pool),
        redirect_uri_for=lambda provider: f"https://api.ejemplo.com/oauth/{provider}/callback",
        return_urls=ReturnUrlPolicy.of("https://app.ejemplo.com"),
    )
```

| Argumento | Qué es |
|---|---|
| `providers` | Las redes, cada una con su configuración y su transporte. La página de cada red muestra cómo se arma. |
| `connections`, `assets` | Dónde se guardan las conexiones y los activos. Los tokens se guardan cifrados. |
| `states` | El `state` de cada autorización en curso: sirve una sola vez y vence. |
| `webhook_events` | Las reservas de [omniwebhook](https://pypi.org/project/omniwebhook/), para no procesar dos veces un aviso. |
| `publications` | Las publicaciones en curso y las claves de idempotencia. Opcional: si falta, quedan en memoria. |
| `redirect_uri_for` | La URL del callback de OAuth de cada red. Tiene que coincidir con la cargada en la app de la red. |
| `return_urls` | A qué orígenes se puede volver después de autorizar. Cualquier otro se rechaza. |
| `on_connection_change` | Opcional. Se llama cuando una conexión deja de servir o vuelve a servir ([Conexiones](conexiones.md)). |
| `observer` | Opcional. Recibe cada llamada a una red ([Operar](operar.md)). |

### La clave de cifrado

Se genera una vez y va al gestor de secretos:

```python
from omnisocial.crypto import generate_key

print(generate_key())
```

Para rotarla se agrega una clave nueva y se la marca activa. Lo nuevo se cifra con ella, y las anteriores
siguen descifrando lo que ya estaba guardado:

```python
import os

from omnisocial.crypto import AesGcmTokenCipher

cipher = AesGcmTokenCipher(
    {"k1": os.environ["OMNISOCIAL_KEY_K1"], "k2": os.environ["OMNISOCIAL_KEY_K2"]},
    active="k2",
)
```

### Las tablas

`create_schema(pool)` crea las tablas de omnisocial y la de reservas de omniwebhook si no existen. Algunas
redes usan almacenes propios, que se pasan al armar esa red y también crea `create_schema`:

| Almacén | Para qué | Redes |
|---|---|---|
| `PostgresServerAppStore(pool, cipher)` | La app registrada en cada servidor | Mastodon, Pixelfed |
| `PostgresQuotaLedger(pool)` | La cuota diaria, compartida entre procesos | YouTube |
| `PostgresRateLimitStore(pool)` | El ritmo de pedidos, compartido entre procesos | Pinterest, Reddit, Google Business Profile, Telegram, Discord |

## Sin base de datos

Para probar, todo tiene su versión en memoria. Sirve en un solo proceso y se pierde al reiniciar:

```python
from omniwebhook import AsyncMemoryIdempotencyStore

from omnisocial import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
    SystemClock,
)

stores = dict(
    connections=InMemoryConnectionRepository(),
    assets=InMemoryAssetRepository(),
    states=InMemoryAuthorizationStateStore(SystemClock()),
    webhook_events=AsyncMemoryIdempotencyStore(),
)
```

También existen `InMemoryServerAppStore`, `InMemoryQuotaLedger` e `InMemoryRateLimitStore`.

## Las rutas web

Con Starlette o FastAPI, la librería trae las rutas del callback de OAuth y de los avisos:

```python
from omnisocial.starlette import oauth_routes, webhook_routes

app.router.routes.extend(oauth_routes(social, on_logged_in=crear_sesion))  # GET /oauth/{provider}/callback
app.router.routes.extend(webhook_routes(social, on_events=encolar))  # GET y POST /webhooks/{provider}
```

`crear_sesion` se explica en [Login con una red](login.md) y `encolar`, en [Avisos](webhooks.md). Si la
app no usa login con una red, `on_logged_in` se omite.
