# Hoja de ruta: diez sprints

El objetivo es que omnisocial sea la referencia para conectar redes sociales desde Python: muchas redes,
las mismas reglas, y que sumar una red nueva sea barato para quien no conoce el núcleo.

Al empezar había dos redes (Meta y TikTok), ocho capacidades y ninguna de ellas publicaba. El plan va en este orden:
primero lo que abarata cada red nueva, después publicar, después las redes, y al final lo que hace falta
para sostenerlas y prometer estabilidad.

Cada sprint cierra con una versión publicada y con su documentación. Una red está terminada cuando pasa el
contrato común, tiene su página en `docs/` y aparece en la matriz de capacidades.

## Resumen

| Sprint | Tema | Redes que suma |
|--------|------|----------------|
| 1 ✓ | Cimientos para muchas redes | — |
| 2 ✓ | Publicar | Meta y TikTok publican |
| 3 ✓ | Video largo y cuotas | YouTube |
| 4 ✓ | Redes profesionales y pagas | LinkedIn, X |
| 5 ✓ | Salud de las conexiones | Threads, Instagram con login propio |
| 6 | Redes abiertas y federadas | Bluesky, Mastodon, Pixelfed |
| 7 | Publicaciones con campos propios | Pinterest, Reddit, Google Business Profile |
| 8 | Mensajería y comunidades | WhatsApp Business, Telegram, Discord |
| 9 | Operar en producción | — |
| 10 | Versión 1.0 | Snapchat, Twitch (según demanda) |

Al terminar: 16 redes o más, contra las 2 de hoy.

## Sprint 1. Cimientos para muchas redes

**Hecho.** Lo que se copiaba de Meta a mano ahora es una herramienta. La decisión está en el
[ADR 0007](adr/0007-descripcion-y-contrato-de-una-red.md). Quedó para más adelante declarar las cabeceras
de límite de uso: entran con la concurrencia por red (sprint 7) y los límites compartidos (sprint 9), que
son quienes las van a usar.

- **Contrato común para adaptadores** (`omnisocial.testing`): una batería de pruebas por capacidad que
  cualquier red corre contra respuestas grabadas, como ya existe para los almacenes
  (`tests/adapters/stores/contract.py`). La usan también los paquetes externos.
- **Descripción declarativa de la red**: URLs de OAuth, separador de permisos, PKCE, versión de la API,
  cabeceras de límite de uso y cómo se renueva el token son datos, no código. La clase queda para lo que
  la red hace distinto.
- **Tabla de errores por red**: cada adaptador declara qué respuesta significa token muerto, permiso
  faltante, límite de uso, cuota agotada, pedido inválido o reintentable. El núcleo decide qué hacer con
  cada clase. Suma las negativas `RATE_LIMITED` y `QUOTA_EXHAUSTED`.
- **Matriz de capacidades generada**: una tabla red × capacidad × tipo de activo que sale del código y se
  publica en el README. CI falla si quedó vieja.
- **Generador de esqueleto**: un comando que crea el adaptador, sus pruebas y su página de documentación
  con los pendientes marcados.
- **Contribuir**: `CONTRIBUTING.md`, plantillas de issue (error en una red, con lista de redes; pedido de
  red nueva) y plantilla de PR con la lista de control de una red.

## Sprint 2. Publicar

**Hecho**, salvo dos cosas que pasan a los sprints donde hay una red que las necesita: los **hilos**
(sprint 4, con X, y sprint 5, con Threads) y la **subida de archivos por partes** (sprint 3: YouTube no
acepta otra cosa; Meta y TikTok toman los medios de una URL). El estado `lista` no existe: retomar una
publicación la lleva sola de `pendiente` a `publicada`. La decisión está en el
[ADR 0008](adr/0008-publicar.md).

- **Puerto `Publisher`** con un borrador común: texto, medios, hilo, primer comentario y opciones propias
  de la red, tipadas.
- **Validar antes de publicar**: cada red declara sus límites (largo del texto, cantidad y tipo de medios,
  tamaño, duración, si mezcla fotos y videos). Un borrador que no entra vuelve como `Refused` con el
  motivo, sin llamar a la red.
- **Publicación en etapas**: muchas redes publican en dos pasos (subir, esperar el procesamiento,
  confirmar). El resultado es un estado (`pendiente`, `lista`, `publicada`, `publicada con error`) que se
  puede retomar sin duplicar la publicación.
- **Clave de idempotencia**: reintentar el mismo pedido no publica dos veces.
- **Subida de medios**: por partes y reanudable en el transporte, con cuerpos que no se pueden reenviar
  tratados aparte de los reintentos comunes. Las URLs de medios pasan por un control contra pedidos a
  direcciones internas.
- **Borrar una publicación**, donde la red lo permite.
- Implementado en Meta (páginas e Instagram) y TikTok. La documentación de TikTok explica la auditoría que
  exige para publicar.

## Sprint 3. Video largo y cuotas: YouTube

**Hecho.** Quedaron afuera, porque no hacían falta para lo esencial: los avisos de videos nuevos (un
mecanismo propio, con XML y firma SHA-1), las series históricas de YouTube Analytics, la miniatura propia y
el primer comentario. Ver [docs/youtube.md](youtube.md) y el
[ADR 0009](adr/0009-cuota-y-subida-por-partes.md).

- Login con Google, el canal como activo, videos, comentarios, métricas y perfiles públicos con clave de
  API. Lo aprendido está en [youtube.md](youtube.md).
- Subida reanudable de video; la miniatura que falla después de subir es `publicada con error`, no un
  fracaso.
- **Presupuesto de cuota**: un puerto que cuenta el costo de cada llamada y corta antes de agotar el día.
- Al reconectar se conserva el token de renovación anterior si la red no manda uno nuevo. Regla del
  núcleo, no de YouTube.

## Sprint 4. Redes profesionales y pagas: LinkedIn y X

**LinkedIn está hecho** ([docs/linkedin.md](linkedin.md)): login, el perfil y las páginas como activos,
publicar en los dos, y publicaciones, comentarios y métricas de las páginas. Quedó afuera avisar cuando la
versión de la API está por ser retirada (hoy se documenta y el error lo dice claro) y los contadores por
publicación.

**X está hecho** ([docs/x.md](x.md)): login con PKCE, posts, respuestas, contadores, perfiles públicos y
publicar posts e hilos con medios. Con X llegaron al núcleo los hilos, el largo de texto con peso y la
prueba de que perder la carrera con un token de renovación que rota no invalida la conexión. Quedaron
afuera los mensajes privados y los avisos de actividad.

- **LinkedIn**: login, páginas de empresa, publicaciones y comentarios. La versión de la API es
  configuración obligatoria y se avisa cuando está por ser retirada. Se comprueban los permisos otorgados
  al conectar, porque la red no avisa cuando falta uno.
- **X**: login con PKCE, publicaciones, respuestas, perfiles públicos. Sin créditos es
  `QUOTA_EXHAUSTED`, nunca una conexión inválida. La documentación dice qué plan exige cada capacidad.
- **Tokens de renovación que rotan** (X, TikTok): prueba de contrato que demuestra que dos renovaciones
  simultáneas no pierden la conexión.
- **Variantes de una red como proveedores distintos** (perfil personal y página, por ejemplo), en lugar de
  cambiar el comportamiento de uno existente.

## Sprint 5. Salud de las conexiones: Threads e Instagram con login propio

**Hecho** ([ADR 0010](adr/0010-salud-de-las-conexiones.md), [threads.md](threads.md),
[instagram.md](instagram.md)). Quedaron afuera los webhooks de Threads y, en Instagram con login propio,
los mensajes y los webhooks: la documentación no deja claro con qué secreto se firman, y conviene
resolverlo con una cuenta real.

- **Threads**: login, publicar (con hilos), respuestas y métricas.
- **Instagram con login propio**, sin pasar por una página de Facebook.
- **Renovación anticipada**: un caso de uso que lista las conexiones por vencer y las renueva, para correr
  desde un planificador. Hoy se renueva recién al usar.
- **Avisos de salud**: la app se entera cuando una conexión queda inválida y cuando se recupera, sin
  esperar a que falle una operación.
- **Reconexión**: volver a autorizar conserva el id de la conexión y de sus activos.

## Sprint 6. Redes abiertas y federadas: Bluesky, Mastodon y Pixelfed

- **Conexión por credencial**: generaliza el usuario de sistema para redes que no usan OAuth clásico
  (contraseña de aplicación, token de bot).
- **Bluesky**: publicar con hilos, respuestas, perfiles públicos. El video va por un servicio aparte.
- **Mastodon**: la app se registra en cada instancia. La instancia es parte de la conexión, no de la
  configuración global, y los datos de cada registro se guardan cifrados.
- **Pixelfed**: comparte protocolo con Mastodon; sale casi gratis y prueba que la abstracción aguanta.
- `parse_handle` aprende los nombres con dominio (`@persona@instancia`).

## Sprint 7. Publicaciones con campos propios: Pinterest, Reddit y Google Business Profile

- **Consultas auxiliares**: algunas redes exigen elegir algo antes de publicar (tablero, comunidad,
  etiqueta, sede). Un puerto para listarlas.
- **Pinterest**: tableros y pines, métricas.
- **Reddit**: publicar en comunidades, comentarios. Un pedido por segundo.
- **Google Business Profile**: sedes como activos, novedades, y reseñas con respuesta.
- **Concurrencia por red**: cada adaptador declara cuántas llamadas simultáneas tolera y el transporte lo
  respeta.

## Sprint 8. Mensajería y comunidades: WhatsApp Business, Telegram y Discord

- **WhatsApp Business**: mensajes con la ventana de 24 horas que ya modela `ReplyWindow`, plantillas para
  escribir fuera de la ventana, y webhooks.
- **Telegram**: bots, canales y grupos; publicar y recibir.
- **Discord**: publicar en canales, por bot o por webhook.
- **Mensajes con adjuntos** y estados de entrega en el dominio.
- **Bandeja unificada**: comentarios, mensajes y reseñas de todas las redes con la misma forma.

## Sprint 9. Operar en producción

- **Observabilidad**: ganchos para trazas y métricas por red y por operación, con OpenTelemetry como extra.
  Los tokens y las cabeceras de autorización nunca llegan a un log o a una traza; hay una prueba que lo
  vigila.
- **Límites de uso compartidos**: el estado de los límites vive en un almacén, para que varios procesos no
  se pisen.
- **Pruebas en vivo**: una corrida nocturna contra cuentas de prueba, red por red, que alimenta un estado
  público.
- **Niveles de soporte**: cada red se declara `verificada` (con pruebas en vivo y responsable),
  `comunitaria` o `experimental`. La matriz lo muestra.
- **Vigilancia de versiones**: una tarea programada que avisa cuando una red anuncia el retiro de la
  versión de API que el adaptador usa.
- **Cadena de suministro**: atestaciones de origen en cada versión, lista de componentes (SBOM) y
  puntuación pública de prácticas de seguridad.

## Sprint 10. Versión 1.0

- **Promesa de estabilidad**: qué es API pública, cómo se anuncia un cambio y cuánto dura lo obsoleto.
- **Sitio de documentación**: una página por red con la misma estructura (cómo crear la app, permisos,
  revisión, límites, lo que conviene saber), más la matriz de capacidades. También en inglés.
- **Apps de ejemplo**: conectar y publicar con FastAPI; una bandeja unificada.
- **Más marcos**: rutas para Django y Flask, además de Starlette.
- **Redes fuera del repositorio**: guía y plantilla para publicar una red como paquete propio, y un
  listado de las que existen.
- **Snapchat y Twitch**, o las que más se hayan pedido hasta ese momento.

## Lo que queda afuera

- **Programar publicaciones.** Cuándo publicar es de la app y de su cola; la librería publica cuando se lo
  piden y deja retomar una publicación en curso.
- **Interfaz de usuario.** Es una librería.
- **Raspar páginas.** Solo APIs oficiales; otra fuente entra como `ProfileLookup` en un paquete aparte.
