# Instagram con login propio

Una cuenta profesional de Instagram conectada con su propio login, sin pasar por una página de Facebook.

## Qué cubre

Hay dos formas de conectar una cuenta profesional de Instagram, y para la librería son dos redes:

| | `meta` | `instagram` |
|---|---|---|
| La persona autoriza con | Facebook | Instagram |
| Hace falta una página de Facebook | Sí | No |
| App | La de Meta | La de Instagram (otro id y otro secreto) |
| Publicar, leer, comentarios, métricas | Sí | Sí |
| Mensajes privados y avisos | Sí | Todavía no |
| Perfiles públicos de otras cuentas | Sí | No: la API no los da con este login |
| Token | El de la página; no vence | 60 días; se renueva él mismo |

Conviene `instagram` cuando quien conecta no tiene (o no quiere usar) una página de Facebook, que es lo
común en creadores y negocios chicos. Conviene `meta` cuando hacen falta mensajes, avisos o perfiles
ajenos, o cuando ya se administran páginas: ver [Meta](meta.md).

## Antes de empezar

- La cuenta de Instagram tiene que ser **profesional** (empresa o creador).
- Una app de Meta para desarrolladores con el producto **Instagram** y su login propio (*Instagram API
  with Instagram Login*). Para usarla con cuentas ajenas, la app pasa por la misma revisión que en
  [Meta](meta.md#permisos).

## Crear la app

1. En [developers.facebook.com/apps](https://developers.facebook.com/apps), crear una app del tipo
   **Empresa** y agregarle el producto **Instagram**.
2. En *Instagram → API setup with Instagram login → Business login settings*, cargar la URL de retorno:
   `https://api.ejemplo.com/oauth/instagram/callback`.
3. En esa misma pantalla están el **id y el secreto de Instagram**. No son los de la app de Meta.

Documentación oficial:
[Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/)
(verificado 2026-11).

## Armado

```python
import os

from omnisocial.httpx import HttpxTransport, RetryingTransport
from omnisocial.instagram import CONNECT_SCOPES, PUBLISH_SCOPES, InstagramConfig, instagram_provider

instagram = instagram_provider(
    InstagramConfig(
        client_id=os.environ["INSTAGRAM_APP_ID"],
        client_secret=os.environ["INSTAGRAM_APP_SECRET"],
        api_version="v26.0",
        connect_scopes=CONNECT_SCOPES + PUBLISH_SCOPES,
    ),
    RetryingTransport(HttpxTransport()),
)
```

## Permisos

| Constante        | Permisos                                                                    |
|------------------|-----------------------------------------------------------------------------|
| `LOGIN_SCOPES`   | `instagram_business_basic`                                                  |
| `CONNECT_SCOPES` | el anterior, `instagram_business_manage_comments` y `instagram_business_manage_insights` |
| `PUBLISH_SCOPES` | `instagram_business_content_publish`                                        |

Los nombres viejos (`business_basic` y compañía) dejaron de servir en enero de 2025.

## Tokens

- **El token dura 60 días y no hay token de renovación**: se renueva el mismo token, y solo mientras esté
  vigente y tenga al menos un día de antigüedad.
- **Un token que venció no se recupera.** Por eso conviene la renovación anticipada diaria: ver
  [Mantener vivas las conexiones](conexiones.md#renovacion).
- No hay cómo revocar un token por API: la persona quita el acceso desde su cuenta.
- **Las llamadas no llevan `appsecret_proof`.** Con este login no hay app de Meta con la cual firmar.

## Publicar

Igual que una cuenta de Instagram por Facebook, con los mismos endpoints en `graph.instagram.com`: siempre
con medios, en etapas, hasta 20 en un carrusel, con primer comentario. Ver
[Publicar en Meta](meta.md#publicar).

## Errores

Los mismos códigos que [Meta](meta.md#errores).

## Lo que conviene saber

- **La cuenta se identifica con `user_id`**, el id de la cuenta profesional: es el que va en las rutas y
  el que llega en los avisos. El otro (`id`) es propio de la app y no sirve para eso.
- **El canje del código responde envuelto en `data`** (y a veces no): se aceptan las dos formas.
- **Instagram le agrega `#_` al código** en la URL de retorno. No es parte del código y se quita.
- **Sin like a comentarios**, como por Facebook.
- **El tipo de activo es el mismo** (`instagram_account`), bajo otra red. La misma cuenta conectada por los
  dos caminos son dos conexiones distintas.

!!! warning "A confirmar con la API real"
    - Con qué secreto se firman los avisos de este login: por eso todavía no se integran los mensajes ni
      los avisos.

Qué tan probada está esta red lo dice la columna "Soporte" de la [matriz de redes](index.md); qué
quiere decir cada nivel, [niveles de soporte](niveles-de-soporte.md).
