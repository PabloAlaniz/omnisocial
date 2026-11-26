# Glosario

**Activo** (`Asset`)
:   Lo que una conexión permite manejar: una página de Facebook, una cuenta de Instagram, un canal de
    YouTube, un bot de Telegram. Casi todas las operaciones se hacen sobre un activo, por su `id`. Ver
    [Conectar cuentas](../conectar.md).

**Arnés** (`NetworkHarness`)
:   Lo que cada red le da al contrato común para probarse: sus respuestas grabadas, su credencial o
    servidor de prueba y las opciones para publicar. Ver [Sumar una red](../nueva-red.md).

**Atestación de origen**
:   Una firma de que el paquete publicado salió de este repositorio, de ese commit y de ese workflow
    (el estándar es SLSA). Ver [Cómo se publica una versión](../versiones.md).

**Aviso**
:   Lo que una red manda cuando pasa algo (un comentario nuevo, un mensaje). Es lo que en inglés se llama
    *webhook*. Ver [Avisos](../webhooks.md).

**Capacidad** (`Capability`)
:   Algo que una red sabe hacer: `login`, `assets`, `content`, `publishing`, `comments`, `messaging`,
    `insights`, `webhooks`, `public_profiles`. Cada red implementa solo las que tiene; la
    [matriz](../index.md) las muestra.

**Conexión** (`Connection`)
:   Una autorización guardada: el token que una persona le dio a la app para usar su cuenta en una red.
    Tiene un dueño y un estado (`ACTIVE`, `EXPIRED`, `INVALID`, `REVOKED`). Ver
    [Mantener vivas las conexiones](../conexiones.md).

**Dueño** (`owner`)
:   A quién pertenece una conexión, para la app: un usuario, un proyecto, un cliente. Es un texto opaco
    para la librería.

**Huella**
:   Un resumen criptográfico (hash) del cuerpo de un aviso. Cuando la red no manda un id de entrega,
    la huella sirve para reconocer un aviso repetido.

**Idempotencia**
:   Que repetir un pedido no repita su efecto. Publicar con la misma `idempotency_key` devuelve la
    publicación que ya existe; un aviso repetido no se procesa dos veces.

**Lista de componentes** (SBOM)
:   De qué depende el paquete, con las versiones exactas con que se probó. Acompaña a cada versión.

**Mirador**
:   Una cuenta propia a través de la cual se miran cuentas ajenas, en las redes que lo exigen (Instagram).
    Ver [Perfiles públicos](../perfiles-publicos.md).

**Negativa** (`Refused`)
:   El resultado de una operación que no se hizo por una razón que la app tiene que manejar. Lo contrario
    de `Done`. Ver [Negativas y errores](negativas.md).

**Puerto**
:   Una interfaz (`Protocol`) que el núcleo define y un adaptador implementa: una capacidad de una red
    (`Publisher`), un almacén (`ConnectionRepository`), el transporte HTTP. Así el núcleo no depende
    de ninguna red ni de ninguna base. Ver el [ADR 0001](../adr/0001-arquitectura-en-capas.md).

**Raíz de composición**
:   El único lugar donde se arman juntas todas las piezas: `Omnisocial.build`
    (`entrypoints/hub.py`).

**Red y proveedor**
:   La red es el servicio (Instagram, X). El proveedor (`Provider`) es el adaptador que habla con su API.
    Casi siempre coinciden; Meta es un proveedor que cubre dos redes (Facebook e Instagram).

**Renovación compare-and-swap**
:   Cómo se guarda un token renovado: solo si nadie lo cambió desde que se leyó. Si dos procesos renuevan
    a la vez, uno gana y el otro usa el que quedó, sin perder la conexión.

**Ritmo** (`Pace`)
:   Cuántos pedidos por segundo, y cuántos a la vez, acepta una red. La librería lo respeta sola; para
    repartirlo entre procesos, ver [Operar](../operar.md#limites-de-uso-entre-varios-procesos).

**Usuario de sistema**
:   En Meta, una cuenta de la organización (no de una persona) con un token que no vence. Sirve para
    conectar sin que cada persona autorice. Ver [Conectar cuentas](../conectar.md#con-un-usuario-de-sistema).
