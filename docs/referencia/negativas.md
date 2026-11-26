# Negativas y errores

Cada operación devuelve un resultado (`Done`, `Connected`, `InsightsRead`…) o una **negativa**:
`Refused(reason)`. Una negativa es una decisión que la app tiene que manejar (falta un permiso, la conexión
venció, el texto es muy largo). No es una falla del código.

Las **excepciones** quedan para lo que el código no puede decidir: una red que no responde, una respuesta
que no se entiende, un error de programación.

```python
from omnisocial import Done, Refusal, Refused

result = await social.publish.execute(asset_id, draft)
match result:
    case Done(value=publication):
        ...
    case Refused(reason=Refusal.RATE_LIMITED, retry_after=seconds):
        ...  # reintentar más tarde
    case Refused(reason=reason, detail=detail):
        ...
```

## `Refused`

| Campo | Qué trae |
|---|---|
| `reason` | El motivo: un `Refusal` de la tabla de abajo |
| `detail` | Más información, cuando la hay: qué credencial falta, qué dijo la red. Para registrar, no para mostrar tal cual |
| `problems` | Con `INVALID_DRAFT`: los problemas del borrador (`DraftProblem`: `issue`, `detail` y `part`, la parte del hilo) |
| `retry_after` | Con `RATE_LIMITED`: los segundos que pidió esperar la red, si lo dijo |
| `capability` | La capacidad que se estaba usando (`publishing`, `messaging`…) |
| `return_url` | En la autorización: a dónde volver para mostrar el error |

## Motivos

**¿Invalida la conexión?** Solo los tres `CONNECTION_*` describen una conexión que dejó de servir. Todos
los demás la dejan como estaba.

### Autorización y conexiones

| `Refusal` | Qué pasó | Qué hacer |
|---|---|---|
| `RETURN_URL_NOT_ALLOWED` | `return_url` no está entre los orígenes de `return_urls` | Corregir la URL o la política |
| `OWNER_REQUIRED` | Se quiso conectar sin dueño | Pasar `owner` |
| `UNKNOWN_STATE` | El `state` del callback no existe o ya se usó | Empezar la autorización de nuevo |
| `EXPIRED_STATE` | El `state` venció: la persona tardó demasiado en autorizar | Empezar de nuevo |
| `PROVIDER_DENIED` | La red no autorizó: la persona canceló, o el token o la credencial no sirven | Mostrarlo; la persona puede reintentar |
| `SERVER_REQUIRED` | Red federada sin servidor | Pasar `server` |
| `INVALID_SERVER` | El servidor no es un dominio público | Pedir otro |
| `CREDENTIALS_REQUIRED` | Falta un dato de la credencial (`detail` dice cuál) | Pedirlo |
| `NO_ASSETS` | El token sirve, pero no administra nada: no se guarda | Revisar los permisos de la cuenta en la red |
| `CONNECTION_EXPIRED` | La conexión venció y la red no permite renovarla | Volver a conectar |
| `CONNECTION_INVALID` | La red rechazó el token (lo revocaron, cambió la contraseña) | Volver a conectar |
| `CONNECTION_REVOKED` | Se desconectó a pedido | Volver a conectar |

### Al usar una conexión

| `Refusal` | Qué pasó | Qué hacer |
|---|---|---|
| `MISSING_PERMISSION` | Al token le falta un permiso | Volver a conectar pidiendo ese permiso. La conexión sigue sana para lo demás |
| `RATE_LIMITED` | La red pide bajar el ritmo | Esperar `retry_after` segundos, si vino |
| `QUOTA_EXHAUSTED` | Se acabó la cuota o el crédito de la app en la red | Esperar al próximo período o ampliar el plan. Reintentar enseguida no sirve |
| `NOT_SUPPORTED` | La red no tiene esa capacidad (mensajes en TikTok, por ejemplo) | Ver la [matriz](../index.md) |
| `ACTION_NOT_OFFERED` | La red no ofrece esa acción para ese activo (like a un comentario de Instagram) | No ofrecerla en la interfaz |
| `NOT_FOUND` | No existe: el activo, la publicación o la clave de idempotencia | Revisar el id |

### Publicar

| `Refusal` | Qué pasó | Qué hacer |
|---|---|---|
| `INVALID_DRAFT` | El borrador no entra en ese activo (`problems` dice por qué). No se llamó a la red | Corregir el borrador |
| `CONTENT_REJECTED` | La red no aceptó el contenido. No salió | Cambiar el contenido: repetirlo da lo mismo |
| `NOT_PUBLISHED` | Falló antes de que la red creara algo (se cortó la subida, por ejemplo). Con certeza no salió | Reintentar |
| `UNKNOWN_LOOKUP` | Ese activo no ofrece esa consulta auxiliar | Ver `list_choices.available` |
| `PARENT_REQUIRED` | La consulta depende de otra elección (`detail` dice de cuál) | Pasar `parent` |

### Mensajes

| `Refusal` | Qué pasó | Qué hacer |
|---|---|---|
| `OUTSIDE_REPLY_WINDOW` | Pasó el tiempo en que la red deja responder | En WhatsApp, mandar una plantilla |
| `NO_RECIPIENT` | No se sabe a quién mandarlo | Pasar `to` (ver [mensajes sin historial](../comentarios-y-mensajes.md#redes-sin-historial-whatsapp-y-telegram)) |
| `INVALID_MESSAGE` | El mensaje no entra en lo que acepta la red (`detail` dice por qué). No se llamó a la red | Corregir el mensaje |

### Perfiles públicos

| `Refusal` | Qué pasó | Qué hacer |
|---|---|---|
| `INVALID_HANDLE` | No es un nombre de cuenta válido para esa red | Pedir otro |
| `VIEWER_REQUIRED` | La red solo muestra cuentas ajenas a través de una cuenta propia, y no se pasó una que sirva | Pasar `viewer_asset_id` |
| `PROFILE_NOT_FOUND` | La cuenta no existe, o no es visible por la API | — |

## Excepciones

Todas heredan de `OmnisocialError`.

| Excepción | Cuándo |
|---|---|
| `UnknownProvider` | Se nombró una red que no se pasó a `Omnisocial.build` |
| `CapabilityNotSupported` | Se usó una capacidad que la red no tiene, en un lugar donde no vuelve como negativa |
| `TransportError` | La red no respondió o se cortó la conexión. Repetir más tarde puede andar |
| `ProviderError` | La red respondió con un error que no es una decisión de negocio (un pedido mal armado, una falla pasajera, una respuesta inesperada). `kind` dice de qué clase es |

Cada red declara qué significa cada uno de sus códigos de error (`ErrorKind`), y el núcleo decide igual
para todas:

| `ErrorKind` | Resultado |
|---|---|
| `TOKEN_DEAD` | La conexión queda inválida → `CONNECTION_INVALID` |
| `MISSING_PERMISSION` | `Refused(MISSING_PERMISSION)` |
| `RATE_LIMITED` | `Refused(RATE_LIMITED)`, con `retry_after` si la red lo dijo |
| `QUOTA_EXHAUSTED` | `Refused(QUOTA_EXHAUSTED)` |
| `INVALID_REQUEST`, `TRANSIENT`, `UNKNOWN` | `ProviderError` |

Un 401 o un 403 no siempre quiere decir que el token murió: depende de la red, y por eso cada una lo
declara.
