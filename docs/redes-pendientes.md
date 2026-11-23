# Redes pendientes: YouTube, X y LinkedIn

Todavía no tienen adaptador. Esto junta lo que ya se sabe de cada una, aprendido en producción, para que
quien las sume no tropiece de nuevo con lo mismo. Cómo se suma una red: [nueva-red.md](nueva-red.md).

## YouTube (Data API v3)

**Capacidades posibles:** `login` (Google OAuth, `youtube.readonly`), `assets` (el canal), `content`
(videos), `comments` (lectura de hilos), `insights` (suscriptores; las series históricas son de YouTube
Analytics API) y `public_profiles` con una clave de API, sin mirador.

- **La cuota manda.** Son 10.000 unidades por día. `channels.list` cuesta 1; `search.list`, 100. Para los
  videos de un canal: `channels` → la playlist de subidas (`contentDetails.relatedPlaylists.uploads`) →
  `playlistItems` (1 unidad) → `videos` de a 50 ids. Nunca `search` para listar.
- **Buscar canales:** por id (`UC…`, hasta 50 separados por coma), por `forHandle` (`@marca`) o por
  `forUsername` (los nombres viejos). `search` solo como último recurso y solo ante un "no existe" real, nunca
  ante un error de red. Un `@handle` cuesta dos llamadas: resolver y traer.
- **Un 403 no siempre es la credencial.** Puede ser la cuota agotada o una clave inválida; lo dice
  `error.errors[0].reason`. En comentarios, un 403 suele querer decir que el video los tiene desactivados.
- **No compartir el cliente oficial de Google entre tareas concurrentes.** Reusa un socket que no es seguro
  entre hilos y corrompe el TLS ("SSL record layer failure"). Con httpx directo no pasa.
- **OAuth de Google:** al reconectar una cuenta, Google no vuelve a mandar el refresh token; hay que conservar
  el anterior. Un refresh vencido responde 400 `invalid_grant`, que es terminal.

## X (API v2)

**Capacidades posibles:** `login` (OAuth 2.0 con PKCE; `tweet.read`, `users.read`, `offline.access`),
`content`, `comments` (respuestas), `public_profiles` y búsqueda con el token de app (bearer).

- **Es paga y por créditos.** Un 402 quiere decir que la cuenta de la API se quedó sin créditos: no es un
  token muerto y no hay que invalidar la conexión. Leer respuestas exige el plan Basic o superior.
- **El refresh token rota**, como en TikTok: una conexión de X no puede ser compartida por dos sistemas con la
  misma app, porque cada uno invalida el refresh token del otro.
- **Las respuestas a un post** se buscan con `search/recent` y `conversation_id:<id> is:reply -from:<autor>`.
- Para listar posts propios conviene excluir retuits y respuestas, y pedir `public_metrics` y
  `conversation_id`.

## LinkedIn (Community Management API)

**Capacidades posibles:** `login` (OpenID: `openid`, `profile`, `email`), `assets` (las páginas de empresa
que la persona administra, `/v2/organizationAcls`), `content` y `comments`.

- **Las páginas de empresa necesitan la Community Management API**, que LinkedIn aprueba aparte. Sin eso solo
  hay login. El token dura 60 días y no tiene refresh en el plan básico.
- **La versión va en una cabecera** (`LinkedIn-Version: AAAAMM`) y LinkedIn retira las viejas: hay que fijarla
  en la configuración y actualizarla.
- **`/rest/posts?q=author` con `sortBy=LAST_MODIFIED`** pone primero los posts viejos que se editaron: no se
  puede cortar al encontrar uno fuera de la ventana; hay que filtrar por fecha de creación. Hay un tope de 1000.
- **El texto viene en formato "little text"**, con caracteres escapados y menciones con su propia sintaxis.
- **El parámetro `List(...)` de `/rest/images` se arma a mano**: las librerías HTTP lo codifican y LinkedIn
  no lo entiende.
- **Un 403 en imágenes no es un token muerto**: no hay que invalidar la conexión por eso.

## Común a todas

- **401/403 no siempre es un token muerto.** Cada red tiene sus códigos: solo los que significan "este token
  ya no sirve" invalidan la conexión; los de permiso faltante vuelven como `Refused(MISSING_PERMISSION)`.
- **Los links de imágenes vencen** (CDN firmados). Si hace falta mostrarlas después, se copian en el momento.
- **Guardar el id estable, no el nombre.** Los nombres de usuario cambian; el id numérico no.
