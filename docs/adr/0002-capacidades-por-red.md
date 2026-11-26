# 0002. Capacidades por red

- **Estado:** Aceptada. Actualizada por [0005](0005-perfiles-publicos-y-mirador.md), [0008](0008-publicar.md), [0011](0011-redes-federadas-y-credenciales.md), [0012](0012-consultas-auxiliares-y-ritmo.md), que suman puertos.
- **Fecha:** 2026-11-23
- **Relacionadas:** [0001](0001-arquitectura-en-capas.md), [0007](0007-descripcion-y-contrato-de-una-red.md)

## Contexto

Las redes no hacen lo mismo. Algunas tienen mensajes privados por API y otras no; algunas exponen
métricas por cuenta y otras solo por publicación; algunas renuevan tokens y otras obligan a volver a
autorizar. Una clase base con todos los métodos obliga a cada red a implementar lo que no tiene, en
general con un `raise NotImplementedError` que aparece en producción.

## Decisión

Cada capacidad es un [puerto](../referencia/glosario.md) separado. Al tomar la decisión eran siete: `OAuthClient`,
`AssetDirectory`, `ContentReader`, `CommentGateway`, `MessagingGateway`, `InsightsReader` y
`WebhookParser`. Los ADR siguientes sumaron otros (`Publisher`, `ProfileLookup`, `LookupReader`,
`ServerOAuth`, `CredentialLogin`…); la lista vigente está en `src/omnisocial/application/ports.py`. Un
`Provider` es un identificador más las capacidades que trae; las que no trae quedan en `None`.

- Los casos de uso preguntan antes de usar: si la red (o el activo) no tiene la capacidad, devuelven
  `Refused(NOT_SUPPORTED, capability=...)`.
- Cada activo declara además qué capacidades habilita, porque dentro de una misma red un activo puede
  permitir menos que otro.
- Las redes externas se suman por entry points (`omnisocial.providers`), sin tocar este paquete.

## Lo que es común a todas las redes

- **Conexión:** dueño opaco, identidad, token, estado y versión para [compare-and-swap](../referencia/glosario.md).
- **Activo:** tipo abierto (`facebook_page`, `instagram_account`…), id en la red, token propio opcional.
- **Métricas:** se guardan con el nombre propio de la red. Un catálogo chico de nombres comunes
  (`followers`, `reach`, `impressions`, `views`, `engagements`) se traduce por red, por tipo de activo y por
  versión de la API. Lo que no tiene traducción vuelve en `unresolved`, no se inventa.
- **Mensajes:** la ventana para responder es una regla de dominio (`ReplyWindow`) que cada red declara.

## Consecuencias

- Una red con solo login es válida: sirve para "entrar con…" sin nada más.
- Sumar una capacidad nueva al núcleo es un puerto nuevo y un caso de uso nuevo; las redes que no la
  implementan no cambian.

## Alternativas descartadas

- **Una clase base con todos los métodos.** Obliga a cada red a implementar lo que no tiene, con un
  `raise NotImplementedError` que aparece en producción.
