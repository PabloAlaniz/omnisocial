# Login con una red

El mismo diálogo de [conectar](conectar.md#con-el-dialogo-de-la-red), con `Purpose.LOGIN`, sirve para
"Entrar con Meta" o "Entrar con Google". No guarda una conexión: devuelve la identidad de la persona, y la
app crea su propia sesión.

```python
from omnisocial import Purpose

started = await social.start_authorization.execute(
    "meta", purpose=Purpose.LOGIN, return_url="https://app.ejemplo.com/"
)
# redirigir a started.url
```

Al volver, las rutas de Starlette llaman a `on_logged_in` con la identidad:

```python
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from omnisocial import LoggedIn
from omnisocial.starlette import oauth_routes


async def crear_sesion(request: Request, result: LoggedIn) -> Response:
    identity = result.identity  # identity.provider, identity.external_id, identity.name…
    usuario = await usuarios.por_identidad(identity.provider, identity.external_id)
    response = RedirectResponse(result.return_url or "/")
    ...  # crear la sesión de la app en la respuesta
    return response


app.router.routes.extend(oauth_routes(social, on_logged_in=crear_sesion))
```

`identity.external_id` es el id estable de la persona en esa red: conviene guardar ese y no el nombre, que
puede cambiar.

Qué redes ofrecen login está en la columna "Login" de la [matriz](index.md).
