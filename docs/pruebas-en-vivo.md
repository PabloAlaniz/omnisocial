# Pruebas en vivo

Una corrida nocturna ([`en-vivo.yml`](../.github/workflows/en-vivo.yml)) prueba cada red contra su API
real, con una cuenta de prueba. Es lo único que dice si un adaptador funciona de verdad.

**Viene apagada.** Cada red se enciende cargando un secreto en el repositorio. Sin el secreto, esa red
se saltea y la corrida sigue.

## Qué comprueba

Por defecto solo lee, sin cambiar nada en la cuenta:

1. Conecta la cuenta con el token o la credencial del secreto.
2. Descubre sus activos.
3. En cada activo: lista una publicación y sus comentarios, corre cada consulta auxiliar y lista una
   conversación, según lo que ese activo ofrezca.

Si se corre a mano con "publicar un texto y borrarlo", además publica un texto que dice que es una
prueba y lo borra. **No lo hace nunca la corrida nocturna.**

El resultado queda en el resumen de la corrida: qué se comprobó en cada red y cómo salió. Solo nombres
de comprobaciones y motivos de negativa: nunca un token ni el contenido de la cuenta.

## Encender una red

En *Settings → Secrets and variables → Actions*, un secreto llamado `OMNISOCIAL_LIVE_<RED>` (por ejemplo
`OMNISOCIAL_LIVE_TELEGRAM`), con un JSON:

```json
{
  "config": {"client_id": "...", "client_secret": "..."},
  "token": {"access_token": "...", "refresh_token": "...", "server": "mastodon.social"},
  "write": {"options": {"chat_id": "@canal_de_prueba"}}
}
```

- **`config`**: los argumentos de la configuración de esa red (`TelegramConfig`, `MetaConfig`…).
- **`token`** o **`credentials`**: con qué se conecta. `token` es un token ya emitido (`access_token` y,
  si los hay, `refresh_token`, `expires_at`, `scopes`, `server`, `kind`). `credentials` es lo que pide
  `connect_with_credentials` en las redes que conectan así.
- **`write`**: opcional. Las opciones para publicar (`options`), que algunas redes exigen.

Los nombres de red son los de la matriz: `meta`, `instagram`, `tiktok`, `youtube`, `linkedin`, `x`,
`threads`, `bluesky`, `mastodon`, `pixelfed`, `pinterest`, `reddit`, `google_business`, `whatsapp`,
`telegram`, `discord` y `discord_webhook`.

### Por dónde empezar

Las más fáciles son las que no necesitan una app aprobada ni un token que venza:

| Red | Qué cargar |
|---|---|
| Telegram | `{"credentials": {"token": "<el del bot>"}, "write": {"options": {"chat_id": "@canal"}}}` |
| Discord (webhook) | `{"config": {"app_url": "https://…"}, "credentials": {"webhook_url": "https://discord.com/api/webhooks/…"}}` |
| Bluesky | `{"credentials": {"identifier": "prueba.bsky.social", "password": "<contraseña de aplicación>"}}` |
| Mastodon | `{"config": {"client_name": "Prueba"}, "token": {"access_token": "…", "server": "mastodon.social"}}` (el token se crea en Preferencias → Desarrollo) |

### Cuentas de prueba

- **Una cuenta que no importe.** La corrida lee lo que hay en ella, y si se le pide, publica.
- **Con los permisos justos.** Un token de solo lectura alcanza para la corrida nocturna.
- **Un secreto por red.** Si se filtra uno, se cambia ese.

## Lo que no resuelve sola

**Los tokens que rotan.** En X, Pinterest y Discord cada renovación cambia el token de renovación, y un
workflow no puede guardar el nuevo en un secreto. Para esas redes el secreto hay que renovarlo a mano
cuando vence, o guardarlo en un almacén propio al que la corrida tenga acceso. Mientras tanto, la corrida
falla en "conectar" y lo dice.

**Las redes que piden una app aprobada** (Meta, TikTok, LinkedIn, Reddit, Google Business Profile,
Pinterest con acceso estándar) necesitan esa aprobación antes de tener algo que probar.

## Correrla en una máquina

```bash
export OMNISOCIAL_LIVE_TELEGRAM='{"credentials": {"token": "..."}}'
uv run pytest -m live --no-cov tests/live
# Además, publicar y borrar:
OMNISOCIAL_LIVE_WRITE=1 uv run pytest -m live --no-cov tests/live
```

## Cuando una red pasa

Después de unas noches seguidas en verde, y con alguien que se haga cargo de mirarla, la red puede pasar
a [verificada](niveles-de-soporte.md).
