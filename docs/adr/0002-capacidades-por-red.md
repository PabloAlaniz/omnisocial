# 0002. Capacidades por red

## Contexto

Las redes no hacen lo mismo. Algunas tienen mensajes privados por API y otras no; algunas exponen
métricas por cuenta y otras solo por publicación; algunas renuevan tokens y otras obligan a volver a
autorizar. Una clase base con todos los métodos obliga a cada red a implementar lo que no tiene, en
general con un `raise NotImplementedError` que aparece en producción.

## Decisión

Cada capacidad es un puerto separado: `OAuthClient`, `AssetDirectory`, `ContentReader`, `CommentGateway`,
`MessagingGateway`, `InsightsReader`, `WebhookParser`. Un `Provider` es un identificador más las capacidades
que trae; las que no trae quedan en `None`.

- Los casos de uso preguntan antes de usar: si la red (o el activo) no tiene la capacidad, devuelven
  `Refused(NOT_SUPPORTED, capability=...)`.
- Cada activo declara además qué capacidades habilita, porque dentro de una misma red un activo puede
  permitir menos que otro.
- Las redes externas se suman por entry points (`omnisocial.providers`), sin tocar este paquete.

## Lo que es común a todas las redes

- **Conexión:** dueño opaco, identidad, token, estado y versión para compare-and-swap.
- **Activo:** tipo abierto (`facebook_page`, `instagram_account`…), id en la red, token propio opcional.
- **Métricas:** se guardan con el nombre propio de la red. Un catálogo chico de nombres comunes
  (`followers`, `reach`, `impressions`, `views`, `engagements`) se traduce por red, por tipo de activo y por
  versión de la API. Lo que no tiene traducción vuelve en `unresolved`, no se inventa.
- **Mensajes:** la ventana para responder es una regla de dominio (`ReplyWindow`) que cada red declara.

## Consecuencias

- Una red con solo login es válida: sirve para "entrar con…" sin nada más.
- Sumar una capacidad nueva al núcleo es un puerto nuevo y un caso de uso nuevo; las redes que no la
  implementan no cambian.
