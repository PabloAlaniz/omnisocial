# 0013. Mensajes sin historial y bandeja unificada

## Contexto

La mensajería se había modelado sobre Messenger e Instagram: la red deja leer las conversaciones, y de
ahí salen a quién responder y cuándo escribió por última vez. WhatsApp y Telegram no dejan leer nada:
los mensajes llegan por avisos y, si no se guardaron, se perdieron. Además traen lo que faltaba en el
dominio: adjuntos, plantillas para escribir fuera de la ventana y el estado de entrega de lo enviado.

Por otro lado, a una marca le escriben por muchos lados (comentarios, mensajes, reseñas) y quien
atiende quiere verlos juntos.

## Decisión

**La red declara si deja leer las conversaciones.** `MessagingLimits.history` lo dice, junto con lo que
acepta un mensaje (largo, adjuntos, plantillas). Donde no hay historial, listar conversaciones devuelve
una negativa en vez de una lista vacía, que se confundiría con "nadie escribió".

**Donde no hay historial, la app dice a quién y cuándo escribió.** `send_message` acepta un `Recipient`
con el momento del último mensaje de la persona, que la app guardó al recibir el aviso. Con eso la
ventana se sigue comprobando antes de llamar a la red. Sin ese dato, una red con ventana solo acepta una
plantilla: mandar a ciegas es lo que les cuesta la cuenta a los números de WhatsApp.

**Un mensaje saliente es un valor.** `OutboundMessage` lleva texto, adjuntos, una plantilla o una cita,
y se valida contra los límites antes de llamar a la red, igual que un borrador al publicar.

**Los avisos traen lo necesario para responder.** Un evento de mensaje lleva la conversación, el nombre
de quien escribió, los adjuntos y, si es sobre algo enviado, hasta dónde llegó (`DeliveryStatus`). Un
adjunto puede traer una URL o un id con que pedirle el archivo a la red: bajarlo queda del lado de la
app, que sabe dónde guardarlo.

**El aviso puede necesitar la URL a la que llegó.** El de Telegram no dice de qué bot es. `parse` recibe
los parámetros de la URL, y el adaptador pone ahí el id del bot al registrarla.

**La bandeja es una forma, no un almacén.** `InboxItem` le da la misma forma a un comentario, un mensaje
o una reseña, vengan de una lectura (`read_inbox`) o de un aviso (`inbox_item_from_event`). La librería
no guarda la bandeja ni sabe qué se respondió: eso es de la app, que ya tiene su base.

## Lo que queda afuera

- **Guardar mensajes.** Sin historial en la red, alguien tiene que guardarlos, y es la app.
- **Bajar adjuntos.**
- **Recibir mensajes de Discord.** Solo se entregan por una conexión permanente; una librería que se
  llama y responde no la mantiene.
- **Crear y administrar plantillas de WhatsApp**: se listan, no se crean.
- **Marcar como leído y los indicadores de "escribiendo"**.

## Consecuencias

- `MessagingGateway.send` recibe un `OutboundMessage`, y el puerto suma `limits_for`. Un adaptador
  propio tiene que actualizarse.
- `WebhookParser.parse` recibe además `query`.
- `read_inbox` hace varias llamadas a la red por activo: es para ponerse al día, no para consultar
  seguido.
- Una red puede atender una capacidad con una credencial de la app y no con el token de la conexión (el
  bot de Discord). Si esa credencial deja de valer, la conexión no se invalida: el contrato común lo
  contempla.
