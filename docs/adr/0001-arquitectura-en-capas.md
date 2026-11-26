# 0001. Arquitectura en capas

- **Estado:** Aceptada.
- **Fecha:** 2026-11-23
- **Relacionadas:** [0002](0002-capacidades-por-red.md), [0004](0004-reglas-estaticas-de-diseno.md), [0006](0006-cada-red-paga-lo-suyo.md)

## Contexto

La librería tiene que servir para varias redes, varias bases y varios frameworks web. Si las reglas
(cuándo un token deja de servir, cuándo se puede responder un mensaje, a dónde se puede volver después de
autorizar) quedan mezcladas con las llamadas HTTP de una red, cada red nueva las vuelve a escribir y cada
una las escribe un poco distinto.

## Decisión

Cuatro capas. Las dependencias apuntan hacia adentro:

```
entrypoints → adapters → application → domain
```

- **domain:** entidades y reglas puras. Sin entrada ni salida, sin dependencias externas.
- **application:** casos de uso y puertos (`Protocol`). Los casos de uso no conocen ninguna red: piden el
  proveedor al registro y usan sus capacidades.
- **adapters:** las redes (`providers/meta`), los almacenes (`stores`), el transporte HTTP y el cifrado.
- **entrypoints:** la fachada `Omnisocial` que arma todo y las rutas de Starlette.

`import-linter` lo hace cumplir en cada corrida de CI (`[tool.importlinter]` en `pyproject.toml`), con tres
contratos: las capas, la independencia entre redes y almacenes, y que el núcleo no importe paquetes
opcionales.

## Consecuencias

- Los mismos casos de uso se prueban con una red falsa y con Meta. Es la prueba de que el núcleo es común.
- Los paquetes opcionales (httpx, psycopg, cryptography, starlette) solo se importan en su adaptador. Quien
  no los instala no los carga.
- Hay más archivos que en un cliente directo de la API. Es el precio de no repetir las reglas por red.

## Alternativas descartadas

- **Un cliente directo por red**, sin capas: menos archivos, pero cada red repite las reglas a su manera.
