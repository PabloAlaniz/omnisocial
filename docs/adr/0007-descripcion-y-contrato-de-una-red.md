# 0007. Descripción y contrato de una red

- **Estado:** Aceptada. Actualizada por [0012](0012-consultas-auxiliares-y-ritmo.md) y [0014](0014-operar-en-produccion.md), que suman el ritmo por red.
- **Fecha:** 2026-11-24
- **Relacionadas:** [0002](0002-capacidades-por-red.md), [0004](0004-reglas-estaticas-de-diseno.md)

## Contexto

Con dos redes, sumar la tercera era copiar a mano lo que hacía Meta: el cliente de OAuth, la traducción de
errores, las pruebas de punta a punta. Cada copia podía apartarse sin que nadie lo notara, y lo que una red
ya había aprendido (que un 403 no siempre es un token muerto, por ejemplo) no llegaba a la siguiente.

Para tener muchas redes, sumar una tiene que ser barato para quien no conoce el núcleo, y revisarla tiene
que ser barato para quien lo mantiene.

## Decisión

**Lo que se puede decir con datos, se declara.** Cada red trae un `NetworkSpec` (`spec.py`):

- Sus capacidades y qué habilita cada tipo de activo. De ahí sale la matriz de capacidades.
- Su `ErrorTable`: qué quiere decir cada código de error. El núcleo tiene siete clases (`ErrorKind`) y
  decide lo mismo para todas las redes: un token muerto invalida la conexión; un permiso faltante, un
  límite de uso o la cuota agotada vuelven como negativa y la conexión sigue sana; lo demás es una
  excepción. Un 401 o un 403 sin código conocido **no** es un token muerto.
- Su `OAuthSpec`, si el OAuth es el estándar. Con eso `StandardOAuth` hace el resto y la red solo escribe
  cómo se lee la identidad. Una red con un OAuth propio (Meta, con su canje por un token largo) sigue
  trayendo su `OAuthClient`.

**Lo que el núcleo espera, se prueba igual en todas.** `omnisocial.testing` trae el contrato común: la
descripción dice la verdad, conectar guarda la conexión y sus activos, cada clase de error se traduce
igual en toda capacidad y un aviso sin firma no pasa. Corre contra respuestas grabadas, por los casos de
uso, y viaja en el paquete para que lo usen las redes externas.

**Ningún archivo central se edita por red.** Las pruebas de arquitectura, la matriz y el contrato de
independencia encuentran las redes solas. `scripts/nueva_red.py` crea el esqueleto y CI comprueba que el
esqueleto recién creado pasa todo.

## Lo que queda afuera

- Las cabeceras de límite de uso y la concurrencia por red. Llegaron después: el ritmo por red en el
  [ADR 0012](0012-consultas-auxiliares-y-ritmo.md) y su reparto entre procesos en el
  [ADR 0014](0014-operar-en-produccion.md).
- La descripción no reemplaza a los adaptadores de lectura: listar publicaciones o leer métricas sigue
  siendo código, porque ahí cada red es distinta de verdad.

## Consecuencias

- Una red de solo login son unas pocas decenas de líneas, casi todas datos.
- Clasificar mal un error se corrige en una línea de la tabla, y el contrato lo detecta.
- El contrato es API pública: cambiarlo puede romper las pruebas de un paquete externo, así que se versiona
  con el mismo cuidado que los puertos.
