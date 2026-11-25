# 0014. Operar en producción

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
la cuenta), ni rutas con ids. La ruta de un pedido se informa con cada tramo que no es un nombre
reemplazado: hay redes donde el secreto viaja en la ruta, y una regla por red se olvidaría en la
siguiente. El contrato común comprueba, en cada red, que ningún secreto que pasó por el transporte
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
revisó; una tarea avisa por tiempo. No se intenta leer los anuncios de cada red: cambian de formato, y
un aviso que falla en silencio es peor que uno por calendario.

## Lo que queda afuera

- **Un estado público fuera de GitHub.** El resumen de cada corrida y su insignia alcanzan por ahora.
- **Guardar los tokens que rotan** durante las pruebas en vivo.
- **Registros.** La librería no escribe en ningún log: avisa a quien se suscriba.

## Consecuencias

- `Omnisocial.build` suma `observer`, y las fábricas de las redes con ritmo, `rate_limits`.
- `create_schema` crea la tabla `omnisocial_rate_limits`.
- Cada versión publicada lleva una atestación de origen y su lista de componentes.
