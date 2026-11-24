from __future__ import annotations

import pytest

from omnisocial.domain.errors import (
    ErrorKind,
    PermissionMissing,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    TokenRejected,
)
from omnisocial.domain.lookup import LookupSpec
from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.spec import ErrorTable, NetworkSpec

RED = ProviderId("red")
TABLE = ErrorTable(
    codes={
        "muerto": ErrorKind.TOKEN_DEAD,
        "permiso": ErrorKind.MISSING_PERMISSION,
        "cuota": ErrorKind.QUOTA_EXHAUSTED,
        "mal": ErrorKind.INVALID_REQUEST,
    },
    statuses={402: ErrorKind.QUOTA_EXHAUSTED},
)


@pytest.mark.parametrize(
    ("status", "code", "kind"),
    [
        (401, "muerto", ErrorKind.TOKEN_DEAD),
        # El código de la red manda sobre el estado HTTP.
        (500, "permiso", ErrorKind.MISSING_PERMISSION),
        (402, None, ErrorKind.QUOTA_EXHAUSTED),
        (429, None, ErrorKind.RATE_LIMITED),
        (503, "desconocido", ErrorKind.TRANSIENT),
        # Un 401 o un 403 sin código conocido no es un token muerto.
        (401, None, ErrorKind.UNKNOWN),
        (403, "desconocido", ErrorKind.UNKNOWN),
        (None, None, ErrorKind.UNKNOWN),
    ],
)
def test_clasificar(status: int | None, code: str | None, kind: ErrorKind) -> None:
    assert TABLE.classify(status=status, code=code) is kind


def test_cada_clase_tiene_su_excepcion() -> None:
    dead = TABLE.error(RED, "no", status=401, code="muerto")
    assert isinstance(dead, TokenRejected)
    assert dead.code == "muerto"
    assert isinstance(TABLE.error(RED, "no", code="permiso"), PermissionMissing)
    assert isinstance(TABLE.error(RED, "no", code="cuota"), QuotaExhausted)
    limited = TABLE.error(RED, "no", status=429, retry_after=30.0)
    assert isinstance(limited, RateLimited)
    assert (limited.retry_after, limited.kind) == (30.0, ErrorKind.RATE_LIMITED)
    invalid = TABLE.error(RED, "no", status=400, code="mal")
    assert type(invalid) is ProviderError
    assert (invalid.kind, invalid.status, invalid.code) == (ErrorKind.INVALID_REQUEST, 400, "mal")
    assert ProviderError(RED, "no").kind is ErrorKind.UNKNOWN


def test_un_activo_no_declara_mas_que_la_red() -> None:
    with pytest.raises(ValueError, match="messaging"):
        NetworkSpec(
            id=RED,
            name="Red",
            capabilities=frozenset({Capability.CONTENT}),
            assets={"cuenta": frozenset({Capability.CONTENT, Capability.MESSAGING})},
        )


def test_las_consultas_auxiliares_se_declaran_bien() -> None:
    base = {"id": RED, "name": "Red", "capabilities": frozenset({Capability.ASSETS})}
    assets = {"cuenta": frozenset({Capability.ASSETS})}
    boards = LookupSpec("tableros", "Los tableros.")
    NetworkSpec(**base, assets=assets, lookups={"cuenta": (boards, LookupSpec("s", "…", parent="tableros"))})  # type: ignore[arg-type]
    for wrong, message in [
        ({"otra": (boards,)}, "no es un tipo de activo"),
        ({"cuenta": (boards, boards)}, "repite"),
        ({"cuenta": (LookupSpec("s", "…", parent="tableros"),)}, "depende de otra"),
    ]:
        with pytest.raises(ValueError, match=message):
            NetworkSpec(**base, assets=assets, lookups=wrong)  # type: ignore[arg-type]
