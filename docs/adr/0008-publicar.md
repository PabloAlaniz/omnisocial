# 0008. Publicar

## Contexto

Publicar es distinto de leer en tres cosas. No se puede repetir: un reintento duplica la publicación.
Muchas redes lo hacen en etapas: reciben el pedido, procesan los medios y publican después. Y cada red
acepta cosas distintas, que conviene saber antes de llamarla.

## Decisión

**Los límites son datos.** Cada tipo de activo declara un `PublishLimits` en la descripción de la red: largo
del texto y cómo se cuenta, cantidad y tipo de medios, si admite link, primer comentario o borrado. El
núcleo valida el borrador con eso y devuelve todos los problemas juntos, sin llamar a la red.

**Una publicación es un registro con estado**, guardado en un `PublicationRepository`:

| Estado | Qué significa |
|--------|---------------|
| `STARTED` | Se reservó y se llamó a la red, pero no quedó registrado qué respondió. Está en duda. |
| `PENDING` | La red la está procesando. Se retoma con `check_publication`. |
| `PUBLISHED` | Salió. |
| `PUBLISHED_WITH_ERROR` | Salió, y un paso posterior falló. No hay que repetirla. |
| `FAILED` | La red la rechazó mientras la procesaba. No salió. |

**Ante la duda, no se repite.** Antes de llamar a la red se reserva la publicación. Según lo que pase:

- La red responde: se guarda el resultado.
- La red dice con certeza que no salió (permiso faltante, límite de uso, contenido rechazado, token
  muerto): vuelve una negativa y la reserva se libera, así la misma clave sirve para reintentar.
- No se sabe (la red no respondió, un error desconocido): la excepción sigue y la reserva queda `STARTED`.
  Repetir el pedido con la misma clave la devuelve así. Publicar dos veces es peor que avisar que hay que
  mirar.

**La clave de idempotencia es de quien llama** y vale por activo. Sin clave, cada pedido es una publicación
nueva.

**Los medios van por URL.** La red los descarga; la librería no. Por eso alcanza con exigir que la URL sea
https y pública, y no hay descargas propias que proteger. Las redes que solo aceptan archivos suman la
subida por partes cuando lleguen.

**El adaptador nunca lanza una excepción después de haber publicado.** Devuelve `PUBLISHED_WITH_ERROR`. Es
la regla que evita los duplicados.

## Lo que queda afuera

- **Programar.** Cuándo publicar es de la app y de su cola.
- **Publicar lo mismo en varias redes de una vez.** Es un bucle de quien llama, con un resultado por activo:
  cada red puede aceptar o rechazar por su cuenta.
- **Guardar el borrador.** El registro guarda el estado y el id en la red, no el contenido.

## Consecuencias

- Los activos guardados antes de esta versión no tienen la capacidad `publishing`: hay que volver a
  sincronizarlos. Y publicar pide permisos propios, que no se suman solos a los de conexión.
- `Omnisocial.build` recibe `publications`. Si falta, las publicaciones quedan en memoria.
- Una publicación `STARTED` vieja no se resuelve sola: la app decide si la da por perdida.
