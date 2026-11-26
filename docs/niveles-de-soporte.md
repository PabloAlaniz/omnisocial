# Niveles de soporte

La columna "Soporte" de la [matriz](index.md) dice, para cada red, cuánto respaldo tiene. Sale de la descripción de la red
(`NetworkSpec.support`).

| Nivel | Qué quiere decir |
|---|---|
| **verificada** | Se prueba seguido contra la API real, con una cuenta de prueba, y tiene quién la mantenga. Si la red cambia algo, se sabe en un día. |
| **comunitaria** | Alguien la usa en producción y avisa cuando se rompe, pero no se prueba sola contra la API real. |
| **experimental** | Escrita contra la documentación de la red y probada con respuestas simuladas. Nadie confirmó que funcione con la API real. |

**Hoy todas las redes son experimentales.** El código está probado contra respuestas simuladas, que
dicen si el adaptador hace lo que su autor creyó que la red pedía, no si la red pide eso. Cada página de
red lista, al final, lo que quedó sin verificar.

## Cómo sube de nivel una red

- **A comunitaria**: alguien la usa con cuentas reales y lo cuenta en un issue, con qué capacidades
  probó. Se cambia `support=SupportLevel.COMMUNITY` en su `spec.py` y se corrige lo que haya aparecido.
- **A verificada**: tiene una cuenta de prueba cargada para la [corrida nocturna](pruebas-en-vivo.md), la
  corrida pasa, y alguien se hace responsable de mirarla cuando falla. Un test comprueba que toda red
  verificada esté en esa corrida.

Una red baja de nivel si su corrida falla y nadie la arregla, o si la cuenta de prueba deja de servir.

## Qué significa para quien la usa

Con una red experimental conviene probar el flujo completo con una cuenta propia antes de ponerla frente
a clientes, empezando por conectar y por lo que más se va a usar. Lo que se encuentre vale mucho como
issue: es lo que la saca de experimental.
