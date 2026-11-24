# Lo que vale para todas las redes

Lo que se aprendió en producción y se repite de una red a otra. Lo propio de cada una está en su página;
cómo se suma una red nueva, en [nueva-red.md](nueva-red.md).

- **401/403 no siempre es un token muerto.** Cada red tiene sus códigos: solo los que significan "este token
  ya no sirve" invalidan la conexión; los de permiso faltante vuelven como `Refused(MISSING_PERMISSION)`.
- **Los links de imágenes vencen** (CDN firmados). Si hace falta mostrarlas después, se copian en el momento.
- **Guardar el id estable, no el nombre.** Los nombres de usuario cambian; el id numérico no.
