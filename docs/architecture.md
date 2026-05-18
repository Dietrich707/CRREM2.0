# CRREM 2.0 — Architectuur

## Mappenstructuur
crrem2/
├── CLAUDE.md
├── .env                    # nooit in git
├── .env.example
├── requirements.txt
├── app.py                  # Streamlit entry point
├── data/
│   ├── input/              # originele inputbestanden van gebruiker (PDF, Excel) — nooit overschreven
│   ├── stage1/             # output stap 1: raw_extractions.csv
│   ├── stage2/             # output stap 2: normalized_consumption.csv
│   ├── stage3/             # output stap 3: crrem_results.json
│   ├── output/             # eindrapport Word-bestand
│   └── crrem_pathways/     # pathway- en emissiefactordata (JSON, te vullen vanuit CRREM Excel V2.04)
│       ├── pathways.json
│       └── emission_factors.json
├── agents/
│   ├── extractor.py        # stap 1
│   └── normalizer.py       # stap 2
├── engine/
│   ├── crrem.py            # stap 3 — berekeningsengine, geen landdata
│   ├── pathway_data.py     # stap 3 — laadt pathway- en emissiefactordata uit JSON
│   └── measures.py         # stap 4 + 5
├── report/
│   └── generator.py        # stap 6
├── tests/
└── logs/

## Stap 1 — Extractie-agent (agents/extractor.py)
Leest alle bestanden in data/input/ (PDF en Excel).
Gebruikt Claude API voor extractie van: energiedrager, periode_start,
periode_eind, verbruik, eenheid, bron_type, extractie_confidence.
Output: data/stage1/raw_extractions.csv

Schema raw_extractions.csv:
gebouw_id, bestand, energiedrager, periode_start (YYYY-MM-DD),
periode_eind (YYYY-MM-DD), verbruik, eenheid, bron_type (pdf/excel),
extractie_confidence (high/medium/low)

## Stap 2 — Normalisatie-agent (agents/normalizer.py)
Leest data/stage1/raw_extractions.csv. Aggregeert per maand, sorteert chronologisch,
selecteert meest aaneengesloten periode (bij voorkeur 12 maanden).
Ontbrekende maanden worden geïnterpoleerd conform CRREM-methodologie.
Niet-interpoleerbare periodes worden geflagd en gemeld aan de gebruiker.
Output: data/stage2/normalized_consumption.csv

Schema normalized_consumption.csv:
gebouw_id, jaar, maand, energiedrager, verbruik_kwh,
geinterpoleerd (bool), interpolatie_methode, flag

## Stap 3 — CRREM berekeningsengine (engine/crrem.py)
Leest data/stage2/normalized_consumption.csv + gebouwparameters.
Berekent kWh/m²/jaar per energiedrager.
Past CRREM Belgium Office 1.5°C-pad toe (V2.04).
Berekent strandingpunt en jaarlijkse overschrijding.
Output: data/stage3/crrem_results.json

## Stap 4 — Renovatiekeuzemenu (engine/measures.py + Streamlit UI)
Maatregelbibliotheek met per maatregel:
- Energiereductie in kWh/m²
- Kostindicatie
- Toepassingsvoorwaarden
- Finetuning-parameters (bv. isolatiedikte, WP-capaciteitsfractie)

## Stap 5 — Herontwikkelde analyse (engine/crrem.py)
Herberekent strandingpunt na toepassing van gekozen maatregelen.
Toont vergelijking voor/na op dezelfde grafiek.

## Stap 6 — Rapportgeneratie (report/generator.py)
Word-rapport via python-docx in Bopro-huisstijl.
Inhoud: gebouwfiche, verbruiksoverzicht, huidig strandingpunt,
renovatiescenario, nieuw strandingpunt, gebruikte aannames.

## Deployment
Lokaal-first. Deployment-ready voor Streamlit Cloud of VPS.
Geen hardcoded paden. Configuratie via .env.
