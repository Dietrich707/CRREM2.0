"""Tests voor engine/crrem.py — gebruiken mock-data, geen afhankelijkheid van JSON-bestanden."""

import pytest
from unittest.mock import MagicMock

from engine.crrem import (
    BuildingInput,
    bereken_crrem,
    bereken_strandingpunt,
    interpoleer_pathway,
)
from engine.pathway_data import DataNietBeschikbaar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _maak_pathway_data(
    co2_anker: dict[int, float] | None = None,
    eui_anker: dict[int, float] | None = None,
    ef_overrides: dict[tuple, float] | None = None,
) -> MagicMock:
    """Bouwt een mock PathwayData met instelbare return-waarden."""
    co2_anker = co2_anker or {2020: 30.0, 2025: 25.0, 2030: 20.0, 2035: 15.0,
                               2040: 10.0, 2045: 5.0, 2050: 2.0}
    eui_anker = eui_anker or {2020: 120.0, 2025: 110.0, 2030: 100.0, 2035: 90.0,
                               2040: 80.0, 2045: 70.0, 2050: 60.0}
    ef_overrides = ef_overrides or {}

    pd = MagicMock()
    pd.valideer.return_value = True
    pd.get_co2_pathway.return_value = co2_anker
    pd.get_eui_pathway.return_value = eui_anker

    def ef_side_effect(land, drager, jaar):
        return ef_overrides.get((land, drager, jaar), 0.2)

    pd.get_emission_factor.side_effect = ef_side_effect
    return pd


def _basis_gebouw(**kwargs) -> BuildingInput:
    defaults = dict(
        gebouw_id="G001",
        naam="Testgebouw",
        land="BE",
        gebruik="office",
        scenario="1.5C",
        netto_vloeroppervlak_m2=1000.0,
        referentiejaar=2024,
        elektriciteit_kwh=50_000.0,
    )
    defaults.update(kwargs)
    return BuildingInput(**defaults)


# ---------------------------------------------------------------------------
# Test 1 — interpoleer_pathway: correcte tussenliggende waarden
# ---------------------------------------------------------------------------

def test_interpoleer_pathway_tussenliggende_waarden():
    anker = {2020: 10.0, 2025: 20.0}
    resultaat = interpoleer_pathway(anker, range(2020, 2026))

    assert resultaat[2020] == pytest.approx(10.0)
    assert resultaat[2022] == pytest.approx(14.0)  # 10 + 2/5 * 10
    assert resultaat[2023] == pytest.approx(16.0)  # 10 + 3/5 * 10
    assert resultaat[2025] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Test 2 — strandingpunt: gebouw al gestrand in referentiejaar
# ---------------------------------------------------------------------------

def test_bereken_strandingpunt_al_gestrand_in_referentiejaar():
    pathway = {2024: 30.0, 2025: 28.0, 2026: 26.0}
    # Gebouw zit op 50, ruim boven pathway van 30
    resultaat = bereken_strandingpunt(50.0, pathway, start_jaar=2024)
    assert resultaat == 2024


# ---------------------------------------------------------------------------
# Test 3 — strandingpunt: gebouw nooit gestrand
# ---------------------------------------------------------------------------

def test_bereken_strandingpunt_nooit_gestrand():
    pathway = {j: 100.0 for j in range(2024, 2051)}
    # Gebouw zit op 10, altijd ruim onder pathway
    resultaat = bereken_strandingpunt(10.0, pathway, start_jaar=2024)
    assert resultaat is None


# ---------------------------------------------------------------------------
# Test 4 — strandingpunt: gebouw strandt in exact jaar 5
# ---------------------------------------------------------------------------

def test_bereken_strandingpunt_strandt_in_jaar_5():
    # Pathway begint op 100 en daalt elk jaar met 10
    pathway = {2024 + i: 100.0 - i * 10 for i in range(10)}
    # Gebouw zit op 55 → pathway daalt tot 50 in jaar 5 (2029)
    resultaat = bereken_strandingpunt(55.0, pathway, start_jaar=2024)
    assert resultaat == 2029  # pathway[2029] = 100 - 5*10 = 50 < 55


# ---------------------------------------------------------------------------
# Test 5 — CO2 met alleen gas (EF constant) → CO2 constant over jaren
# ---------------------------------------------------------------------------

def test_co2_constant_bij_constant_gas_ef():
    # EF gas is identiek in elk jaar
    pd = _maak_pathway_data(
        ef_overrides={("BE", "aardgas", j): 0.2 for j in range(2020, 2051)}
    )
    gebouw = _basis_gebouw(elektriciteit_kwh=0.0, aardgas_kwh=100_000.0)
    resultaat = bereken_crrem(gebouw, pd)

    co2_waarden = [r["gebouw_co2"] for r in resultaat.tijdreeks]
    assert all(v == pytest.approx(co2_waarden[0]) for v in co2_waarden)


# ---------------------------------------------------------------------------
# Test 6 — CO2 daalt bij dalend EF elektriciteit (grid decarbonisering)
# ---------------------------------------------------------------------------

def test_co2_daalt_bij_dalend_elektriciteits_ef():
    # EF elektriciteit daalt lineair van 0.3 (2020) naar 0.05 (2050)
    ef_elek = {j: 0.3 - (j - 2020) * (0.25 / 30) for j in range(2020, 2051)}

    # Mock: get_emission_factor geeft dalende waarde terug afhankelijk van jaar
    pd = MagicMock()
    pd.valideer.return_value = True
    pd.get_co2_pathway.return_value = {2020: 30.0, 2050: 5.0}
    pd.get_eui_pathway.return_value = {2020: 120.0, 2050: 60.0}
    pd.get_emission_factor.side_effect = lambda land, drager, jaar: ef_elek.get(jaar, 0.1)

    gebouw = _basis_gebouw(elektriciteit_kwh=100_000.0, aardgas_kwh=0.0)
    resultaat = bereken_crrem(gebouw, pd)

    # CO2 in tijdreeks is constant (gebouwprofiel constant gehouden)
    # maar het referentiejaar CO2 is berekend met referentiejaar-EF
    ef_ref = ef_elek[gebouw.referentiejaar]
    verwachte_co2 = (100_000.0 * ef_ref) / 1000.0
    assert resultaat.co2_kgco2_m2 == pytest.approx(verwachte_co2, rel=1e-4)

    # Bevestig dat EF in referentiejaar kleiner is dan in 2020 (grid decarboniseert)
    assert ef_elek[2024] < ef_elek[2020]


# ---------------------------------------------------------------------------
# Test 7 — On-site hernieuwbaar telt mee voor EUI, niet voor CO2
# ---------------------------------------------------------------------------

def test_hernieuwbaar_telt_mee_voor_eui_niet_voor_co2():
    pd = _maak_pathway_data()
    # 50.000 kWh gas + 20.000 kWh hernieuwbaar onsite
    gebouw = _basis_gebouw(
        elektriciteit_kwh=0.0,
        aardgas_kwh=50_000.0,
        hernieuwbaar_onsite_kwh=20_000.0,
    )
    resultaat = bereken_crrem(gebouw, pd)

    # EUI telt beide: (50.000 + 20.000) / 1000 = 70 kWh/m²
    assert resultaat.eui_kwh_m2 == pytest.approx(70.0)

    # CO2 telt alleen gas (EF = 0.2): 50.000 * 0.2 / 1000 = 10 kgCO2/m²
    # hernieuwbaar heeft EF = 0 en staat niet in drager_verbruik
    assert resultaat.co2_kgco2_m2 == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Test 8 — PathwayData.valideer() geeft duidelijke foutmelding voor onbekend land
# ---------------------------------------------------------------------------

def test_valideer_onbekend_land_geeft_foutmelding():
    from engine.pathway_data import PathwayData, DataNietBeschikbaar
    import json
    import tempfile
    import os

    pathways = {
        "_meta": {"scenario_opties": ["1.5C", "2C"]},
        "landen": {
            "BE": {
                "label": "Belgium",
                "gebruikstypen": {
                    "office": {
                        "1.5C": {
                            "co2_pathway": {"2020": 30.0, "2050": 5.0},
                            "eui_pathway": {"2020": 120.0, "2050": 60.0},
                        }
                    }
                },
            }
        },
    }
    ef = {"_meta": {}, "landen": {"BE": {"aardgas": {"2020": 0.2, "2050": 0.2}}}}

    with tempfile.TemporaryDirectory() as tmp:
        p_path = os.path.join(tmp, "pathways.json")
        e_path = os.path.join(tmp, "emission_factors.json")
        with open(p_path, "w") as f:
            json.dump(pathways, f)
        with open(e_path, "w") as f:
            json.dump(ef, f)

        pd = PathwayData(pathways_pad=p_path, ef_pad=e_path)

        with pytest.raises(DataNietBeschikbaar) as exc_info:
            pd.valideer("XX", "office", "1.5C")

        assert "XX" in str(exc_info.value)
