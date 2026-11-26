# 0014. Operar en producción

- **Estado:** Aceptada.
- **Fecha:** 2026-11-24
- **Relacionadas:** [0007](0007-descripcion-y-contrato-de-una-red.md), [0012](0012-consultas-auxiliares-y-ritmo.md)

**En resumen.** Seis decisiones para operar con muchas redes:

1. Observar cada llamada a una red, sin datos de la cuenta.
2. OpenTelemetry como extra.
3. Repartir los límites de uso entre procesos.
4. Un nivel de soporte por red.
5. Pruebas en vivo, apagadas por defecto.
6. La versión de API como dato con fecha.

Además, cada versión publicada lleva su atestación de origen (SLSA) y su lista de componentes (SBOM).

## Contexto

Con muchas redes, lo que falta no es otra red: es saber qué pasa cuando corren. Cuál falla, cuánto
tarda, quién se pasó del límite, qué versión de API está por desaparecer, y cuáles de los adaptadores
alguien probó contra la red de verdad.

## Decisión

**Se observa en el borde con la red.** `Omnisocial.build(observer=...)` envuelve cada adaptador y avisa
de cada llamada: la red, la operación, el resultado y la duración. Es un solo lugar para todas las redes
y todas las operaciones, presentes y futuras, sin tocar los casos de uso. Lo que el núcleo niega sin
llamar a nadie no es una llamada y no aparece.

**Una observación lleva nombres, no datos.** Ni tokens, ni mensajes de error (que pueden traer datos de
la cuenta), ni rutas con ids. De la ruta de un pedido se informan los nombres, y cada tramo que no
es un nombre (un id, un token) se reemplaza por `:id`: hay redes donde el secreto viaja en la ruta. El contrato común comprueba, en cada red, que ningún secreto que pasó por el transporte
aparezca en lo observado.

**OpenTelemetry es un extra, no el contrato.** El núcleo define un observador mínimo; `omnisocial.otel`
lo traduce. Quien usa otra cosa escribe diez líneas.

**Los límites se comparten con un solo dato.** `RateLimitStore` guarda, por red, el momento del próximo
pedido. Con eso se reparten los turnos y se respeta la espera que pidió la red, entre todos los
procesos. El tope de pedidos simultáneos queda por proceso: compartirlo pide reservas con vencimiento, y
la red ya frena lo que se pase.

**El nivel de soporte es un dato de la red.** Cada una declara si está verificada, si es comunitaria o
si es experimental, y la matriz lo muestra. Todas empiezan experimentales: estar probada contra
respuestas simuladas no es estar probada.

**Las pruebas en vivo vienen apagadas.** El armazón sirve para todas las redes y cada una se enciende
con un secreto. No publican salvo que alguien lo pida a mano.

**La versión de API es un dato con fecha.** Cada red declara contra cuál está escrita y cuándo se la
revisó; una tarea avisa por tiempo.

## Lo que queda afuera

- **Un estado público fuera de GitHub.** El resumen de cada corrida y su insignia alcanzan por ahora.
- **Guardar los tokens que rotan** durante las pruebas en vivo.
- **Registros.** La librería no escribe en ningún log: avisa a quien se suscriba.

## Consecuencias

- `Omnisocial.build` suma `observer`, y las fábricas de las redes con ritmo, `rate_limits`.
- `create_schema` crea la tabla `omnisocial_rate_limits`.
- Cada versión publicada lleva una [atestación de origen](../referencia/glosario.md) y su
  [lista de componentes](../referencia/glosario.md) (ver [cómo se publica una versión](../versiones.md)).

## Alternativas descartadas

- **Una regla por red para limpiar las rutas.** Se olvidaría en la red siguiente; reemplazar todo
  tramo que no es un nombre vale para todas.
- **Leer los anuncios de cada red para saber cuándo retira una versión.** Cambian de formato, y un
  aviso que falla en silencio es peor que uno por calendario.
