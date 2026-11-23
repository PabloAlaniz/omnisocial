import pytest

from omnisocial.domain.redirect import ReturnUrlPolicy

POLICY = ReturnUrlPolicy.of(
    "https://app.ejemplo.com", "http://localhost:3000", "ftp://nada", "http://inseguro.com"
)


@pytest.mark.parametrize(
    "url",
    ["https://app.ejemplo.com/vuelta?x=1", "https://APP.ejemplo.com:443/", "http://localhost:3000/cb"],
)
def test_acepta_origenes_conocidos(url: str) -> None:
    assert POLICY.allows(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://app.ejemplo.com.malo.com/",
        "https://malo.com/?r=https://app.ejemplo.com",
        "http://app.ejemplo.com/",
        "http://localhost:4000/",
        "https://usuario@app.ejemplo.com/",
        "javascript:alert(1)",
        "//app.ejemplo.com/",
        "https://app.ejemplo.com:99999/",
        "http://inseguro.com/",
    ],
)
def test_rechaza_lo_demas(url: str) -> None:
    assert not POLICY.allows(url)
