# CRREM 2.0

Streamlit webapp voor CRREM-analyse van gebouwen.
Extraheert energieverbruik uit PDF en Excel, berekent strandingpunt,
stelt renovatiemaatregelen voor, genereert rapport in Bopro-huisstijl.

Details: zie docs/architecture.md
Beslissingen: zie docs/decisions.log

## Stack
- Python 3.11+, Streamlit, Anthropic API, pandas, openpyxl, python-docx, pytest, python-dotenv

## Werkafspraken
- Plan altijd eerst wat je gaat bouwen en wacht op bevestiging voor je begint
- Bouw één stap volledig af voor je naar de volgende gaat
- Wijzig nooit CRREM-berekeningslogica of maatregelbibliotheek zonder expliciete instructie
- Mislukte extracties loggen in logs/, nooit stilzwijgend overslaan
- Elke module krijgt een testfile in tests/
- Alle configuratie via .env, nooit hardcoded
- Voeg elke architectuurbeslissing toe aan docs/decisions.log
