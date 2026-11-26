# Decisiones de diseño

Cada decisión de diseño que cuesta revertir queda escrita en un ADR (*Architecture Decision Record*): el
contexto, lo que se decidió, por qué y qué consecuencias trae. Un ADR no se reescribe cuando la decisión
cambia. Se escribe uno nuevo y el anterior pasa a decir "Actualizada por" o "Reemplazada por".

| ADR | Decisión | Estado | Fecha |
|---|---|---|---|
| [0001](0001-arquitectura-en-capas.md) | Arquitectura en capas | Aceptada | 2026-11-23 |
| [0002](0002-capacidades-por-red.md) | Capacidades por red | Aceptada, actualizada | 2026-11-23 |
| [0003](0003-webhooks-con-omniwebhook.md) | Webhooks con omniwebhook | Aceptada | 2026-11-23 |
| [0004](0004-reglas-estaticas-de-diseno.md) | Reglas estáticas de diseño | Aceptada | 2026-11-23 |
| [0005](0005-perfiles-publicos-y-mirador.md) | Perfiles públicos y mirador | Aceptada | 2026-11-23 |
| [0006](0006-cada-red-paga-lo-suyo.md) | Cada red paga lo suyo | Aceptada | 2026-11-23 |
| [0007](0007-descripcion-y-contrato-de-una-red.md) | Descripción y contrato de una red | Aceptada, actualizada | 2026-11-24 |
| [0008](0008-publicar.md) | Publicar | Aceptada, actualizada | 2026-11-24 |
| [0009](0009-cuota-y-subida-por-partes.md) | Cuota y subida por partes | Aceptada | 2026-11-24 |
| [0010](0010-salud-de-las-conexiones.md) | Salud de las conexiones | Aceptada | 2026-11-24 |
| [0011](0011-redes-federadas-y-credenciales.md) | Redes federadas y conexión por credencial | Aceptada | 2026-11-24 |
| [0012](0012-consultas-auxiliares-y-ritmo.md) | Consultas auxiliares y ritmo por red | Aceptada, actualizada | 2026-11-24 |
| [0013](0013-mensajes-sin-historial-y-bandeja.md) | Mensajes sin historial y bandeja unificada | Aceptada | 2026-11-24 |
| [0014](0014-operar-en-produccion.md) | Operar en producción | Aceptada | 2026-11-24 |

## Sumar un ADR

Se copia la [plantilla](plantilla.md) con el número siguiente, se agrega a esta tabla y a la navegación del
sitio (`mkdocs.yml`), y va en el mismo pull request que el cambio que describe. Un test comprueba que cada
ADR tenga su encabezado y figure acá.
