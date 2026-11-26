# 0012. Consultas auxiliares y ritmo por red

- **Estado:** Aceptada. Actualizada por [0014](0014-operar-en-produccion.md), que reparte el ritmo entre procesos.
- **Fecha:** 2026-11-24
- **Relacionadas:** [0007](0007-descripcion-y-contrato-de-una-red.md), [0008](0008-publicar.md)

**En resumen.** Dos decisiones: las consultas auxiliares para publicar (tableros, comunidades) y el ritmo
que pide cada red. Suma una tercera, más chica: las reseñas se tratan como comentarios.

## Contexto

Hasta acá un borrador alcanzaba para publicar: texto, medios y, a lo sumo, opciones con valores fijos
(la privacidad de un video). En Pinterest y en Reddit no alcanza. Un pin va a un tablero y una
publicación de Reddit a una comunidad, con una etiqueta que depende de la comunidad: son valores que
solo la red conoce y que cambian por cuenta. Una app que quiera armar el formulario necesita pedirlos.

Además, Reddit pide un ritmo: pocos pedidos y espaciados. Hasta acá el único freno era reintentar
después de que la red rechazara.

## Decisión

**Las consultas son un puerto, y la red declara cuáles ofrece.** `LookupReader.choices` devuelve
opciones (`Choice`: un id para poner en las opciones del borrador, un nombre para mostrar y los datos
que sirven para decidir). Qué consultas ofrece cada tipo de activo, cuál depende de cuál y cuáles
aceptan un texto para buscar se declara en la descripción (`NetworkSpec.lookups`). El caso de uso
(`list_choices`) rechaza lo que la red no declaró sin llamarla.

**No es una capacidad aparte.** Acompaña a `publishing`: no agrega una columna a la matriz ni obliga a
sincronizar los activos ya guardados.

**Un tipo de activo puede exigir sus opciones.** `PublishLimits.options_required` hace que un borrador
sin opciones no pase la validación, antes de llamar a la red. Que las opciones estén completas lo
valida su propio tipo al construirse: un `PinterestOptions` sin tablero no existe.

**El ritmo se declara y lo respeta un transporte.** `Pace` dice cuántos pedidos simultáneos y cuánto
entre uno y otro; `PacedTransport` los hace esperar. La fábrica de cada red lo aplica sola, y quien
despliega puede cambiarlo o sacarlo.

**Las reseñas son comentarios.** Una reseña de Google se lee, se responde y su respuesta se borra con
las mismas operaciones que un comentario. Lo único nuevo es `Comment.rating`.

## Lo que queda afuera

- **El ritmo entre procesos.** `PacedTransport` cuenta dentro de un proceso. Con varios, cada uno
  respeta su parte y la red frena el resto con un límite de uso, que ya se traduce.
- **Consultas para las redes anteriores** (las categorías de YouTube, por ejemplo). El puerto está; se
  suman cuando hagan falta.
- **Guardar las opciones.** Cada consulta va a la red. Si conviene guardarlas un rato, lo decide la app.

## Consecuencias

- El contrato común comprueba que cada consulta declarada responda, y arma el borrador de prueba con
  las opciones que el arnés de la red indique.
- `PublishLimits.video_by_url` cubre a las redes que toman las imágenes de una URL pero piden el video
  como archivo.

## Alternativas descartadas

- **Una capacidad aparte para las consultas.** Agregaría una columna a la matriz y obligaría a
  sincronizar los activos ya guardados, para algo que solo sirve al publicar.
