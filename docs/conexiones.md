# Mantener vivas las conexiones

Una conexión sirve mientras su token sirva. Esta página explica cuándo deja de servir, cómo se entera la
app y cómo evitar que venza sin que nadie se dé cuenta.

## Estados de una conexión

| `ConnectionStatus` | Qué pasó | Qué devuelve usarla |
|---|---|---|
| `ACTIVE` | Sirve | Lo que corresponda |
| `EXPIRED` | Venció y la red no permite renovarla | `Refused(CONNECTION_EXPIRED)` |
| `INVALID` | La red rechazó el token: lo revocaron, cambió la contraseña o quitaron permisos | `Refused(CONNECTION_INVALID)` |
| `REVOKED` | Se desconectó a pedido | `Refused(CONNECTION_REVOKED)` |

En los tres últimos casos, la salida es que la persona vuelva a [conectar](conectar.md). Reconectar
conserva el id de la conexión y el de sus activos.

No todo error deja la conexión inválida: cada red declara qué respuestas significan "este token ya no
sirve". Un permiso que falta vuelve como `Refused(MISSING_PERMISSION)`, y un límite de uso como
`Refused(RATE_LIMITED)`; en los dos casos la conexión sigue sana. Ver
[la tabla de negativas](referencia/negativas.md).

## Renovación

Los tokens se renuevan solos, cuando la red lo permite, al usar la conexión. Si dos procesos intentan
renovar el mismo token al mismo tiempo, solo uno guarda el resultado y el otro usa el que quedó: así no se
pierde la conexión en las redes donde cada renovación cambia el token de renovación (X o TikTok, por
ejemplo).

El problema es la conexión que nadie usa: vence sin aviso, y en las redes que renuevan el mismo token
(Threads, Instagram con login propio) pasado cierto tiempo ya no se recupera. Para eso está
`refresh_expiring`, que conviene correr una vez por día desde un planificador:

```python
from datetime import timedelta

report = await social.refresh_expiring.execute(within=timedelta(days=7))
```

| Campo de `RefreshReport` | Qué son |
|---|---|
| `refreshed` | Se renovaron |
| `lost` | La red rechazó la renovación: quedaron inválidas |
| `not_refreshable` | La red no permite renovarlas (o todavía no): van a vencer, y conviene avisarle a la persona |
| `errored` | La red no respondió o falló: siguen como estaban y se reintentan en la próxima corrida |

Son ids de conexión.

## Enterarse de los cambios

`on_connection_change` se llama cuando una conexión deja de servir o vuelve a servir, con el cambio ya
guardado:

```python
from omnisocial import ConnectionChange, Omnisocial


async def avisar(change: ConnectionChange) -> None:
    if change.lost:
        ...  # venció, la red rechazó el token o se desconectó: pedirle a la persona que reconecte
    if change.recovered:
        ...  # alguien reconectó


social = Omnisocial.build(..., on_connection_change=avisar)
```

`change.connection` es la conexión como quedó, y `change.previous`, el estado anterior.
