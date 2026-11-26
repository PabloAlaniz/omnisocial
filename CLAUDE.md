# omnisocial

Librería Python (3.11+) que habla con muchas redes sociales con las mismas reglas: un núcleo chico y un
adaptador por red. Todo en español rioplatense: docs, docstrings, mensajes de error, tests y commits.

## Antes de dar algo por terminado

```bash
uv run ruff format . && uv run ruff check . && uv run mypy && uv run lint-imports && uv run pytest
```

Todo eso corre en CI y falla el build. La cobertura de ramas tiene un piso de 98%.

## Arquitectura

Las dependencias apuntan hacia adentro: `entrypoints → adapters → application → domain`
([ADR 0001](docs/adr/0001-arquitectura-en-capas.md)). import-linter lo hace cumplir.

- `domain`: Python puro, sin dependencias externas.
- `application`: casos de uso y puertos (`application/ports.py`). No importa paquetes opcionales.
- `adapters`: cada red en `adapters/providers/<red>/`; las redes no se importan entre sí.
- El reloj, los ids, el azar y la configuración entran por puertos (`Clock`, `IdGenerator`,
  `SecretGenerator`) o por parámetros. Nunca `datetime.now()`, `uuid4()` ni `os.environ` en el núcleo.
- Cada adaptador hereda del puerto que implementa y marca sus métodos con `@override`
  (de `typing_extensions`).

## Diseño

Las reglas y sus porqués están en el [ADR 0004](docs/adr/0004-reglas-estaticas-de-diseno.md). En corto:

- Funciones chicas: hay topes de complejidad, ramas, sentencias y argumentos (los números, en
  `[tool.ruff]` de `pyproject.toml`). Si una función se pasa, se parte por responsabilidad; no se sube el tope.
- Sin booleanos posicionales, sin `Any` en las firmas, fechas siempre con zona horaria.
- Sin `# noqa` ni `# type: ignore` sin código y sin una razón en el mismo comentario. Preferí arreglar.
- Las reglas preview de ruff se suman una por una en `pyproject.toml`, nunca todas juntas.

## Redes, commits y versiones

- Red nueva: `uv run python scripts/nueva_red.py <red> --nombre "<Nombre>"` y la lista de
  [CONTRIBUTING.md](CONTRIBUTING.md). Ningún test llama a la red real: respuestas grabadas, sin tokens.
- Commits en [Conventional Commits](https://www.conventionalcommits.org/es/), en español. Un cambio
  incompatible lleva `!`.
- Una decisión de diseño nueva va en un ADR en `docs/adr/`.
