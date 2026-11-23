"""Ventanas de tiempo para leer historia."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """Un intervalo [since, until]. Cualquiera de los dos extremos puede faltar."""

    since: datetime | None = None
    until: datetime | None = None

    def __post_init__(self) -> None:
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError("La ventana empieza después de terminar.")

    def contains(self, moment: datetime | None) -> bool:
        if moment is None:
            return True
        if self.since is not None and moment < self.since:
            return False
        return not (self.until is not None and moment > self.until)

    def is_before(self, moment: datetime | None) -> bool:
        """El momento quedó antes de que empiece la ventana."""
        return moment is not None and self.since is not None and moment < self.since

    def chunks(self, max_span: timedelta) -> tuple[TimeWindow, ...]:
        """Parte la ventana en tramos que no superen `max_span`. Necesita los dos extremos."""
        if self.since is None or self.until is None:
            raise ValueError("Para partir una ventana hacen falta los dos extremos.")
        if max_span <= timedelta(0):
            raise ValueError("El tramo tiene que ser positivo.")
        parts: list[TimeWindow] = []
        start = self.since
        while start < self.until:
            end = min(start + max_span, self.until)
            parts.append(TimeWindow(start, end))
            start = end
        return tuple(parts) or (self,)
