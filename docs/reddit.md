# Reddit

La cuenta de Reddit de quien autoriza: publicar en comunidades, leer y moderar comentarios.

## Qué cubre

| Capacidad    | Qué hace |
|--------------|----------|
| `login`      | OAuth con la cuenta de Reddit. |
| `assets`     | La cuenta de quien autorizó (`reddit_account`). |
| `content`    | Sus publicaciones, en cualquier comunidad. |
| `publishing` | Un texto o un link en una comunidad. Borrar. |
| `comments`   | Leer el árbol de comentarios, responder, borrar lo propio y, si la cuenta modera, quitar y aprobar. |

**Sin imágenes ni videos, sin mensajes, sin métricas, sin avisos.** Reddit no documenta cómo subir
medios por la API; los mensajes privados están pasando al chat, que no tiene API.

## Antes de empezar

- **Reddit aprueba cada app antes de darle acceso a la API**, y el uso comercial va por un acuerdo
  aparte. Conviene leer su política para quienes construyen sobre Reddit y las condiciones de la API.
- **No se publica lo mismo en varias comunidades**: su política lo prohíbe, y las comunidades lo
  castigan.
- **Lo que se borra en Reddit hay que borrarlo del lado propio**: las condiciones piden no conservar
  contenido ni datos de cuentas que ya no están.

## Crear la app

1. En [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps), crear una app del tipo **web app**.
2. Cargar la URL de retorno `https://api.ejemplo.com/oauth/reddit/callback`.
3. Copiar el **client id** (debajo del nombre de la app) y el **secret**.
4. Pedir el acceso a la API (ver [Antes de empezar](#antes-de-empezar)).

Documentación oficial: [Reddit API](https://www.reddit.com/dev/api/) (verificado 2026-11).

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.reddit import CONNECT_SCOPES, PUBLISH_SCOPES, RedditConfig, reddit_provider

reddit = reddit_provider(
    RedditConfig(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent="web:com.ejemplo.miproducto:1.0 (by /u/miusuario)",
        connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES,
    ),
    RetryingTransport(HttpxTransport()),
)
```

- **El `user_agent` es obligatorio.** Reddit limita fuerte a quien manda uno genérico y pide esa forma:
  plataforma, id de la app, versión y la cuenta responsable. Va en todos los pedidos.
- **El ritmo va incluido**: el proveedor separa los pedidos solo (`SPEC.pace`). Vale dentro de un
  proceso. Con varios, se reparte con un almacén compartido (`reddit_provider(..., rate_limits=...)`, ver
  [Operar](operar.md#limites-de-uso-entre-varios-procesos)), o se baja el ritmo de cada uno con
  `reddit_provider(..., pace=Pace(min_interval=…))`, con `Pace` de `omnisocial`.

## Permisos

| Para | Permisos |
|---|---|
| Entrar | `identity` |
| Leer (`CONNECT_SCOPES`) | `identity`, `history`, `read`, `mysubreddits` |
| Publicar, responder y borrar (`PUBLISH_SCOPES`) | `submit`, `edit`, `flair` |
| Quitar y aprobar comentarios (`MODERATE_SCOPES`) | `modposts` |

La app se identifica por cabecera. No se manda PKCE.

## Tokens

- **El token de acceso dura una hora**; el de renovación no vence. Se pide con `duration=permanent`, que
  el adaptador ya manda.

## Publicar

En Reddit se publica en una comunidad y con un título:

```python
from omnisocial import Draft
from omnisocial.reddit import RedditOptions

mine = await social.list_choices.execute(asset_id, "communities")
found = await social.list_choices.execute(asset_id, "communities", query="cocina")
# Done([Choice(id="cocina", name="r/cocina", data={"submission_type": "any", "subscribers": "52000"}), ...])
flairs = await social.list_choices.execute(asset_id, "flairs", parent="cocina")

draft = Draft(
    "Probé tres recetas de budín y esta es la que mejor salió…",
    options=RedditOptions(subreddit="cocina", title="El budín de limón que no falla", flair_id="…"),
)
result = await social.publish.execute(asset_id, draft)
```

- **Sin `RedditOptions` no se publica**: `Refused(INVALID_DRAFT)` con el problema `OPTIONS_REQUIRED`.
- **Un texto o un link.** Con `Draft(link=…)` sale una publicación de link y el texto no se manda.
- **Cada comunidad pone sus reglas**: hay las que solo aceptan texto, las que piden etiqueta, las que no
  dejan publicar a cuentas nuevas. La consulta dice qué tipo de publicación acepta (`submission_type`);
  el resto se sabe cuando Reddit rechaza: `Refused(CONTENT_REJECTED)`, con su motivo en `detail`.
- **"Estás publicando demasiado"** vuelve como `Refused(RATE_LIMITED)`, con los segundos que Reddit pide
  esperar. Les pasa a las cuentas nuevas o con poco karma en esa comunidad.
- **Para publicar en el perfil propio**, la comunidad es `u_<usuario>`.
- `resubmit=False` hace que Reddit rechace un link que ya está en la comunidad.

## Comentarios

- **`list_comments` trae el árbol que Reddit manda en un pedido.** Las ramas que deja para pedir aparte
  ("cargar más comentarios") no se siguen.
- **Ocultar es quitar**, y solo funciona en las comunidades que la cuenta modera. Mostrar es aprobar.
- **Borrar es borrar un comentario propio.** Uno ajeno no se borra: se quita.
- **No se ofrece dar like.** Es votar, y Reddit pide que los votos los emita una persona.

## Límites

| Qué | Límite |
|---|---|
| Pedidos | 100 por minuto por app |
| Título | 300 caracteres |
| Texto | 40.000 caracteres (cada comunidad puede pedir menos) |

## Errores

Llegan por tres lados: el estado HTTP, la cabecera `WWW-Authenticate` y, en las escrituras, una lista en el
cuerpo de una respuesta 200.

| Respuesta | Resultado |
|---|---|
| 401, `invalid_token`, `USER_REQUIRED` | La conexión queda inválida |
| `insufficient_scope` | `Refused(MISSING_PERMISSION)` |
| `RATELIMIT`, `SUBREDDIT_RATELIMIT` | `Refused(RATE_LIMITED)`, con los segundos que pide esperar |
| 400, y lo que rechaza una comunidad | `ProviderError`; al publicar, `Refused(CONTENT_REJECTED)` con el motivo en `detail` |
| 403 sin más | No es un permiso faltante: una comunidad privada o una cuenta vetada en ella |

## Lo que conviene saber

- **Los ids llevan un prefijo que dice qué son**: `t3_…` es una publicación y `t1_…` un comentario.

!!! warning "A confirmar con la API real"
    - El límite de 40.000 caracteres del texto.
    - La forma exacta de las respuestas al publicar y al comentar.
    - Varios campos de las comunidades (`submission_type`).

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
