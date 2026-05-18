"""CRREM V2.0 berekeningsengine — generiek, geen hardcoded land/gebruik/scenario."""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.pathway_data import PathwayData

JAREN = range(2020, 2051)

# Dragers die meetellen voor EUI maar EF = 0 hebben
_DRAGERS_EF_NUL = {"hernieuwbaar_onsite"}

# Dragers die via emissiefactordata opgezocht worden
_DRAGER_NAAR_EF_SLEUTEL = {
    "elektriciteit": "elektriciteit",
    "aardgas": "aardgas",
    "stookolie": "stookolie",
    "warmtenet": "warmtenet",
    "overige": "overige",
}


@dataclass
class BuildingInput:
    gebouw_id: str
    naam: str
    land: str
    gebruik: str
    scenario: str
    netto_vloeroppervlak_m2: float
    referentiejaar: int

    elektriciteit_kwh: float = 0.0
    aardgas_kwh: float = 0.0
    stookolie_kwh: float = 0.0
    warmtenet_kwh: float = 0.0
    hernieuwbaar_onsite_kwh: float = 0.0
    overige_kwh: float = 0.0

    klimaatcorrectie: bool = False


@dataclass
class CRREMResult:
    gebouw_id: str
    naam: str
    land: str
    gebruik: str
    scenario: str
    referentiejaar: int

    eui_kwh_m2: float
    co2_kgco2_m2: float

    pathway_eui_kwh_m2: float
    pathway_co2_kgco2_m2: float

    overschrijding_eui_pct: float
    overschrijding_co2_pct: float

    strandingpunt_energie: int | None
    strandingpunt_co2: int | None

    tijdreeks: list[dict] = field(default_factory=list)
    emissiefactoren_gebruikt: dict = field(default_factory=dict)
    aannames: list[str] = field(default_factory=list)
    verificatie_vereist: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Publieke functies
# ---------------------------------------------------------------------------

def interpoleer_pathway(ankerwaarden: dict[int, float], jaren: range) -> dict[int, float]:
    """Lineaire interpolatie van pathway-ankerwaarden naar jaarlijkse reeks.

    Jaren buiten het bereik van de ankerwaarden worden platgehouden op de
    eerste of laatste ankerwaarde.
    """
    if not ankerwaarden:
        raise ValueError("ankerwaarden mag niet leeg zijn.")

    gesorteerd = sorted(ankerwaarden)
    resultaat: dict[int, float] = {}

    for jaar in jaren:
        if jaar <= gesorteerd[0]:
            resultaat[jaar] = ankerwaarden[gesorteerd[0]]
        elif jaar >= gesorteerd[-1]:
            resultaat[jaar] = ankerwaarden[gesorteerd[-1]]
        else:
            for i in range(len(gesorteerd) - 1):
                j0, j1 = gesorteerd[i], gesorteerd[i + 1]
                if j0 <= jaar <= j1:
                    t = (jaar - j0) / (j1 - j0)
                    resultaat[jaar] = ankerwaarden[j0] + t * (ankerwaarden[j1] - ankerwaarden[j0])
                    break

    return resultaat


def bereken_strandingpunt(
    gebouw_profiel: float,
    pathway_reeks: dict[int, float],
    start_jaar: int,
) -> int | None:
    """Geeft het eerste jaar terug waar gebouw boven de pathway uitkomt.

    Retourneert start_jaar als het gebouw daar al gestrand is.
    Retourneert None als het gebouw compliant blijft t/m 2050.
    """
    for jaar in sorted(j for j in pathway_reeks if j >= start_jaar):
        if gebouw_profiel > pathway_reeks[jaar]:
            return jaar
    return None


def bereken_crrem(building: BuildingInput, pathway_data: PathwayData) -> CRREMResult:
    """Hoofdfunctie. Berekent EUI, CO2, strandingpunten en tijdreeks.

    Werkt voor elk land/gebruik/scenario waarvoor pathway_data beschikbaar is.
    """
    pathway_data.valideer(building.land, building.gebruik, building.scenario)

    aannames: list[str] = []
    verificatie_vereist: list[str] = []

    # --- Stap 1: Interpoleer pathways naar jaarreeks ---
    co2_anker = pathway_data.get_co2_pathway(building.land, building.gebruik, building.scenario)
    eui_anker = pathway_data.get_eui_pathway(building.land, building.gebruik, building.scenario)

    if min(co2_anker) > list(JAREN)[0] or max(co2_anker) < list(JAREN)[-1]:
        aannames.append(
            "Pathway-ankerwaarden dekken 2020-2050 niet volledig: "
            "waarden buiten bereik zijn platgehouden."
        )

    co2_pathway_reeks = interpoleer_pathway(co2_anker, JAREN)
    eui_pathway_reeks = interpoleer_pathway(eui_anker, JAREN)

    # --- Stap 2: Emissiefactoren ophalen voor referentiejaar ---
    drager_verbruik = {
        "elektriciteit": building.elektriciteit_kwh,
        "aardgas": building.aardgas_kwh,
        "stookolie": building.stookolie_kwh,
        "warmtenet": building.warmtenet_kwh,
        "overige": building.overige_kwh,
    }

    ef_referentie: dict[str, float] = {}
    for drager, verbruik in drager_verbruik.items():
        if verbruik > 0:
            ef = pathway_data.get_emission_factor(building.land, drager, building.referentiejaar)
            ef_referentie[drager] = ef

    # --- Stap 3: EUI (eindenergie, incl. hernieuwbaar) ---
    totaal_kwh = (
        building.elektriciteit_kwh
        + building.aardgas_kwh
        + building.stookolie_kwh
        + building.warmtenet_kwh
        + building.hernieuwbaar_onsite_kwh
        + building.overige_kwh
    )
    eui = totaal_kwh / building.netto_vloeroppervlak_m2

    aannames.append("EUI = site-eindenergie (incl. hernieuwbaar onsite), niet primaire energie.")
    aannames.append("On-site hernieuwbaar heeft EF = 0 (telt niet mee voor CO2).")
    if building.klimaatcorrectie:
        verificatie_vereist.append("Klimaatcorrectie aangevinkt maar nog niet geïmplementeerd.")

    # --- Stap 4: CO2 in referentiejaar ---
    co2_kwh = sum(
        verbruik * ef_referentie.get(drager, 0.0)
        for drager, verbruik in drager_verbruik.items()
    )
    co2 = co2_kwh / building.netto_vloeroppervlak_m2

    # --- Stap 5: Pathway-waarden in referentiejaar ---
    pathway_eui_ref = eui_pathway_reeks[building.referentiejaar]
    pathway_co2_ref = co2_pathway_reeks[building.referentiejaar]

    overschrijding_eui = _overschrijding_pct(eui, pathway_eui_ref)
    overschrijding_co2 = _overschrijding_pct(co2, pathway_co2_ref)

    # --- Stap 6: Strandingpunten ---
    strandingpunt_energie = bereken_strandingpunt(eui, eui_pathway_reeks, building.referentiejaar)
    strandingpunt_co2 = bereken_strandingpunt(co2, co2_pathway_reeks, building.referentiejaar)

    # --- Stap 7: Tijdreeks 2020-2050 (gebouwprofiel constant) ---
    tijdreeks = _bouw_tijdreeks(
        eui, co2, eui_pathway_reeks, co2_pathway_reeks, building.referentiejaar
    )

    return CRREMResult(
        gebouw_id=building.gebouw_id,
        naam=building.naam,
        land=building.land,
        gebruik=building.gebruik,
        scenario=building.scenario,
        referentiejaar=building.referentiejaar,
        eui_kwh_m2=round(eui, 4),
        co2_kgco2_m2=round(co2, 4),
        pathway_eui_kwh_m2=round(pathway_eui_ref, 4),
        pathway_co2_kgco2_m2=round(pathway_co2_ref, 4),
        overschrijding_eui_pct=round(overschrijding_eui, 2),
        overschrijding_co2_pct=round(overschrijding_co2, 2),
        strandingpunt_energie=strandingpunt_energie,
        strandingpunt_co2=strandingpunt_co2,
        tijdreeks=tijdreeks,
        emissiefactoren_gebruikt=ef_referentie,
        aannames=aannames,
        verificatie_vereist=verificatie_vereist,
    )


# ---------------------------------------------------------------------------
# Interne hulpfuncties
# ---------------------------------------------------------------------------

def _overschrijding_pct(gebouw: float, pathway: float) -> float:
    if pathway == 0:
        return 0.0
    return ((gebouw - pathway) / pathway) * 100


def _bouw_tijdreeks(
    eui: float,
    co2: float,
    eui_pathway: dict[int, float],
    co2_pathway: dict[int, float],
    referentiejaar: int,
) -> list[dict]:
    reeks = []
    for jaar in JAREN:
        p_co2 = co2_pathway[jaar]
        p_eui = eui_pathway[jaar]
        reeks.append({
            "jaar": jaar,
            "pathway_co2": round(p_co2, 4),
            "pathway_eui": round(p_eui, 4),
            "gebouw_co2": round(co2, 4),
            "gebouw_eui": round(eui, 4),
            "gestrand_co2": co2 > p_co2,
            "gestrand_eui": eui > p_eui,
        })
    return reeks
