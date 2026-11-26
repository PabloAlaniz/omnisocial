# Perfiles públicos

Los datos públicos de una cuenta ajena (seguidores, publicaciones, bio), buscada por nombre o por URL.

Los ejemplos suponen un `social` armado como en [Instalar y armar](instalar-y-armar.md).

```python
from omnisocial import Done, Refusal, Refused

perfil = await social.lookup_profile.execute("x", network="x", handle="@marca")
match perfil:
    case Done(value=p):
        ...  # p.external_id, p.username, p.followers, p.posts, p.bio…
    case Refused(reason=Refusal.PROFILE_NOT_FOUND):
        ...
```

`handle` acepta `@marca`, `marca` o la URL del perfil. `omnisocial.parse_handle(network, texto)` hace esa
misma normalización por separado, por ejemplo para validar lo que escribe una persona.

**Guardar `external_id`, no el nombre.** El nombre de usuario puede cambiar; el id, no.

## Instagram: a través de una cuenta propia

Instagram solo muestra cuentas ajenas a través de una cuenta profesional propia, que se pasa como
**mirador** (`viewer_asset_id`):

```python
perfil = await social.lookup_profile.execute(
    "meta",
    network="instagram",
    handle="https://www.instagram.com/marca/",
    viewer_asset_id=instagram_asset_id,
)
```

Sin una cuenta que sirva, vuelve `Refused(VIEWER_REQUIRED)`. Si la cuenta buscada no existe o no es
profesional, `Refused(PROFILE_NOT_FOUND)`.

Qué redes ofrecen perfiles públicos está en la columna "Perfiles públicos" de la [matriz](index.md).
