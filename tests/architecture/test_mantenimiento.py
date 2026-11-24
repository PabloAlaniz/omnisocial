"""Las herramientas de mantenimiento: la vigilancia de versiones y el resumen de las pruebas en vivo."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from omnisocial.domain.provider import Capability, ProviderId
from omnisocial.domain.spec import ApiPin, NetworkSpec, SupportLevel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import en_vivo  # noqa: E402  # los scripts viven fuera del paquete
import matriz  # noqa: E402
import versiones  # noqa: E402

TODAY = date(2026, 11, 24)


def _spec(name: str, api: ApiPin | None, support: SupportLevel = SupportLevel.EXPERIMENTAL) -> NetworkSpec:
    return NetworkSpec(
        id=ProviderId(name.lower()),
        name=name,
        capabilities=frozenset({Capability.LOGIN}),
        api=api,
        support=support,
        docs=f"docs/{name.lower()}.md",
    )


def test_se_avisa_de_un_retiro_cercano_y_de_lo_que_nadie_mira() -> None:
    networks = [
        _spec("Al día", ApiPin("v3", reviewed=date(2026, 9, 1))),
        _spec(
            "Por vencer",
            ApiPin("v24.0", reviewed=TODAY, sunset=date(2027, 1, 21), changelog="https://red/cambios"),
        ),
        _spec("Vencida", ApiPin("v1", reviewed=TODAY, sunset=date(2026, 11, 1))),
        _spec("Olvidada", ApiPin("v2", reviewed=date(2026, 1, 1))),
        _spec("Lejos", ApiPin("v9", reviewed=TODAY, sunset=date(2028, 1, 1))),
        _spec("Configurable", None),
    ]
    found = {finding.network: finding.problem for finding in versiones.findings(networks, TODAY)}
    assert set(found) == {"Por vencer", "Vencida", "Olvidada"}
    assert (
        found["Por vencer"] == "La versión v24.0 se retira el 2027-01-21 (58 días). Ver https://red/cambios."
    )
    assert "se retiró el 2026-11-01" in found["Vencida"]
    assert "desde el 2026-01-01" in found["Olvidada"]
    table = versiones.table(networks)
    assert "| Configurable | la elige quien configura | | |" in table
    assert "| Lejos | v9 | 2026-11-24 | 2028-01-01 |" in table
    assert "| Al día | v3 | 2026-09-01 | sin fecha |" in table


def test_las_versiones_de_hoy_estan_al_dia(capsys: pytest.CaptureFixture[str]) -> None:
    assert versiones.findings(matriz.specs(), TODAY) == []
    assert versiones.main([]) == 0
    assert "| Red | Versión | Revisada | Se retira |" in capsys.readouterr().out


def test_la_matriz_muestra_el_nivel_de_soporte() -> None:
    table = matriz.render([_spec("Probada", None, SupportLevel.VERIFIED), _spec("Nueva", None)])
    assert "| Red | Activo | Soporte |" in table
    assert "| [**Probada**](docs/probada.md) |  | verificada |" in table
    assert "| [**Nueva**](docs/nueva.md) |  | experimental |" in table
    assert set(matriz.SUPPORT) == set(SupportLevel)


def test_el_resumen_de_una_corrida_en_vivo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = tmp_path / "en-vivo.jsonl"
    run = {
        "network": "telegram",
        "at": "2026-11-24T05:17:00+00:00",
        "checks": [
            {"check": "conectar", "ok": True, "reason": None},
            {"check": "telegram_bot: publicar", "ok": False, "reason": "content_rejected"},
        ],
    }
    report.write_text(json.dumps(run) + "\n\n", encoding="utf-8")
    assert en_vivo.main([str(report)]) == 0
    out = capsys.readouterr().out
    assert "| telegram | conectar | bien |" in out
    assert "| telegram | telegram_bot: publicar | falló: content_rejected |" in out
    assert en_vivo.main([str(tmp_path / "no-existe.jsonl")]) == 0
    assert en_vivo.main([]) == 0
    assert "no dejó nada anotado" in capsys.readouterr().out
