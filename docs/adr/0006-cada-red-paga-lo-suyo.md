# 0006. Cada red paga lo suyo

- **Estado:** Aceptada. La regla sigue; los ejemplos son de cuando había dos redes.
- **Fecha:** 2026-11-23
- **Relacionadas:** [0001](0001-arquitectura-en-capas.md), [0002](0002-capacidades-por-red.md)

## Contexto

omnisocial junta varias redes en un solo paquete. Quien usa solo una no debería cargar con las demás: ni
instalar sus dependencias ni ejecutar su código al importar.

Lo que pesa no es el código de un adaptador (cuando se decidió, las redes eran Meta y TikTok, Python puro,
y el paquete entero ocupaba unos 90 KB), sino las dependencias: un SDK oficial puede arrastrar decenas de
paquetes.

## Decisión

- **El paquete raíz no importa redes.** `import omnisocial` trae el núcleo; cada red se carga recién con su
  módulo (`omnisocial.meta`, `omnisocial.tiktok`).
- **Una red no importa a otra.** Lo común va al núcleo.
- **Una red no suma dependencias obligatorias.** Si necesita una biblioteca, va en un extra con su nombre
  (por ejemplo, un hipotético `omnisocial[youtube]`; hoy ninguna red lo necesita). Si es pesada o tiene un ciclo de versiones propio, va en un paquete aparte que se
  registra por entry point (`omnisocial.providers`, ver ADR 0002).
- **Lo opcional sigue siendo opcional.** httpx, cryptography, psycopg y starlette son extras; el núcleo no
  los importa.

Lo vigilan `tests/architecture/test_peso.py` (qué queda cargado después de cada import) y los contratos de
import-linter (independencia entre redes y núcleo sin opcionales).

## Consecuencias

- Todas las redes viajan en el mismo wheel: son código liviano sin dependencias propias.
- Si una red futura necesita un SDK, la decisión entre extra y paquete aparte se toma al sumarla, con esta
  regla a la vista.

## Alternativas descartadas

- **Un paquete por red.** Suma versiones y publicaciones que mantener, para redes que son Python puro
  y sin dependencias propias.
