# Métricas

Cada red llama a sus métricas de otra forma, y los nombres cambian entre versiones de la API. La librería
ofrece unas pocas **métricas comunes** (`CanonicalMetric`) que se traducen al nombre de cada red, y deja
pedir cualquier otra por su nombre nativo.

Los ejemplos suponen un `social` armado como en [Instalar y armar](instalar-y-armar.md) y un `asset_id`
sacado de [`list_assets`](conectar.md#usar-los-activos).

```python
from datetime import datetime, timedelta, timezone

from omnisocial import CanonicalMetric, InsightsRead, Period, Refused, TimeWindow

until = datetime.now(timezone.utc)
result = await social.read_insights.execute(
    asset_id,
    metrics=[CanonicalMetric.FOLLOWERS, CanonicalMetric.REACH, "page_video_views"],
    period=Period.DAY,
    window=TimeWindow(until - timedelta(days=30), until),
)
match result:
    case InsightsRead(series=series, unresolved=unresolved):
        for s in series:
            s.name, s.canonical, [(p.end_time, p.value) for p in s.points]
        # `unresolved`: métricas comunes sin traducción para ese activo y esa versión de la API
    case Refused(reason=reason):
        ...  # conexión vencida, permiso faltante, red sin métricas…
```

| Métrica común | Qué mide |
|---|---|
| `FOLLOWERS` | Seguidores |
| `REACH` | Cuentas distintas que vieron algo |
| `IMPRESSIONS` | Veces que se mostró algo |
| `VIEWS` | Reproducciones o vistas |
| `ENGAGEMENTS` | Interacciones (likes, comentarios, compartidos…) |

`Period` es `DAY`, `WEEK`, `DAYS_28` o `LIFETIME`, según lo que ofrezca la red.

Una métrica común que la red no tiene para ese activo no es un error: vuelve en `unresolved` y las demás
llegan igual. Qué traduce cada red, y desde qué versión de la API, está en su página (por ejemplo, el
[catálogo de Meta](meta.md)).

Cada red limita cuánto tiempo devuelve por llamada. En Meta, una ventana más larga se parte sola
(`MetaConfig.insights_max_span`); en las demás, ver la página de la red.
