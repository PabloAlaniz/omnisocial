# 0003. Webhooks con omniwebhook

## Contexto

Recibir webhooks bien es más que verificar una firma. Las redes reintentan: si la app responde tarde o
falla, el mismo aviso vuelve, y sin control se procesa dos veces. Si se marca como procesado antes de
terminar y el procesamiento falla, el reintento se descarta y el aviso se pierde. Estas reglas ya están
resueltas, especificadas y probadas en [omniwebhook](https://pypi.org/project/omniwebhook/).

## Decisión

- omniwebhook es una **dependencia obligatoria**, no un extra. No tiene dependencias propias y es la regla
  de recepción para todas las redes.
- El puerto `WebhookParser` expone un `omniwebhook.Verifier`. Cada red declara su esquema de firma con
  omniwebhook (Meta usa `hmac_body_scheme` sobre `X-Hub-Signature-256`) y no reimplementa HMAC.
- `HandleWebhook` arma un receptor de omniwebhook por red con el almacén de reservas que se le inyecta.
  Traducir, enrutar y llamar a `on_events` es el procesamiento que omniwebhook reserva, completa o libera.
- El almacén de reservas es obligatorio en `Omnisocial.build`. Uno en memoria deduplicaría solo dentro de
  un proceso y escondería el problema hasta tener dos instancias.
- El saludo de suscripción (`hub.challenge` en Meta) no es parte de omniwebhook: queda en cada red
  (`WebhookParser.handshake`).

## Consecuencias

- **La clave es la huella del cuerpo** cuando la red no manda un id de entrega, como Meta. Dos avisos
  distintos con el mismo cuerpo exacto se tomarían por uno; en Meta no pasa, porque cada entrega lleva su
  marca de tiempo.
- **La deduplicación es por entrega, no por evento.** Una entrega de Meta puede traer varios eventos; si
  `on_events` falla a mitad, la entrega se reprocesa entera. Lo que haga `on_events` tiene que tolerar
  recibir un evento dos veces.
- **Sin control de frescura** para esquemas que no firman una marca de tiempo. La firma y la reserva son la
  defensa contra la repetición.
- Las respuestas HTTP son las de omniwebhook (`http_status_for`) y el cuerpo no dice qué falló.
