## Qué cambia y por qué

## Cómo se probó

- [ ] `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run lint-imports`
- [ ] `uv run pytest`
- [ ] Las respuestas grabadas no traen tokens, secretos ni datos de cuentas reales.

## Si toca una red

- [ ] La descripción (`spec.py`) dice lo que el proveedor hace, y la matriz del README está al día
      (`uv run python scripts/matriz.py`).
- [ ] Pasa el contrato común (`test_contract.py`).
- [ ] Los códigos de error nuevos están en la tabla `ERRORS`, con un comentario que dice qué significan.
- [ ] La página de la red en `docs/` cuenta lo que cambió o lo que se aprendió.
- [ ] No suma dependencias obligatorias.

Si es una red nueva, la lista completa está en [CONTRIBUTING.md](../CONTRIBUTING.md#sumar-una-red).
