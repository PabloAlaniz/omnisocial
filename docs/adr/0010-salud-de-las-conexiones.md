# 0010. Salud de las conexiones

## Contexto

Un token se renovaba recién cuando alguien usaba la conexión, y la app se enteraba de que una conexión ya
no servía recién cuando una operación fallaba. Con tokens que duran una hora y traen su token de
renovación, alcanza. Con Threads e Instagram no: el token dura 60 días, se renueva él mismo y, si vence,
no se recupera. Una cuenta que nadie toca durante dos meses se pierde en silencio.

## Decisión

**Renovar antes, desde afuera.** `refresh_expiring` lista las conexiones activas que vencen dentro de un
plazo y las renueva. Lo corre un planificador de la app; la librería no tiene uno. Devuelve un informe con
cuatro grupos: renovadas, perdidas (la red rechazó la renovación), no renovables (van a vencer: hay que
avisarle a la persona) y con error (se reintentan en la próxima corrida). Una conexión que falla no frena
a las demás.

**Avisar los cambios de estado.** `on_connection_change` se llama cuando una conexión deja de servir
(venció, la red rechazó el token, se desconectó) o vuelve a servir (alguien reconectó). Se llama después de
guardar el cambio, una vez por cambio: renovar un token no es un cambio de estado, y conectar por primera
vez tampoco.

**`can_refresh` dice la verdad, con el reloj.** Una red que solo renueva tokens vigentes y con más de un
día lo dice ahí. El núcleo no conoce esas reglas.

**Reconectar conserva la identidad.** El id de la conexión y el de sus activos son los mismos después de
reconectar: lo que la app guardó contra esos ids sigue valiendo.

## Lo que queda afuera

- **El planificador.** Cuándo correr la renovación es de la app.
- **Avisarle a la persona.** La librería dice qué conexiones están por perderse; el mail lo manda la app.

## Consecuencias

- `ConnectionRepository` suma `list_expiring`: un repositorio propio tiene que implementarlo.
- Si el observador lanza una excepción, la operación que provocó el cambio falla, aunque el cambio ya quedó
  guardado. Conviene que encole y no haga trabajo pesado.
- `TransportError` pasa a ser un `OmnisocialError`, para que una falla de red en una conexión se pueda
  atrapar sin conocer el transporte.
