# Instagram con login propio

Hay dos formas de conectar una cuenta profesional de Instagram, y para la librería son dos redes:

| | `meta` | `instagram` |
|---|---|---|
| La persona autoriza con | Facebook | Instagram |
| Hace falta una página de Facebook | Sí | No |
| App | La de Meta | La de Instagram (otro id y otro secreto) |
| Publicar, leer, comentarios, métricas | Sí | Sí |
| Mensajes privados y webhooks | Sí | Todavía no |
| Perfiles públicos de otras cuentas | Sí | No: la API no los da con este login |
| Token | El de la página; no vence | 60 días; se renueva él mismo |

Conviene `instagram` cuando quien conecta no tiene (o no quiere usar) una página de Facebook, que es lo
común en creadores y negocios chicos. Conviene `meta` cuando hacen falta mensajes, webhooks o perfiles
ajenos, o cuando ya se administran páginas.

Lo de Instagram por Facebook está en [meta.md](meta.md). Esta página es la del login propio.

## Armado

```python
from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.instagram import CONNECT_SCOPES, PUBLISH_SCOPES, InstagramConfig, instagram_provider

instagram = instagram_provider(
    InstagramConfig(
        client_id=os.environ["INSTAGRAM_APP_ID"],
        client_secret=os.environ["INSTAGRAM_APP_SECRET"],
        api_version="v24.0",
        connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES,
    ),
    RetryingTransport(HttpxTransport()),
)
```

**El id y el secreto son los de Instagram**, no los de la app de Meta: están en el panel de la app, en
Instagram → "API setup with Instagram login" → "Business login settings".

## Permisos

| Constante        | Permisos                                                                    |
|------------------|-----------------------------------------------------------------------------|
| `LOGIN_SCOPES`   | `instagram_business_basic`                                                  |
| `CONNECT_SCOPES` | el anterior, `instagram_business_manage_comments` y `instagram_business_manage_insights` |
| `PUBLISH_SCOPES` | `instagram_business_content_publish`                                        |

Los nombres viejos (`business_basic` y compañía) dejaron de servir en enero de 2025.

## Tokens

- **El token dura 60 días y no hay token de renovación**: se renueva el mismo token, y solo mientras esté
  vigente y tenga más de un día.
- **Un token que venció no se recupera.** Para que una cuenta que nadie usa no se pierda, correr la
  renovación anticipada una vez por día: `await social.refresh_expiring.execute(within=timedelta(days=7))`.
- No hay cómo revocar un token por API: la persona quita el acceso desde su cuenta.
- **Las llamadas no llevan `appsecret_proof`.** Con este login no hay app de Meta con la cual firmar.

## Lo que conviene saber

- **La cuenta se identifica con `user_id`**, el id de la cuenta profesional: es el que va en las rutas y
  el que llega en los avisos. El otro (`id`) es propio de la app y no sirve para eso.
- **El canje del código responde envuelto en `data`** (y a veces no): se aceptan las dos formas.
- **Instagram le agrega `#_` al código** en la URL de retorno. No es parte del código y se quita.
- **Publicar, leer, comentar y medir es igual que por Facebook**: mismos endpoints, en
  `graph.instagram.com`. Los límites y lo aprendido son los de [meta.md](meta.md): siempre con medios, en
  etapas, hasta 20 en un carrusel, primer comentario, sin like a comentarios.
- **El tipo de activo es el mismo** (`instagram_account`), bajo otra red. La misma cuenta conectada por los
  dos caminos son dos conexiones distintas.
- Algunos mensajes de error todavía dicen "Meta" aunque la red sea Instagram: vienen de los adaptadores
  compartidos.
