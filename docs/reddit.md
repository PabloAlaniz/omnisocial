# Reddit: comunidades, títulos y lo que conviene saber

## Qué cubre

| Capacidad    | Qué hace |
|--------------|----------|
| `login`      | OAuth con la cuenta de Reddit. |
| `assets`     | La cuenta de quien autorizó (`reddit_account`). |
| `content`    | Sus publicaciones, en cualquier comunidad. |
| `publishing` | Un texto o un link en una comunidad. Borrar. |
| `comments`   | Leer el árbol de comentarios, responder, borrar lo propio y, si la cuenta modera, quitar y aprobar. |

**Sin imágenes ni videos, sin mensajes, sin métricas, sin webhooks.** Reddit no documenta cómo subir
medios por la API; los mensajes privados están pasando al chat, que no tiene API.

## Antes de integrar

- **Reddit aprueba cada app antes de darle acceso a la API**, y el uso comercial va por un acuerdo
  aparte. Conviene leer su política para quienes construyen sobre Reddit y las condiciones de la API.
- **No se publica lo mismo en varias comunidades**: su política lo prohíbe, y las comunidades lo
  castigan.
- **Lo que se borra en Reddit hay que borrarlo del lado propio**: las condiciones piden no conservar
  contenido ni datos de cuentas que ya no están.

## Armado

```python
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.reddit import CONNECT_SCOPES, PUBLISH_SCOPES, RedditConfig, reddit_provider

reddit = reddit_provider(
    RedditConfig(
        client_id="...",
        client_secret="...",
        user_agent="web:com.ejemplo.miproducto:1.0 (by /u/miusuario)",
        connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES,
    ),
    RetryingTransport(HttpxTransport()),
)
```

- **El `user_agent` es obligatorio.** Reddit limita fuerte a quien manda uno genérico y pide esa forma:
  plataforma, id de la app, versión y la cuenta responsable. Va en todos los pedidos.
- **El ritmo va incluido**: 100 pedidos por minuto por app. El proveedor separa los pedidos solo
  (`SPEC.pace`). Vale dentro de un proceso: con varios, conviene bajarlo con `pace=Pace(min_interval=…)`.

## Permisos y tokens

| Para | Permisos |
|---|---|
| Entrar | `identity` |
| Leer (`CONNECT_SCOPES`) | `identity`, `history`, `read`, `mysubreddits` |
| Publicar, responder y borrar (`PUBLISH_SCOPES`) | `submit`, `edit`, `flair` |
| Quitar y aprobar comentarios (`MODERATE_SCOPES`) | `modposts` |

- **El token de acceso dura una hora**; el de renovación no vence. Se pide con `duration=permanent`, que
  el adaptador ya manda.
- La app se identifica por cabecera. No se manda PKCE.

## Publicar

En Reddit se publica en una comunidad y con un título:

```python
from omnisocial import Draft
from omnisocial.reddit import RedditOptions

mine = await social.list_choices.execute(account.id, "communities")
found = await social.list_choices.execute(account.id, "communities", query="cocina")
# Done([Choice(id="cocina", name="r/cocina", data={"submission_type": "any", "subscribers": "52000"}), ...])
flairs = await social.list_choices.execute(account.id, "flairs", parent="cocina")

draft = Draft(
    "Probé tres recetas de budín y esta es la que mejor salió…",
    options=RedditOptions(subreddit="cocina", title="El budín de limón que no falla", flair_id="…"),
)
```

- **Sin `RedditOptions` no se publica**: `Refused(INVALID_DRAFT)` con el problema `OPTIONS_REQUIRED`. El
  título tiene hasta 300 caracteres.
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

## Lo que conviene saber

- **Los ids llevan un prefijo que dice qué son**: `t3_…` es una publicación y `t1_…` un comentario.
- **Los errores llegan por tres lados**: el estado HTTP, la cabecera `WWW-Authenticate` (token inválido,
  permiso faltante) y, en las escrituras, una lista en el cuerpo de una respuesta 200.
- **Un 403 sin más no es un permiso faltante**: es una comunidad privada o una cuenta vetada en ella.
- Sin verificar: el límite de 40.000 caracteres del texto (cambia por comunidad), la forma exacta de las
  respuestas al publicar y al comentar, y varios campos de las comunidades (`submission_type`). Nada se
  probó contra la API real.
