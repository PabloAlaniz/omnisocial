# Cómo se publica una versión

## El circuito

1. Cada commit en `main` sigue [Conventional Commits](https://www.conventionalcommits.org/es/).
2. El workflow [`release.yml`](../.github/workflows/release.yml) mantiene abierto un pull request
   con la próxima versión y el CHANGELOG, calculados a partir de esos commits.
3. Integrar ese pull request crea el tag y la versión en GitHub.
4. El mismo workflow arma el paquete desde ese tag (después de correr lint, tipos, contratos y tests) y
   lo publica en PyPI.

La versión se escribe en un solo lugar (`.release-please-manifest.json`) y la herramienta la copia a
`pyproject.toml` y `uv.lock`. Antes de la 1.0, un `feat` sube la versión menor y un `fix`, la de parche.

## Publicación de confianza

Ningún token de publicación está guardado en el repositorio: PyPI comprueba, con una credencial de corta
vida que emite GitHub, que quien publica es este workflow en este repositorio.

| Dónde | Qué |
|---|---|
| GitHub, *Settings → Actions → General* | Permitir que GitHub Actions cree pull requests; sin eso, release-please no puede abrir el de la versión |
| GitHub, *Settings → Environments* | El entorno `pypi`, sin aprobación manual |
| PyPI, *Publishing* | El publicador de confianza del proyecto `omnisocial`: este repositorio, workflow `release.yml`, entorno `pypi`. Antes de la primera versión se carga como publicador pendiente |
