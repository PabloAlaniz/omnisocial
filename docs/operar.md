# Operar en producción

Cómo observar lo que la librería hace con cada red, repartir los límites de uso entre varios procesos y
seguir las versiones de API.

## Observar

Hay dos lugares donde mirar, y se pueden usar los dos.

**Cada llamada a una red.** Qué red, qué operación, cómo salió y cuánto tardó:

```python
from omnisocial import Observation, Omnisocial


class Contar:
    def operation(self, observation: Observation) -> None:
        metricas.sumar(
            observation.provider,  # "meta"
            observation.port,  # "publisher"
            observation.operation,  # "publish"
            str(observation.result),  # "ok" o "error"
            observation.error,  # "rate_limited", "token_dead", "transient"… o None
            observation.duration,  # segundos
        )


social = Omnisocial.build(..., observer=Contar())
```

**Cada pedido HTTP.** Envolviendo el transporte de una red:

```python
from omnisocial.httpx import HttpxTransport, ObservedTransport, RetryingTransport

transport = RetryingTransport(ObservedTransport(HttpxTransport(), observer, network="meta"))
```

`ObservedTransport` por dentro de los reintentos ve cada intento; por fuera, uno por operación.

### Con OpenTelemetry

```bash
pip install "omnisocial[otel]"
```

```python
from omnisocial.otel import OtelObserver

observer = OtelObserver()  # usa los proveedores globales de OpenTelemetry
social = Omnisocial.build(..., observer=observer)
transport = ObservedTransport(HttpxTransport(), observer, network="meta")
```

Deja dos métricas (`omnisocial.operation.duration` y `omnisocial.http.duration`, en segundos) y un tramo
por llamada y por pedido. Los tramos se crean cuando la llamada ya terminó, con su comienzo y su fin: no
son padres de los que cree el cliente HTTP por su cuenta.

### Lo que nunca sale

- **Un token, un secreto o una cabecera de autorización.** Una observación lleva nombres, no datos.
- **El mensaje de un error.** Puede traer datos de la cuenta: se informa la clase (`rate_limited`,
  `missing_permission`), no el texto.
- **Una ruta con ids o claves.** De un pedido se informa el servidor y la ruta con cada tramo que no es
  un nombre reemplazado por `:id`: `/v26.0/:id/messages`. Importa porque hay redes donde el secreto viaja
  en la ruta (el token de un bot de Telegram, la clave de un webhook de Discord). La query no se informa.

El contrato común lo comprueba en cada red: conecta una cuenta, usa cada capacidad y busca en todo lo
observado cualquier secreto que haya pasado por el transporte.

**Lo que esto no cubre es el registro del propio cliente HTTP.** Si `httpx` o un proxy registran las URLs
completas, el token de Telegram queda ahí: conviene dejar esos registros en un nivel que no las muestre.

Un observador que lanza una excepción no rompe nada: se ignora. Conviene que no tarde, porque se llama
en el camino de cada operación.

## Límites de uso entre varios procesos

Las redes que piden un ritmo (`Pace`) lo respetan solas dentro de un proceso. Con varios procesos, cada
uno respetaría el suyo y entre todos se pasarían. Para repartirlo hace falta un almacén compartido:

```python
from omnisocial.postgres import PostgresRateLimitStore
from omnisocial.reddit import RedditConfig, reddit_provider

limits = PostgresRateLimitStore(pool)
reddit = reddit_provider(RedditConfig(...), transport, rate_limits=limits)
```

- **Los turnos se reparten**: si la red pide 0,6 segundos entre pedidos, los pide entre los de todos los
  procesos.
- **Cuando la red pide esperar, esperan todos.** Un 429 con su tiempo de espera queda anotado, y el
  pedido que otro proceso haría antes de tiempo se responde ahí mismo con un 429, sin llamar a la red.
  Vuelve `Refused(RATE_LIMITED)` con lo que falta. Sirve sobre todo donde insistir se castiga.
- **Si falta poco (hasta 30 segundos), espera** en vez de negar.
- **El reloj es el de la base**: no importa que los procesos no tengan la hora igual.
- `create_schema` crea la tabla `omnisocial_rate_limits`. Cada pedido de una red con almacén hace una
  consulta a la base.
- **El tope de pedidos simultáneos sigue siendo de cada proceso.**
- `InMemoryRateLimitStore` sirve para probar, o para compartir los turnos entre varias instancias de una
  red dentro del mismo proceso.

Aceptan `rate_limits` las redes que declaran un ritmo: Pinterest, Reddit, Google Business Profile,
Telegram y Discord. La cuota diaria de YouTube ya era compartida (`PostgresQuotaLedger`).

## Qué versión de API usa cada red

```bash
uv run python scripts/versiones.py
```

Cada red declara en su descripción la versión contra la que está escrita y cuándo se la comparó por
última vez con la documentación (`ApiPin`). Una tarea semanal abre un issue cuando una versión está por
retirarse (120 días antes) o cuando pasaron seis meses sin que nadie la mire.

En Meta, Instagram y LinkedIn la versión la elige quien configura: esas redes retiran versiones seguido
y conviene fijarla y subirla a conciencia.

## Qué tan probada está cada red

Ver [niveles de soporte](niveles-de-soporte.md) y [pruebas en vivo](pruebas-en-vivo.md).
