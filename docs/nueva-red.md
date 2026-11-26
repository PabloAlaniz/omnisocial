# Sumar una red

Paso a paso para sumar una red de solo login, que es lo mínimo válido, y dejarla lista para sumarle
capacidades. Lo que cada capacidad pide (publicar, mensajes, ritmo, perfiles) está en
[Capacidades de una red](nueva-red-capacidades.md).

Una red es un `Provider` con las capacidades que implementa y una descripción (`NetworkSpec`) que dice
cuáles son. Todo lo que un adaptador necesita se importa de `omnisocial.network`: los puertos, la
descripción, el transporte y los errores.

## 1. Crear el esqueleto

```bash
uv run python scripts/nueva_red.py mired --nombre "Mi Red"
```

Crea:

- el adaptador, en `src/omnisocial/adapters/providers/mired/`;
- su módulo público, `src/omnisocial/mired.py` (`omnisocial.mired`);
- la prueba de contrato, en `tests/adapters/mired/test_contract.py`;
- la página de documentación, `docs/mired.md`.

Lo que hay que completar está marcado con `PENDIENTE`:

```bash
grep -rn PENDIENTE src tests docs
```

!!! warning "El esqueleto pasa el contrato, no toda la suite"
    `uv run pytest tests/adapters/mired` pasa desde el primer momento. `uv run pytest` completo falla hasta
    hacer el [paso 5](#5-documentarla-y-sumarla-al-sitio), porque la página nueva no está en el índice del
    sitio y la matriz del README no tiene la red.

## 2. Describirla (`spec.py`)

Lo que se puede decir con datos no se programa
([ADR 0007](adr/0007-descripcion-y-contrato-de-una-red.md)):

```python
ERRORS = ErrorTable(
    codes={
        "access_token_invalid": ErrorKind.TOKEN_DEAD,
        "scope_not_authorized": ErrorKind.MISSING_PERMISSION,
        "rate_limit_exceeded": ErrorKind.RATE_LIMITED,
    }
)

SPEC = NetworkSpec(
    id=MIRED,
    name="Mi Red",
    capabilities=frozenset({Capability.LOGIN}),  # cada capacidad se suma cuando el proveedor la trae
    errors=ERRORS,
    oauth=OAuthSpec(authorize_url=AUTHORIZE_URL, token_url=f"{API_BASE}/oauth/token"),
    docs="docs/mired.md",
)
```

Es lo que deja el esqueleto. Con tipos de activo, van en `assets`: qué capacidades habilita cada uno.

**La tabla de errores** es lo que más cuida a quien usa la librería. El cliente de la red lanza
`ERRORS.error(...)` y el núcleo decide lo mismo para todas las redes (ver
[Negativas y errores](referencia/negativas.md#excepciones)). Solo es `TOKEN_DEAD` lo que la red documenta
como "este token ya no sirve": un 401 o un 403 sin código conocido no lo es.

**El OAuth**, si es el estándar, se declara en `OAuthSpec` y lo atiende `StandardOAuth`: la red solo
escribe un `IdentityReader`. Se puede declarar el separador de permisos, si usa PKCE, el nombre de los
parámetros de la app, parámetros fijos de la URL de autorización y si el token de renovación rota. Si el
flujo es distinto de verdad (un canje extra, como en Meta), la red trae su propio `OAuthClient`.

Si la red no conecta con el diálogo de siempre, ver
[otras formas de conectar](nueva-red-capacidades.md#otras-formas-de-conectar).

**El nivel de soporte y la versión de API** también van acá:

```python
SPEC = NetworkSpec(
    ...,
    api=ApiPin("v5", reviewed=date(2026, 11, 24), changelog="https://red.ejemplo.com/changelog"),
)
```

Una red nueva es `experimental` (el valor por defecto) hasta que alguien la use con cuentas reales.
`reviewed` es la última vez que se comparó el adaptador con la documentación de esa versión: una tarea
avisa cuando pasan seis meses. Ver [niveles de soporte](niveles-de-soporte.md).

## 3. Sumarle capacidades

Cada capacidad es un puerto. Al sumar una:

1. El adaptador hereda del puerto y marca sus métodos con `@override`.
2. El componente va al `Provider` (`publisher=...`, `comments=...`).
3. La capacidad va a `SPEC.capabilities` y al tipo de activo que la habilita.

El contrato falla si una de las partes quedó atrás. La lista de puertos y lo que el núcleo espera de cada
uno están en [Capacidades de una red](nueva-red-capacidades.md).

## 4. Probarla

**El contrato común** (`tests/adapters/mired/test_contract.py`) es lo primero que tiene que pasar. La red
arma un [arnés](referencia/glosario.md) (`NetworkHarness`): cómo se construye el proveedor, qué responde
la red cuando alguien conecta una cuenta y cómo dice cada clase de error.

```python
from omnisocial.testing import NetworkHarness, ProviderContract


class TestMiRedCumpleElContrato(ProviderContract):
    def harness(self) -> NetworkHarness:
        return MiRedHarness()
```

Con eso se comprueba, pasando por los casos de uso, que:

- La descripción dice la verdad: las capacidades declaradas son las del proveedor, y los activos
  descubiertos son los declarados.
- Cada adaptador hereda de su puerto.
- La URL de autorización lleva el `state`, la URL de retorno, los permisos y PKCE si corresponde.
- Conectar guarda la conexión y sus activos, y los tokens no aparecen en `repr`.
- Cada clase de error se traduce igual en toda capacidad y en todo tipo de activo, y solo un token muerto
  invalida la conexión.
- Un borrador que no entra en un activo se rechaza sin llamar a la red.
- Un aviso sin firma no llega a la app.
- Nada de lo que se observa de la red lleva un secreto.

**Después, la traducción de cada capacidad**, con respuestas copiadas de la API real (sin tokens ni datos
personales) y `FakeTransport`. Ver `tests/adapters/tiktok/`. Ningún test llama a la red.

## 5. Documentarla y sumarla al sitio

La página `docs/mired.md` sale de la plantilla con sus secciones. Un test comprueba la estructura y que
enlace a los [niveles de soporte](niveles-de-soporte.md). La sección que más vale es "Lo que conviene
saber": lo que no está en la documentación oficial y costó descubrir.

Después:

1. Sumar la página a la sección "Redes" de `mkdocs.yml`. El sitio se arma en modo estricto: una página
   fuera del índice o un link roto hacen fallar el CI.
2. `uv run python scripts/matriz.py` suma la red a la matriz del README.
3. `uv run python scripts/sitio.py` actualiza la portada del sitio, que sale del README.
4. Sumar la red a la lista de `.github/ISSUE_TEMPLATE/error-en-una-red.yml`.
5. Verificar todo:

    ```bash
    uv run ruff format . && uv run ruff check . && uv run mypy && uv run lint-imports
    uv run pytest
    uv run --group docs mkdocs serve   # para ver la página en http://127.0.0.1:8000
    ```

## Cuándo está terminada

- [ ] Declara su descripción (`spec.py`): capacidades, tipos de activo, OAuth y tabla de errores.
- [ ] Pasa el contrato común con respuestas copiadas de la API real, sin datos personales ni tokens.
- [ ] Prueba la traducción de cada capacidad con respuestas grabadas. Ningún test llama a la red.
- [ ] No suma dependencias obligatorias ni importa a otra red
      ([ADR 0006](adr/0006-cada-red-paga-lo-suyo.md)).
- [ ] Tiene su página en `docs/`, en la navegación del sitio, con lo que conviene saber.
- [ ] Aparece en la matriz del README y en la lista de redes de la plantilla de issues.

## Publicarla aparte (opcional)

Si la red necesita una biblioteca pesada o tiene su propio ritmo de versiones, puede vivir en un paquete
propio y registrarse por entry point:

```toml
[project.entry-points."omnisocial.providers"]
mired = "omnisocial_mired:mired_provider"
```

```python
from omnisocial.network import load_entry_point

factory = load_entry_point("mired")
```

El paquete externo usa lo mismo que las redes de este repositorio: importa de `omnisocial.network` y corre
el contrato de `omnisocial.testing`.
