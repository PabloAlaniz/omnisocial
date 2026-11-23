from omnisocial.adapters.stores.memory import (
    InMemoryAssetRepository,
    InMemoryAuthorizationStateStore,
    InMemoryConnectionRepository,
)
from tests.adapters.stores.contract import (
    asset_contract,
    connection,
    connection_contract,
    request,
    state_contract,
)
from tests.fakes import FakeClock


async def test_conexiones() -> None:
    await connection_contract(InMemoryConnectionRepository())


async def test_activos() -> None:
    await asset_contract(InMemoryConnectionRepository(), InMemoryAssetRepository())


async def test_estados() -> None:
    await state_contract(InMemoryAuthorizationStateStore(FakeClock()))


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
