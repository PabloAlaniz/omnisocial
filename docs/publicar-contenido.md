# Publicar

Se publica un **borrador** (`Draft`) en un activo: una página, una cuenta, un canal. La misma forma sirve
para todas las redes. Lo que cambia es qué acepta cada una, y eso se comprueba antes de llamarla.

Los ejemplos suponen un `social` armado como en [Instalar y armar](instalar-y-armar.md) y un `asset_id`
sacado de [`list_assets`](conectar.md#usar-los-activos).

```python
from omnisocial import Done, Draft, Media, MediaKind, PublicationStatus, Refusal, Refused

draft = Draft(
    "Llegó el menú de invierno 🍲",
    media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/menu.jpg", alt_text="El menú"),),
    first_comment="Reservas por mensaje privado.",
)
result = await social.publish.execute(asset_id, draft, idempotency_key="menu-invierno")
match result:
    case Done(value=publication) if publication.status is PublicationStatus.PENDING:
        ...  # la red la está procesando: guardar publication.id y consultarla después
    case Done(value=publication):
        ...  # PUBLISHED o PUBLISHED_WITH_ERROR: publication.post_id, publication.url
    case Refused(reason=Refusal.INVALID_DRAFT, problems=problems):
        ...  # no entra en ese activo; no se llamó a la red
    case Refused(reason=reason):
        ...  # MISSING_PERMISSION, RATE_LIMITED, QUOTA_EXHAUSTED, CONTENT_REJECTED…
```

Publicar pide permisos que no están entre los de conexión por defecto en todas las redes: ver la página
de cada red.

## Validar antes de publicar

Cada tipo de activo declara lo que acepta: largo del texto, cantidad y tipo de medios, si admite un link o
un primer comentario. Un borrador que no entra vuelve como `Refused(INVALID_DRAFT)` con la lista de
`problems`, sin llamar a la red.

Para mostrar los problemas mientras alguien escribe, sin publicar:

```python
checked = await social.validate_draft.execute(asset_id, draft)
if isinstance(checked, Done):
    for problem in checked.value:
        ...  # problem.issue, problem.detail
```

## Medios

Según la red, los medios van por URL o como archivo:

- **Por URL pública (https)**: Meta, TikTok, Threads e Instagram los van a buscar a la URL. La URL se
  controla antes, para que no apunte a una dirección interna.
- **Como archivo**: YouTube, LinkedIn y X piden el archivo, que se sube por partes sin cargarlo entero en
  memoria.

```python
from omnisocial import Media, MediaKind, PathFile

video = Media(MediaKind.VIDEO, file=PathFile.open("video.mp4", "video/mp4"))
```

Si la subida se corta, vuelve `Refused(NOT_PUBLISHED)`: con certeza no salió, y se puede reintentar.

## Publicaciones en etapas

Instagram, TikTok y Threads procesan los medios antes de publicar. La publicación vuelve como `PENDING`, y
se retoma después:

```python
later = await social.check_publication.execute(publication_id)
```

Llamarlo dos veces no publica dos veces. Las publicaciones en curso se guardan en `publications`
([Instalar y armar](instalar-y-armar.md#armar-omnisocial)); sin un almacén persistente, un reinicio las
pierde.

## Estados

| `PublicationStatus` | Qué quiere decir | Qué hacer |
|---|---|---|
| `PUBLISHED` | Salió | Nada |
| `PENDING` | La red la está procesando | `check_publication` más tarde |
| `PUBLISHED_WITH_ERROR` | Salió, pero un paso posterior falló (el primer comentario, una parte del hilo) | No repetirla: ya está publicada |
| `STARTED` | No se sabe si salió: la red no respondió | Revisar en la red antes de reintentar. La librería no la repite sola |

## No publicar dos veces

Con `idempotency_key`, repetir el pedido devuelve la publicación que ya existe en vez de publicar de
nuevo. Conviene armar la clave con lo que identifica la publicación en la app (el id del post programado y
el del activo, por ejemplo).

- Si la red dijo con certeza que no salió, la clave se libera y se puede reintentar.
- Si no se sabe qué pasó, la publicación queda `STARTED` y la clave sigue tomada.

## Hilos

Donde la red los tiene (X, Threads, Bluesky, Mastodon):

```python
draft = Draft("Uno", thread=(Draft("Dos"), Draft("Tres")))
```

Si se corta a mitad de camino, lo que salió queda: `PUBLISHED_WITH_ERROR`, con la parte que falló.

## Opciones propias de una red

Lo que solo existe en una red va tipado en `options`:

```python
from omnisocial.tiktok import TikTokOptions

draft = Draft("…", media=(video,), options=TikTokOptions(privacy_level="SELF_ONLY"))
```

Cada página de red lista sus opciones.

### Elegir a dónde va

En algunas redes hay que elegir el destino: un pin va a un tablero de Pinterest, una publicación de Reddit
a una comunidad. Ahí las opciones son obligatorias, y lo que se puede elegir se le pide a la red:

```python
from omnisocial.pinterest import PinterestOptions

boards = await social.list_choices.execute(asset_id, "boards")
if isinstance(boards, Done):
    draft = Draft("…", media=(imagen,), options=PinterestOptions(board_id=boards.value[0].id))
```

`social.list_choices.available(asset_id)` dice qué consultas ofrece un activo. Una consulta que depende de
otra (las etiquetas de una comunidad de Reddit) lleva `parent=`.

## Borrar

```python
await social.delete_post.execute(asset_id, post_id=post_id)
```

Donde la red no lo permite, vuelve `Refused(ACTION_NOT_OFFERED)`.

## Lo que no hace

Cuándo publicar (programar, colas, reintentos diferidos) es de la app: la librería publica cuando se lo
piden y deja retomar lo que quedó en curso.
