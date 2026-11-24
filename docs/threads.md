# Threads: login, publicar en etapas y lo que conviene saber

## Qué cubre

| Capacidad    | Qué hace                                                                  |
|--------------|---------------------------------------------------------------------------|
| `login`      | Autorizar, canjear el código por un token largo y renovarlo.              |
| `assets`     | La cuenta de quien autorizó es el único activo (`threads_account`).       |
| `content`    | Los posts de la cuenta.                                                   |
| `publishing` | Un post o un hilo, con texto, link, imágenes, videos o un carrusel. Borrar. |
| `comments`   | Leer las respuestas a un post, responder y ocultar.                       |
| `insights`   | Seguidores, vistas por día y totales de likes, respuestas, reposts y citas. |

**Threads es de Meta, pero es otra API**: otro servidor, otra app (con su propio id y su propio secreto) y
otros tokens. Una conexión de Meta no sirve para Threads, ni al revés.

**Sin mensajes, sin like, sin perfiles públicos, sin webhooks por ahora.** La API no tiene mensajes ni
forma de dar like. Buscar el perfil de otra cuenta existe, pero con el acceso estándar solo funciona para
cuatro cuentas de Meta. Los avisos existen (respuestas, menciones, publicaciones) y todavía no se integran.

## Armado

```python
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.threads import (
    CONNECT_SCOPES,
    MODERATE_SCOPES,
    PUBLISH_SCOPES,
    ThreadsConfig,
    threads_provider,
)

threads = threads_provider(
    ThreadsConfig(
        client_id=os.environ["THREADS_APP_ID"],
        client_secret=os.environ["THREADS_APP_SECRET"],
        connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES + MODERATE_SCOPES,
    ),
    RetryingTransport(HttpxTransport()),
)
```

## Permisos

| Constante         | Permisos                                                          | Para qué                          |
|-------------------|-------------------------------------------------------------------|-----------------------------------|
| `LOGIN_SCOPES`    | `threads_basic`                                                   | Saber quién es la persona.        |
| `CONNECT_SCOPES`  | `threads_basic`, `threads_read_replies`, `threads_manage_insights` | Leer posts, respuestas y métricas.|
| `PUBLISH_SCOPES`  | `threads_content_publish`, `threads_delete`                       | Publicar, responder y borrar.     |
| `MODERATE_SCOPES` | `threads_manage_replies`                                          | Ocultar respuestas.               |

## Tokens

- **El token dura 60 días y no hay token de renovación**: se renueva el mismo token, y solo mientras esté
  vigente y tenga más de un día.
- **Un token que venció no se recupera.** La persona tiene que volver a autorizar. Como un token se renueva
  solo cuando alguien usa la conexión, una cuenta que nadie toca durante dos meses se pierde. Para que no
  pase, correr la renovación anticipada una vez por día:

  ```python
  report = await social.refresh_expiring.execute(within=timedelta(days=7))
  ```

- No hay forma documentada de revocar un token por API: la persona quita el acceso desde su cuenta.
- **El dominio documentado hoy es `threads.com`** (`graph.threads.com`); el anterior, `threads.net`, sigue
  andando. Los dos se pueden cambiar en `ThreadsConfig`.

## Publicar

```python
from omnisocial import Draft, Media, MediaKind

draft = Draft(
    "Abrimos el local nuevo 🎉",
    media=(Media(MediaKind.IMAGE, "https://cdn.ejemplo.com/local.jpg", alt_text="El frente"),),
    thread=(Draft("Estamos en Av. Siempreviva 742."), Draft("De lunes a sábado, de 9 a 20.")),
)
result = await social.publish.execute(account.id, draft, idempotency_key="local-nuevo")
```

- **Un post de texto sale en un paso.** Con medios va en etapas: Threads descarga y procesa los medios
  (pide esperar unos 30 segundos) y la publicación queda `PENDING`. `check_publication` la retoma;
  conviene consultar una vez por minuto.
- **Los medios son URLs públicas.** Hasta 20 imágenes o videos en un carrusel, mezclados. Imágenes JPEG o
  PNG de hasta 8 MB; videos MP4 o MOV de hasta 1 GB y 5 minutos.
- **Hilos:** cada parte responde a la anterior, así que una parte no se puede armar hasta que salió la que
  la precede. Un hilo con medios puede quedar pendiente varias veces: el estado guarda el plan entero y por
  dónde va. Mientras tanto, `post_id` ya trae el id de la primera parte.
- **Si un hilo se corta**, lo anterior ya salió: queda `PUBLISHED_WITH_ERROR`, con el id del primer post y
  el número de la parte que falló.
- **El texto admite 500 caracteres, y los emojis cuentan por sus bytes** (cuatro, en general): 125 emojis ya
  llenan un post.
- **Un link adjunto** (`Draft(link=...)`) va solo en un post de texto. Un post admite hasta 5 links
  distintos entre el texto y el adjunto.
- `ThreadsOptions(reply_to=...)` responde a un post; `reply_control` dice quién puede responder y
  `topic_tag` le pone tema. Las dos últimas valen para la primera parte.
- **Topes por día:** 250 posts, 1.000 respuestas y 100 borrados por cuenta.
- Sin primer comentario: para eso está el hilo.

## Posts, respuestas y métricas

- **Los contadores de cada post no vienen en el listado** (`like_count` queda en `None`): están en las
  métricas de cada post, de a uno por llamada.
- **Las respuestas se leen de a un nivel.** Para las respuestas a una respuesta, `list_comments` con su id.
  Las de la propia cuenta (las partes de un hilo) no se devuelven como comentarios.
- **Threads identifica al autor de una respuesta por su nombre de usuario**, no por un id: `author_id`
  queda vacío.
- **Solo se ocultan las respuestas de primer nivel.** Borrar una respuesta ajena no existe.
- **Métricas:** `followers_count` es la cantidad de hoy y no acepta ventana. `views` es un punto por día
  dentro de la ventana. `likes`, `replies`, `reposts` y `quotes` son el total de la ventana. Sin ventana,
  Threads devuelve de ayer a hoy.

## Errores

**Threads no documenta sus códigos de error.** Responde con la forma de la Graph API de Meta, y el
adaptador usa los códigos generales de esa API: 190 como token muerto, 10 y 200–299 como permiso
faltante, 4, 17 y 613 como límite de uso. Es lo primero a confirmar con una cuenta real: si un código
resulta distinto, se corrige en una línea de la tabla `ERRORS`.

Mientras procesa los medios, un contenedor puede fallar con `FAILED_DOWNLOADING_VIDEO`,
`FAILED_PROCESSING_VIDEO` o `INVALID_ASPEC_RATIO` (así, con el error de tipeo): la publicación queda
`FAILED` con ese motivo.
