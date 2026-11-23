# 0004. Reglas estáticas de diseño

## Contexto

La arquitectura en capas (ADR 0001) y las capacidades por red (ADR 0002) son acuerdos. Si nada los hace
cumplir, se erosionan de a un atajo por vez: un `datetime.now()` en un caso de uso, una función que crece
hasta decidir cinco cosas, un adaptador que deja de coincidir con su puerto sin que nadie lo note.

## Decisión

Tres herramientas, cada una con su parte. Todas corren en CI y fallan el build.

### import-linter: las dependencias entre capas

Las capas dependen hacia adentro, las redes no se conocen entre sí, y el núcleo no importa paquetes
opcionales. Ver `[tool.importlinter]`.

### ruff: lo que se ve en el código

| Regla | Para qué |
|-------|----------|
| `TID251` (banned-api) | El reloj, los ids, el azar y las variables de entorno no se tocan directo: van por `Clock`, `IdGenerator`, `SecretGenerator` o se inyectan. Solo `adapters/system.py` y el adaptador de cifrado están exentos. |
| `C90`, `PLR0911/0912/0915` | Responsabilidad única: complejidad ≤ 8, ≤ 8 ramas, ≤ 5 returns, ≤ 30 sentencias por función. |
| `PLR0913`, `PLR0917` | ≤ 6 argumentos y ≤ 4 posicionales. Más dependencias que eso suele ser una clase que hace demasiado; la excepción es la raíz de composición (`entrypoints/hub.py`). |
| `ARG` | Sin argumentos sin usar. Un adaptador que no usa un argumento del puerto lo dice con `@override`. |
| `FBT` | Sin booleanos posicionales: `set_hidden(hidden=True)`, nunca `set_hidden(True)`. |
| `SLF` | Nadie toca los privados de otro objeto. |
| `BLE`, `TRY` | No se atrapa todo; las excepciones se re-lanzan con su causa. |
| `DTZ` | Toda fecha lleva zona horaria. |
| `ANN401` | Sin `Any` en las firmas. |
| `PLR2004` | Sin números mágicos: las reglas tienen nombre. |
| `ERA` | Sin código comentado. |

En los tests se relajan solo las reglas que chocan con la forma de un test (literales esperados, dobles que
no usan todos los argumentos).

### mypy: los contratos

- `strict`.
- `explicit-override`: cada adaptador **hereda del puerto que implementa** y marca sus métodos con
  `@override` (de `typing_extensions`, para soportar Python 3.11). Si un puerto cambia, mypy marca cada
  adaptador que quedó desalineado en la definición de la clase, no en un uso perdido. Si un adaptador
  declara un método que el puerto ya no tiene, también falla.
- `ignore-without-code`, `redundant-expr`, `truthy-bool`, `possibly-undefined`.

## Consecuencias

- `typing_extensions` pasa a ser dependencia, solo por `override`.
- Los dobles de los tests siguen siendo estructurales (no heredan): un doble que no coincide con su puerto
  lo marca mypy en el punto donde se usa.
- Refactors que estas reglas forzaron al adoptarlas: `GetValidToken` separa decidir la renovación de
  guardarla, `CompleteAuthorization` separa validar el pedido de canjear el código, `StartAuthorization`
  recibe `AuthorizationSettings` en vez de tres parámetros sueltos, y `MetaInsightsReader.catalog` dejó de
  pisar una propiedad de solo lectura del puerto.
