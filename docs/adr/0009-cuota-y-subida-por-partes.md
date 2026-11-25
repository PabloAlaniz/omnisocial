# 0009. Cuota y subida por partes

## Contexto

YouTube trajo dos cosas que Meta y TikTok no tenían. La cuota es de toda la app y se agota: si un cliente
la gasta, los demás se quedan sin servicio hasta el día siguiente. Y los videos no se toman de una URL:
hay que subir el archivo, que puede pesar gigas y tardar más de lo que dura una conexión.

## Decisión

**La cuota se cuenta del lado propio.** `QuotaBudget` anota el costo de cada llamada en un `QuotaLedger`
(en memoria o en PostgreSQL) antes de hacerla, por clave y por día en la zona horaria donde la red la
reinicia. Si no entra, el adaptador lanza `QuotaExhausted` sin llamar, y la app recibe la misma negativa
que si lo hubiera dicho la red. Es opcional: sin libro, no se cuenta.

- La clave es la app en la red, no la cuenta conectada.
- El gasto se anota aunque la llamada falle. Es conservador a propósito: la red también la cobra en la
  mayoría de los casos, y pasarse cuesta más que quedarse corto.
- El límite es configurable, para dejar una reserva.

**Un medio es una URL o un archivo.** `Media` lleva una de las dos cosas y cada tipo de activo declara cuál
acepta. Un archivo es un `MediaFile`: tamaño, tipo y `read(offset, length)`, que se puede pedir más de una
vez. Así el adaptador sube por partes y retoma sin tener el archivo en memoria.

**El transporte acepta un cuerpo binario.** La subida reanudable usa el mismo puerto HTTP que todo lo
demás, y se prueba con el mismo transporte falso.

**Abandonar una subida no deja dudas, salvo al final.** Mientras no se mandó la última parte la red no
creó nada: el adaptador lanza `NotPublished` y el núcleo libera la clave de idempotencia. Si lo que se
pierde es la respuesta a la última parte, no se puede afirmar, y la publicación queda `STARTED`
([ADR 0008](0008-publicar.md)).

## Lo que queda afuera

- **Retomar una subida en otro proceso.** La sesión de subida no se guarda: si el proceso muere, la subida
  empieza de nuevo. Guardarla exigiría poder reabrir el archivo desde un registro.
- **Un protocolo de subida común.** Cada red tiene el suyo. Cuando haya dos, se verá qué comparten.
- **Devolver lo gastado si la llamada no llegó.** Ver arriba.

## Consecuencias

- `create_schema` crea la tabla `omnisocial_quota`.
- Una red que solo acepta archivos rechaza un borrador con URLs antes de llamar, y al revés.
