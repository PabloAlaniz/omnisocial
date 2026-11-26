# Pinterest

La cuenta de Pinterest de quien autoriza: pines, tableros y métricas.

## Qué cubre

| Capacidad    | Qué hace |
|--------------|----------|
| `login`      | OAuth con la cuenta de Pinterest. |
| `assets`     | La cuenta de quien autorizó (`pinterest_account`). |
| `content`    | Los pines de la cuenta, con sus contadores. |
| `publishing` | Un pin con una imagen, un carrusel de 2 a 5 o un video. Borrar. |
| `insights`   | Seguidores, y las métricas de la cuenta por día o en total. |

**Sin comentarios, sin mensajes, sin avisos.** La API no los tiene: la cantidad de comentarios y de
reacciones de un pin llega solo como contador.

## Crear la app

1. En [developers.pinterest.com/apps](https://developers.pinterest.com/apps/), con una cuenta de empresa,
   crear una app.
2. Cargar la URL de retorno `https://api.ejemplo.com/oauth/pinterest/callback` y copiar el **app id** y
   el **app secret**.
3. La app arranca con **acceso de prueba**. Para usarla de verdad, pedir el **acceso estándar**.

Documentación oficial: [Pinterest API v5](https://developers.pinterest.com/docs/api/v5/) (verificado
2026-11).

### El nivel de acceso

- **Con acceso de prueba, lo que se crea solo lo ve quien lo creó.** Sirve para integrar, no para
  publicar. El acceso estándar se pide con un video del flujo de autorización.
- **Hay un ambiente de prueba aparte**, con su propio token: `PinterestConfig(..., api_base=SANDBOX_BASE)`,
  con `SANDBOX_BASE` de `omnisocial.pinterest`.
- **Leer datos de cuentas que no son de empresa** puede pedir una autorización más de Pinterest, según
  cuándo se registró la app: en ese caso vuelve `Refused(MISSING_PERMISSION)`.

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.pinterest import CONNECT_SCOPES, PUBLISH_SCOPES, PinterestConfig, pinterest_provider

pinterest = pinterest_provider(
    PinterestConfig(
        client_id=os.environ["PINTEREST_APP_ID"],
        client_secret=os.environ["PINTEREST_APP_SECRET"],
        connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES,
    ),
    RetryingTransport(HttpxTransport()),
)
```

Para repartir el ritmo de pedidos entre procesos, `rate_limits=` (ver
[Operar](operar.md#limites-de-uso-entre-varios-procesos)).

## Permisos

| Para | Permisos |
|---|---|
| Entrar | `user_accounts:read` |
| Leer pines, tableros y métricas | `user_accounts:read`, `boards:read`, `pins:read` |
| Publicar y borrar (`PUBLISH_SCOPES`) | `boards:write`, `pins:write`, además de los de lectura |

Los permisos van separados por comas, y la app se identifica por cabecera. No se manda PKCE.

## Tokens

- **El token dura 30 días y el de renovación, 60.** Cada renovación trae un token de renovación nuevo y el
  anterior deja de servir. La renovación anticipada mantiene viva la conexión aunque nadie la use: ver
  [Mantener vivas las conexiones](conexiones.md).
- **No hay cómo revocar el token de una persona**: desconectar borra la conexión de este lado.

## Publicar

Un pin va siempre a un tablero. Los tableros salen de una consulta auxiliar:

```python
from omnisocial import Draft, Media, MediaKind
from omnisocial.pinterest import PinterestOptions

boards = await social.list_choices.execute(asset_id, "boards")
# Done([Choice(id="549755885175", name="Recetas", data={"privacy": "PUBLIC"}), ...])

draft = Draft(
    "Fácil y rico: sale en 40 minutos.",
    media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/budin.jpg", alt_text="Un budín de limón"),),
    options=PinterestOptions(
        board_id="549755885175", title="Budín de limón", link="https://ejemplo.com/budin"
    ),
)
result = await social.publish.execute(asset_id, draft)
```

- **Sin `PinterestOptions` no se publica**: `Refused(INVALID_DRAFT)` con el problema `OPTIONS_REQUIRED`.
- **El texto del borrador es la descripción** (hasta 800 caracteres). El título (hasta 100) y el link de
  destino van en las opciones.
- **Las secciones de un tablero** salen de `list_choices.execute(asset_id, "board_sections",
  parent=board_id)`.
- **Las imágenes van por URL o como archivo.** Como archivo viajan dentro del pedido. En un carrusel van
  todas de la misma forma.
- **Un video va como archivo**, y en etapas: se sube, Pinterest lo procesa y recién entonces se crea el
  pin. Mientras tanto la publicación queda `PENDING`. La portada es `cover_image_url` o un cuadro del
  video (`cover_second`).
- **El texto alternativo** es el del primer medio que lo tenga.

## Métricas

`IMPRESSION`, `ENGAGEMENT`, `PIN_CLICK`, `OUTBOUND_CLICK`, `SAVE` y sus tasas (`…_RATE`), más
`follower_count`. Con período diario, un punto por día; si no, el total del tramo.

- **Pinterest guarda 90 días.** Una ventana más larga se recorta; sin ventana, los últimos 30 días.
- Las tasas son proporciones, no cantidades: no se suman.

## Límites

| Qué | Límite |
|---|---|
| Acceso de prueba | 1.000 pedidos y 300 escrituras por día |
| Acceso estándar | Por minuto, según el endpoint |
| Descripción | 800 caracteres |
| Título | 100 caracteres |
| Carrusel | De 2 a 5 imágenes |

El límite de uso dice cuándo vuelve (`x-ratelimit-reset`, en segundos).

## Errores

| Respuesta | Resultado |
|---|---|
| 401 | La conexión queda inválida |
| 403 | `Refused(MISSING_PERMISSION)`. También lo da el acceso de prueba cuando no alcanza |
| 429 | `Refused(RATE_LIMITED)` |
| 400 | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` |

## Lo que conviene saber

- **Pinterest no devuelve la dirección de un pin**: se arma (`https://www.pinterest.com/pin/<id>/`).
- **El orden de los pines no está documentado.** `list_posts` no corta al salir de la ventana: recorre
  hasta `max_pages` páginas y filtra.

!!! warning "A confirmar con la API real"
    - Los límites de tamaño de las imágenes y de los videos.
    - El significado de los códigos de error distintos del 2.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
