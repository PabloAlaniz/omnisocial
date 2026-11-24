# 0011. Redes federadas y conexión por credencial

## Contexto

Hasta acá todas las redes se conectaban igual: una app registrada de antemano, un diálogo de OAuth y un
servidor conocido. Bluesky y Mastodon rompen las dos cosas. En Bluesky no hay app que registrar: la
persona genera una contraseña de aplicación. En Mastodon hay miles de servidores, cada uno con su propia
app, y la persona dice en cuál está su cuenta.

## Decisión

**Tres formas de conectar, un mismo resultado.** Un proveedor trae una de las tres: `oauth` (el diálogo de
siempre), `server_oauth` (el diálogo, en el servidor que elige la persona) o `credentials` (una credencial
que se cambia por un token). Las tres terminan en una conexión con su token, y las tres renuevan y revocan
por el mismo camino (`Provider.refresher`): el resto del núcleo no distingue cómo se conectó.

**El servidor viaja con el token.** `Token.server` dice a qué servidor pertenece, y se guarda cifrado con
él. Los adaptadores reciben lo mismo que antes (el activo y el token) y saben a dónde hablar. No hizo falta
cambiar ningún puerto de lectura ni de publicación.

**El servidor se valida en el dominio.** Lo escribe una persona y la librería después le hace pedidos: es
la superficie clásica para hacerle pedir cosas a una red interna. `normalize_server` acepta solo nombres de
dominio públicos (ni direcciones, ni puertos, ni `http://`, ni nombres internos), y `StartAuthorization` lo
aplica antes de que el adaptador haga nada. Lo que la librería no puede saber es a dónde resuelve ese
nombre: eso queda documentado como responsabilidad del despliegue.

**Una app por servidor, guardada.** `ServerAppStore` guarda la clave y el secreto que dio cada servidor,
con el secreto cifrado. Registrar es poner-si-no-está: dos procesos que registran a la vez terminan usando
la misma app.

**La credencial no se guarda.** `connect_with_credentials` la cambia por un token y la descarta. El
adaptador declara qué datos pedir y cuáles son secretos, para que una interfaz arme el formulario.

## Lo que queda afuera

- **El OAuth de Bluesky.** Existe y es lo que Bluesky recomienda para apps con login propio, pero es
  bastante distinto del resto (tokens atados a una clave, metadatos del cliente publicados en una URL).
  Las contraseñas de aplicación siguen soportadas y alcanzan para conectar una cuenta.
- **Leer la configuración de cada servidor.** Los límites son los de un servidor por defecto.
- **Descubrir el servidor desde el nombre.** `parse_handle` saca el servidor de `@ana@mastodon.social`; la
  app decide si lo pregunta aparte.

## Consecuencias

- `create_schema` crea la tabla `omnisocial_server_apps`.
- Dos redes pueden vivir en un mismo paquete cuando comparten protocolo (Mastodon y Pixelfed), como ya
  pasaba con Instagram y Meta.
- El contrato común conecta de las tres formas: el arnés de cada red dice su servidor o su credencial de
  prueba.
