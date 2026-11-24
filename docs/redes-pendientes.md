# Redes pendientes: X y LinkedIn

Todavía no tienen adaptador. Esto junta lo que ya se sabe de cada una, aprendido en producción, para que
quien las sume no tropiece de nuevo con lo mismo. Cómo se suma una red: [nueva-red.md](nueva-red.md).

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
