# 0005. Perfiles públicos y mirador

- **Estado:** Aceptada.
- **Fecha:** 2026-11-23
- **Relacionadas:** [0002](0002-capacidades-por-red.md)

## Contexto

Además de administrar cuentas propias, hace falta mirar cuentas ajenas: cuántos seguidores tiene una marca,
cuántas publicaciones, qué dice su bio. Cada red lo resuelve distinto:

- Instagram solo muestra cuentas profesionales ajenas a través de una cuenta profesional propia
  (`business_discovery`).
- Otras redes lo hacen con una credencial de la app (una clave de API o un token de app), sin cuenta propia.
- Hay fuentes que no son APIs oficiales y que no corresponde publicar en este paquete.

Además, la gente pega lo que tiene a mano: `@marca`, `instagram.com/marca/`, `youtube.com/channel/UC…`.

## Decisión

- **Una capacidad aparte, `PUBLIC_PROFILES`,** con el puerto `ProfileLookup`. No se mezcla con `ASSETS`:
  un activo es algo que se administra con un token; un perfil público es algo que solo se mira.
- **El nombre se normaliza en el dominio** (`parse_handle`), igual para todas las redes. La identidad de un
  perfil es su id en la red (`PublicProfile.external_id`), no el nombre, que puede cambiar.
- **El [mirador](../referencia/glosario.md) es explícito.** Cada red declara qué tipos de activo propio sirven para mirar
  (`viewer_kinds`). Si hace falta y no se pasa uno que sirva, el caso de uso devuelve
  `Refused(VIEWER_REQUIRED)` sin llamar a la red. Si la red rechaza el token del mirador, su conexión queda
  inválida como en cualquier otra operación.
- **Las fuentes no oficiales quedan afuera del paquete.** Como cualquier red, un adaptador privado puede
  implementar `ProfileLookup` y registrarse por entry point.

## Consecuencias

- Las páginas de Facebook ajenas no se cubren: necesitan "Page Public Metadata Access", que exige revisión.
- Un perfil público no tiene métricas históricas: es una foto del momento. Guardar la serie es de la app.

## Alternativas descartadas

- **Mezclar los perfiles con los activos (`ASSETS`).** Un activo se administra con un token; un perfil
  público solo se mira.
