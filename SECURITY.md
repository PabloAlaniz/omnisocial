# Seguridad

Si encontrás una vulnerabilidad, no abras un issue público: escribí por el formulario de
[avisos de seguridad del repositorio](https://github.com/PabloAlaniz/omnisocial/security/advisories/new).

Lo que la librería garantiza y se prueba:

- Los tokens se guardan cifrados (AES-256-GCM) y atados a su fila: copiados a otra fila no se descifran.
- El `state` de OAuth sirve una sola vez y vence.
- Solo se vuelve a orígenes permitidos después de autorizar.
- Ningún webhook se traduce sin firma válida, y sin secreto configurado se rechaza. Lo verifica omniwebhook.
- Un webhook repetido no se procesa dos veces, y uno cuyo procesamiento falló se puede reintentar.
- Los tokens no aparecen en `repr` ni en logs de la librería.
