# 0004. Reglas estáticas de diseño

- **Estado:** Aceptada.
- **Fecha:** 2026-11-23
- **Relacionadas:** [0001](0001-arquitectura-en-capas.md), [0002](0002-capacidades-por-red.md)

## Contexto

La arquitectura en capas (ADR 0001) y las capacidades por red (ADR 0002) son acuerdos. Si nada los hace
cumplir, se erosionan de a un atajo por vez: un `datetime.now()` en un caso de uso, una función que crece
hasta decidir cinco cosas, un adaptador que deja de coincidir con su puerto sin que nadie lo note.

## Decisión

Cuatro herramientas, cada una con su parte. Todas corren en CI y fallan el build.

### import-linter: las dependencias entre capas

Las capas dependen hacia adentro, las redes no se conocen entre sí, el núcleo no importa paquetes
opcionales, el dominio es Python puro (ni siquiera `omniwebhook`) y la infraestructura compartida
(`adapters.http`, `adapters.crypto`, `adapters.otel`) no conoce redes ni almacenes. Ver `[tool.importlinter]`.

### ruff: lo que se ve en el código

Las reglas que hacen cumplir el diseño, no el estilo:

- **Nada de efectos sueltos.** El reloj, los ids, el azar y las variables de entorno no se tocan directo:
  van por `Clock`, `IdGenerator` o `SecretGenerator`, o se inyectan. Solo `adapters/system.py` y el
  adaptador de cifrado están exentos.
- **Funciones chicas.** Topes de complejidad, ramas, returns, sentencias y argumentos por función. Más
  dependencias que eso suele ser una clase que hace demasiado; la excepción es la
  [raíz de composición](../referencia/glosario.md) (`entrypoints/hub.py`).
- **Clases y métodos con una sola tarea.** Una clase con demasiados métodos públicos, una función con
  demasiadas variables o una condición con demasiadas partes hace o dice demasiado. Un método que no usa
  `self` es una función o un `@staticmethod` (salvo en el kit de pruebas, donde son ganchos que cada red
  cambia).
- **Sin atajos que esconden errores**: argumentos sin usar, booleanos posicionales, privados ajenos,
  excepciones atrapadas de más, fechas sin zona, `Any` en las firmas, números mágicos, código comentado.

Las reglas y sus umbrales exactos están en `[tool.ruff]` de
[`pyproject.toml`](https://github.com/PabloAlaniz/omnisocial/blob/main/pyproject.toml): ese es el lugar que
manda, y no se repite acá para que no quede viejo.

Las reglas en preview de ruff entran una por una (`explicit-preview-rules`), nunca en bloque.

En los tests se relajan solo las reglas que chocan con la forma de un test (literales esperados, dobles que
no usan todos los argumentos).

### mypy: los contratos

- `strict`.
- `explicit-override`: cada adaptador **hereda del puerto que implementa** y marca sus métodos con
  `@override` (de `typing_extensions`, para soportar Python 3.11). Si un puerto cambia, mypy marca cada
  adaptador que quedó desalineado en la definición de la clase, no en un uso perdido. Si un adaptador
  declara un método que el puerto ya no tiene, también falla.
- `ignore-without-code`, `redundant-expr`, `truthy-bool`, `possibly-undefined`.

### pytest: la cobertura

La cobertura de ramas tiene un piso de 98%. Lo que se prueba contra PostgreSQL de verdad queda afuera de la
cuenta y corre en su propio job.

## Consecuencias

- `typing_extensions` pasa a ser dependencia, solo por `override`.
- Los dobles de los tests siguen siendo estructurales (no heredan): un doble que no coincide con su puerto
  lo marca mypy en el punto donde se usa.
- Adoptarlas forzó a partir algunos casos de uso que decidían varias cosas a la vez (`GetValidToken`,
  `CompleteAuthorization`, `StartAuthorization`).
- Al bajar los topes de complejidad, ramas y sentencias se partieron el publicador y el armado de mensajes
  de Discord, la subida de YouTube, la lectura de métricas de Meta y la validación de `NetworkSpec`.
- No se aplican docstrings obligatorios (`D`), imports solo de tipos (`TC`) ni mensajes de excepción en
  variable (`EM`): el costo en ruido supera lo que protegen en una librería de este tamaño.
