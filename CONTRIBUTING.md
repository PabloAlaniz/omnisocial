# Contribuir

Gracias por querer sumar. Lo que más ayuda:

- **Una red nueva**, o una capacidad que le falta a una red que ya está.
- **Un error en una red**: una respuesta de la API que el adaptador traduce mal, un código de error mal
  clasificado, un límite que cambió.
- **Lo que aprendiste de una API** y no está en la documentación oficial. Va en la página de la red, en
  `docs/`.
- **Documentación**: un ejemplo que no anda, algo que no se entiende. El sitio se arma desde `docs/` con
  MkDocs; la portada sale del README.

Antes de un cambio grande al núcleo (un puerto nuevo, un cambio en el dominio), abrí un issue para
conversarlo: el núcleo es chico a propósito.

## Preparar el entorno

```bash
uv sync
uv run pytest                 # unitarios, con cobertura
uv run pytest -m integration  # contra PostgreSQL (OMNISOCIAL_PG_URL)
uv run ruff format . && uv run ruff check . && uv run mypy && uv run lint-imports
uv run python scripts/matriz.py   # la matriz de capacidades del README
uv run python scripts/sitio.py    # la portada del sitio, que sale del README
uv run --group docs mkdocs serve  # el sitio de documentación, en http://127.0.0.1:8000
```

Todo eso corre en CI y tiene que pasar. Las reglas de diseño (capas, funciones chicas, nada de leer el reloj
o el entorno fuera de los adaptadores de sistema) están en el
[ADR 0004](docs/adr/0004-reglas-estaticas-de-diseno.md).

## Sumar una red

```bash
uv run python scripts/nueva_red.py mired --nombre "Mi Red"
```

Crea una red de solo login que ya pasa el contrato común, con lo que falta marcado como `PENDIENTE`. El
paso a paso, y la lista de lo que tiene que tener una red para estar terminada, están en
[Sumar una red](docs/nueva-red.md). Lo que pide cada capacidad, en
[Capacidades de una red](docs/nueva-red-capacidades.md).

Si la red necesita una biblioteca pesada o tiene su propio ritmo de versiones, puede vivir en un paquete
aparte y registrarse por entry point. El contrato y el transporte falso viajan en `omnisocial.testing` para
eso.

## Corregir un error en una red

Lo más útil es la respuesta de la API que lo provoca. Sumala como caso de prueba (sin tokens ni datos
personales) y después corregí el adaptador. Si el problema es que un error se clasifica mal (una conexión
sana que queda inválida, por ejemplo), el arreglo suele ser una línea en la tabla `ERRORS` de la red.

## Commits y versiones

Los mensajes siguen [Conventional Commits](https://www.conventionalcommits.org/es/), en español:
`feat(tiktok): …`, `fix(meta): …`, `docs: …`. De ahí salen el número de versión y el CHANGELOG
([cómo se publica](docs/versiones.md)). Un cambio incompatible lleva `!` y explica cómo migrar.

## Seguridad

Una vulnerabilidad no va en un issue público: ver [SECURITY.md](SECURITY.md). En issues, pruebas y
documentación no van tokens, secretos ni datos de cuentas reales.
