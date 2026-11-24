"""Presupuesto de cuota: contar lo que cuesta cada llamada y cortar antes de que la red la niegue.

Hay redes que dan una cuota fija por día a toda la app (YouTube: 10.000 unidades). Agotarla deja a todos
los clientes sin servicio hasta el día siguiente, así que conviene reservar una parte para lo importante y
enterarse antes de llegar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, tzinfo

from omnisocial.application.ports import Clock, QuotaLedger


@dataclass(frozen=True, slots=True)
class QuotaBudget:
    key: str
    """De quién es la cuota: la app en la red (`youtube:<client_id>`), no la cuenta conectada."""
    limit: int
    ledger: QuotaLedger
    clock: Clock
    resets_in: tzinfo = UTC
    """La zona horaria en la que la red reinicia la cuota a medianoche."""

    async def spend(self, units: int) -> bool:
        """Anota el gasto si entra en lo que queda del día. Devuelve si entró."""
        day = self.clock.now().astimezone(self.resets_in).date().isoformat()
        return await self.ledger.spend(self.key, day, units, limit=self.limit)
