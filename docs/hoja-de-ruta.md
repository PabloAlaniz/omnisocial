# Hoja de ruta

El objetivo es que omnisocial sea la referencia para conectar redes sociales desde Python: muchas redes,
las mismas reglas, y que sumar una red nueva sea barato para quien no conoce el núcleo.

## Qué falta para la 1.0

La versión 1.0 promete estabilidad. Todavía no se declara porque todas las redes son
[experimentales](niveles-de-soporte.md): están probadas contra respuestas simuladas, no contra la API
real, y probarlas en vivo puede obligar a cambiar algún puerto. La librería sigue en 0.x hasta que:

1. Las redes que se usan en producción pasan a `verificada` o a `comunitaria`, con sus
   [pruebas en vivo](pruebas-en-vivo.md) encendidas.
2. Lo que esas pruebas obliguen a cambiar en los puertos ya se cambió.
3. La promesa de estabilidad está escrita (qué es API pública, cómo se anuncia un cambio, cuánto dura lo
   obsoleto) y hay una prueba que falla si la API pública cambia sin declararlo.

## Lo próximo

En este orden:

- **Apps de ejemplo**: conectar y publicar con FastAPI; una bandeja unificada.
- **Más marcos**: rutas para Django y Flask, además de Starlette.
- **Referencia de la API** generada desde el código.
- **Redes fuera del repositorio**: guía y plantilla para publicar una red como paquete propio, y un
  listado de las que existen.
- **El sitio en inglés.** Hoy está en español, como el código y sus mensajes.
- **Redes nuevas** (Snapchat, Twitch u otras), según los pedidos que lleguen.

## Pendiente en las redes que ya están

Lo que quedó afuera al integrar cada red, porque no hacía falta para lo esencial o porque conviene
resolverlo con una cuenta real:

| Red | Pendiente |
|---|---|
| YouTube | Avisos de videos nuevos (XML con firma SHA-1), series históricas de YouTube Analytics, miniatura propia, primer comentario |
| LinkedIn | Contadores por publicación; avisar cuando la versión de la API está por retirarse (hoy lo dice el error) |
| X | Mensajes privados, avisos de actividad |
| Threads | Avisos |
| Instagram con login propio | Mensajes y avisos (no está claro con qué secreto se firman) |
| Bluesky | OAuth (hoy, contraseñas de aplicación), menciones, ocultar respuestas |
| Mastodon y Pixelfed | Leer los límites de cada servidor (hoy, los de un servidor por defecto) |
| Reddit | Imágenes y videos, mensajes, perfiles públicos |
| Google Business Profile | Avisos de reseñas nuevas (solo salen por Cloud Pub/Sub) |
| WhatsApp Business | Bajar adjuntos, crear plantillas, dar de alta un número |
| Discord | Recibir mensajes (solo se entregan por una conexión permanente) |

Y en el núcleo: compartir entre procesos el tope de pedidos simultáneos, y guardar los tokens que rotan
durante las pruebas en vivo.

## Lo que queda afuera

- **Programar publicaciones.** Cuándo publicar es de la app y de su cola; la librería publica cuando se lo
  piden y deja retomar una publicación en curso.
- **Guardar la bandeja.** Qué se leyó y qué se respondió es de la app.
- **Interfaz de usuario.** Es una librería.
- **Raspar páginas.** Solo APIs oficiales; otra fuente entra como `ProfileLookup` en un paquete aparte.

## Lo hecho

Al empezar había dos redes (Meta y TikTok), ocho capacidades y ninguna publicaba. Se trabajó en diez
etapas; el detalle de cada decisión está en su ADR.

| Etapa | Qué trajo | Decisión |
|---|---|---|
| 1 | Descripción declarativa de cada red, contrato común, tabla de errores, matriz generada, generador de esqueleto | [ADR 0007](adr/0007-descripcion-y-contrato-de-una-red.md) |
| 2 | Publicar: borrador común, validación previa, etapas, idempotencia. Meta y TikTok publican | [ADR 0008](adr/0008-publicar.md) |
| 3 | YouTube: subida por partes y presupuesto de cuota | [ADR 0009](adr/0009-cuota-y-subida-por-partes.md) |
| 4 | LinkedIn y X: hilos, tokens de renovación que rotan, variantes de una red | — |
| 5 | Threads e Instagram con login propio; renovación anticipada y avisos de salud de las conexiones | [ADR 0010](adr/0010-salud-de-las-conexiones.md) |
| 6 | Bluesky, Mastodon y Pixelfed: redes federadas y conexión por credencial | [ADR 0011](adr/0011-redes-federadas-y-credenciales.md) |
| 7 | Pinterest, Reddit y Google Business Profile: consultas auxiliares y ritmo por red | [ADR 0012](adr/0012-consultas-auxiliares-y-ritmo.md) |
| 8 | WhatsApp Business, Telegram y Discord: mensajes sin historial y bandeja unificada | [ADR 0013](adr/0013-mensajes-sin-historial-y-bandeja.md) |
| 9 | Operar en producción: observabilidad, límites compartidos, niveles de soporte, pruebas en vivo, vigilancia de versiones, cadena de suministro | [ADR 0014](adr/0014-operar-en-produccion.md) |
| 10 | Este sitio de documentación | — |

Lo que cambió en cada versión está en el
[CHANGELOG](https://github.com/PabloAlaniz/omnisocial/blob/main/CHANGELOG.md).
