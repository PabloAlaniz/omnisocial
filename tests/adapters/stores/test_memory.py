from datetime import timedelta, timezone

from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
    InMemoryPublicationRepository,
    InMemoryQuotaLedger,
    InMemoryServerAppStore,
)
from omnisocial.application.quota import QuotaBudget
from tests.adapters.stores.contract import (
    asset_contract,
    connection,
    connection_contract,
    publication_contract,
    quota_contract,
    request,
    server_app_contract,
    state_contract,
)
from tests.fakes import FakeClock


async def test_conexiones() -> None:
    await connection_contract(InMemoryConnectionRepository())


async def test_activos() -> None:
    await asset_contract(InMemoryConnectionRepository(), InMemoryAssetRepository())


async def test_estados() -> None:
    await state_contract(InMemoryAuthorizationStateStore(FakeClock()))


async def test_publicaciones() -> None:
    await publication_contract(InMemoryPublicationRepository())


async def test_apps_por_servidor() -> None:
    await server_app_contract(InMemoryServerAppStore())


async def test_cuota() -> None:
    await quota_contract(InMemoryQuotaLedger())


async def test_el_presupuesto_cuenta_el_dia_donde_la_red_lo_reinicia() -> None:
    ledger = InMemoryQuotaLedger()
    clock = FakeClock()  # 23 de noviembre a las 12:00 UTC
    pacific = timezone(timedelta(hours=-8))
    budget = QuotaBudget("app", 100, ledger, clock, resets_in=pacific)
    assert await budget.spend(100)
    assert not await budget.spend(1)
    # A las 03:00 UTC del 24 en el Pacífico sigue siendo 23: la cuota no volvió.
    clock.advance(timedelta(hours=15))
    assert not await budget.spend(1)
    clock.advance(timedelta(hours=6))
    assert await budget.spend(1)
    assert await ledger.spent("app", "2026-11-24") == 1
    assert await QuotaBudget("utc", 5, ledger, clock).spend(5)


async def test_agregar_dos_veces_es_un_error() -> None:
    repo = InMemoryConnectionRepository()
    await repo.add(connection())
    try:
        await repo.add(connection())
    except ValueError:
        return
    raise AssertionError("debió fallar")


async def test_los_estados_vencidos_se_limpian() -> None:
    clock = FakeClock()
    store = InMemoryAuthorizationStateStore(clock)
    await store.put(request("viejo", minutes=1))
    clock.current = clock.current.replace(hour=13)
    await store.put(request("nuevo", minutes=120))
    assert await store.take("viejo") is None
