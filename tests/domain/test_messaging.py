from datetime import UTC, datetime, timedelta

from omnisocial.domain.messaging import Message, ReplyWindow, last_inbound_at

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)


def _msg(hours_ago: float, *, from_asset: bool) -> Message:
    return Message("m", "c", NOW - timedelta(hours=hours_ago), "s", "hola", from_asset=from_asset)


def test_el_ultimo_entrante_ignora_lo_que_mando_el_activo() -> None:
    messages = [_msg(30, from_asset=False), _msg(2, from_asset=False), _msg(1, from_asset=True)]
    assert last_inbound_at(messages) == NOW - timedelta(hours=2)
    assert last_inbound_at([_msg(1, from_asset=True)]) is None


def test_la_ventana_de_24_horas() -> None:
    window = ReplyWindow(timedelta(hours=24))
    assert window.allows(NOW - timedelta(hours=23), NOW)
    assert window.allows(NOW - timedelta(hours=24), NOW)
    assert not window.allows(NOW - timedelta(hours=25), NOW)
    assert not window.allows(None, NOW)


def test_sin_limite_siempre_permite() -> None:
    assert ReplyWindow(None).allows(None, NOW)
