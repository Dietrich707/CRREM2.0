"""Data-laag voor CRREM pathway- en emissiefactordata."""

from __future__ import annotations

import json
import os
from pathlib import Path


class DataNietBeschikbaar(ValueError):
    pass


class PathwayData:
    """Laadt en beheert CRREM pathway- en emissiefactordata uit JSON-bestanden."""

    def __init__(self, pathways_pad: str | None = None, ef_pad: str | None = None):
        base = Path(os.getenv("CRREM_DATA_PATH", "data/crrem_pathways"))
        pathways_pad = pathways_pad or base / "pathways.json"
        ef_pad = ef_pad or base / "emission_factors.json"

        with open(pathways_pad, encoding="utf-8") as f:
            self._pathways = json.load(f)
        with open(ef_pad, encoding="utf-8") as f:
            self._ef = json.load(f)

    # --- Pathway-accessors ---

    def get_co2_pathway(self, land: str, gebruik: str, scenario: str) -> dict[int, float]:
        """Geeft ankerwaarden CO2-pathway terug als {jaar: waarde}."""
        return self._haal_pathway_op(land, gebruik, scenario, "co2_pathway")

    def get_eui_pathway(self, land: str, gebruik: str, scenario: str) -> dict[int, float]:
        """Geeft ankerwaarden EUI-pathway terug als {jaar: waarde}."""
        return self._haal_pathway_op(land, gebruik, scenario, "eui_pathway")

    def _haal_pathway_op(
        self, land: str, gebruik: str, scenario: str, sleutel: str
    ) -> dict[int, float]:
        self.valideer(land, gebruik, scenario)
        data = (
            self._pathways["landen"][land]["gebruikstypen"][gebruik][scenario][sleutel]
        )
        return {int(k): float(v) for k, v in data.items()}

    # --- Emissiefactor-accessor ---

    def get_emission_factor(self, land: str, drager: str, jaar: int) -> float:
        """Geeft emissiefactor (kgCO2/kWh) voor drager in opgegeven jaar.
        Lineair geïnterpoleerd voor jaren tussen ankerpunten."""
        try:
            ef_land = self._ef["landen"][land]
        except KeyError:
            raise DataNietBeschikbaar(
                f"Geen emissiefactordata beschikbaar voor land '{land}'. "
                f"Beschikbare landen: {self._beschikbare_ef_landen()}"
            )

        if drager not in ef_land:
            raise DataNietBeschikbaar(
                f"Geen emissiefactor voor drager '{drager}' in land '{land}'. "
                f"Beschikbare dragers: {list(ef_land.keys())}"
            )

        ankerpunten = {int(k): v for k, v in ef_land[drager].items()}

        if not ankerpunten:
            raise DataNietBeschikbaar(
                f"Emissiefactordata voor '{drager}' in '{land}' is leeg. "
                "Vul aan vanuit CRREM Excel V2.04."
            )

        nul_waarden = [j for j, v in ankerpunten.items() if v is None]
        if nul_waarden:
            raise DataNietBeschikbaar(
                f"Emissiefactor voor '{drager}' in '{land}' bevat null-waarden "
                f"voor jaren {nul_waarden}. Vul aan vanuit CRREM Excel V2.04."
            )

        ankerpunten_float: dict[int, float] = {k: float(v) for k, v in ankerpunten.items()}
        jaren_gesorteerd = sorted(ankerpunten_float)

        if jaar <= jaren_gesorteerd[0]:
            return ankerpunten_float[jaren_gesorteerd[0]]
        if jaar >= jaren_gesorteerd[-1]:
            return ankerpunten_float[jaren_gesorteerd[-1]]

        for i in range(len(jaren_gesorteerd) - 1):
            j0, j1 = jaren_gesorteerd[i], jaren_gesorteerd[i + 1]
            if j0 <= jaar <= j1:
                t = (jaar - j0) / (j1 - j0)
                return ankerpunten_float[j0] + t * (ankerpunten_float[j1] - ankerpunten_float[j0])

        raise DataNietBeschikbaar(f"Kon emissiefactor niet bepalen voor jaar {jaar}.")

    # --- Introspectie ---

    def beschikbare_landen(self) -> list[str]:
        return [
            land
            for land, inhoud in self._pathways["landen"].items()
            if inhoud and "gebruikstypen" in inhoud
        ]

    def beschikbare_gebruikstypen(self, land: str) -> list[str]:
        try:
            typen = self._pathways["landen"][land].get("gebruikstypen", {})
        except KeyError:
            return []
        return [gt for gt, inhoud in typen.items() if inhoud]

    def beschikbare_scenarios(self) -> list[str]:
        return self._pathways["_meta"].get("scenario_opties", ["1.5C", "2C"])

    # --- Validatie ---

    def valideer(self, land: str, gebruik: str, scenario: str) -> bool:
        """Controleert of de combinatie beschikbaar en volledig ingevuld is."""
        landen_data = self._pathways.get("landen", {})

        if land not in landen_data or not landen_data[land]:
            raise DataNietBeschikbaar(
                f"Land '{land}' niet beschikbaar. "
                f"Beschikbare landen: {self.beschikbare_landen()}"
            )

        gebruikstypen = landen_data[land].get("gebruikstypen", {})
        if gebruik not in gebruikstypen or not gebruikstypen[gebruik]:
            raise DataNietBeschikbaar(
                f"Gebruikstype '{gebruik}' niet beschikbaar voor land '{land}'. "
                f"Beschikbare typen: {self.beschikbare_gebruikstypen(land)}"
            )

        scenario_data = gebruikstypen[gebruik].get(scenario)
        if scenario_data is None:
            raise DataNietBeschikbaar(
                f"Scenario '{scenario}' niet beschikbaar voor '{land}/{gebruik}'. "
                f"Beschikbare scenario's: {self.beschikbare_scenarios()}"
            )

        for sleutel in ("co2_pathway", "eui_pathway"):
            waarden = scenario_data.get(sleutel, {})
            if not waarden:
                raise DataNietBeschikbaar(
                    f"'{sleutel}' voor '{land}/{gebruik}/{scenario}' is leeg. "
                    "Vul aan vanuit CRREM Excel V2.04."
                )
            nul_waarden = [j for j, v in waarden.items() if v is None]
            if nul_waarden:
                raise DataNietBeschikbaar(
                    f"'{sleutel}' voor '{land}/{gebruik}/{scenario}' bevat null-waarden "
                    f"voor jaren {nul_waarden}. Vul aan vanuit CRREM Excel V2.04."
                )

        return True

    def _beschikbare_ef_landen(self) -> list[str]:
        return [
            land
            for land, inhoud in self._ef.get("landen", {}).items()
            if inhoud
        ]
