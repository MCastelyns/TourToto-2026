# Tourtoto 2026

Automatisch klassement voor onze Tour de France-poule (Hoofdpoule + Pannenkoekenpoule),
gebaseerd op `source_files/Tour toto 2026 regelement.docx`.

## Hoe het werkt

```
source_files/                  originele docx/xlsx (niet bewerken, alleen als bron)
data/teams_master.json         merkploegen-rooster (1-8 per team), geparsed uit Merkploegen 2026.docx
data/participants/<naam>.json  ieders hoofdploeg/pannenkoeken-keuzes + jokeretappe, geparsed uit de xlsx
data/name_aliases.json         handmatig bevestigde correcties voor typefouten in rennersnamen
data/name_dismissed.json       namen die je in de admin-GUI hebt genegeerd (blijven 0 punten scoren)
data/rider_bib_map.json        merkploegen-naam -> officieel rugnummer (voor het koppelen aan scrape-resultaten)
data/rider_bib_map_overrides.json  handmatig bevestigde rugnummer-koppelingen (via admin-GUI)
data/results/stage_NN.json     uitslag per etappe (via scrape_results.py of handmatig, zie data/results/README.md)
data/results/final.json        eindklassementen + antwoorden bonusvragen (aan het eind van de Tour)
data/computed/standings.json   berekende output van scoring.py
data/admin_password.json       admin-wachtwoord (platte tekst, .gitignored, nooit committen)
data/flask_secret_key.txt      sessie-sleutel voor Flask (auto-gegenereerd, .gitignored)
docs/index.html                de webpagina (GitHub Pages serveert deze map), gegenereerd door generate_site.py
```

## Gebruik

Eén Flask-app (`scripts/app.py`) bedient alles:
- `/` — publieke, alleen-lezen dashboard (`docs/index.html`)
- `/admin` — wachtwoord-beveiligd adminpaneel (rennersnamen oplossen, rugnummers
  koppelen, ploegen bewerken, site herbouwen)

```
python scripts/app.py
-> open http://127.0.0.1:5000        (publieke site)
-> open http://127.0.0.1:5000/admin  (vraagt de eerste keer om een wachtwoord in te stellen)
```

In `/admin` kun je:
- een nieuwe etappe-uitslag laden — twee opties, zie "Nieuwe etappe laden" hieronder
- per onopgeloste naam de juiste renner kiezen ("Oplossen", schrijft naar `name_aliases.json`)
  of aangeven dat het geen typefout is ("Negeren", schrijft naar `name_dismissed.json`)
- per nog niet aan een rugnummer gekoppelde renner de juiste ploeggenoot kiezen ("Koppelen")
- per deelnemer de hoofdploeg/pannenkoekenploeg, jokeretappe en bonusantwoorden bewerken
- op "Herbouw site" klikken om alles opnieuw te berekenen — direct zichtbaar op "Bekijk site" (`/`)

Het wachtwoord staat in platte tekst in `data/admin_password.json` — bewust simpel
gehouden (geen accounts, geen encryptie), bedoeld om willekeurige bezoekers tegen te
houden, niet een serieuze aanvaller.

### Nieuwe etappe laden

Bovenaan `/admin` staan twee manieren om een etappe-uitslag te laden (beide herberekenen
en herbouwen de site automatisch na afloop):

1. **"Etappe ophalen"** — vul het etappenummer in en klik. De server haalt de uitslag
   zelf op bij de Tour-API. Werkt alleen als de server (bij hosting op bv. PythonAnywhere)
   uitgaand internet naar `racecenter.letour.fr` mag — dat weet je pas zeker als je het
   geprobeerd hebt.
2. **"Bestand uploaden"** — werkt altijd, ongeacht netwerkbeperkingen. Draai lokaal op je
   eigen pc `python scripts/scrape_results.py --stage N`, en upload het resulterende
   `data/results/stage_NN.json`-bestand via het formulier. Handig als optie 1 niet werkt,
   of als je een handmatig aangepast `stage_NN.json`-bestand (zie `data/results/README.md`)
   wil doorzetten.

## Hosten (PythonAnywhere, gratis)

Data leeft in lokale JSON-bestanden die het adminpaneel bewerkt, dus een host met
*persistente* schijfruimte is belangrijk — de meeste gratis hosting-platforms wissen
lokale bestanden bij elke herstart. PythonAnywhere's gratis "Beginner"-tier bewaart
bestanden wel gewoon.

1. Maak een gratis account op pythonanywhere.com.
2. Open een Bash-console daar en clone/upload deze projectmap (bijv. via git, of
   upload de zip via de Files-tab).
3. In die console: `pip install --user -r requirements.txt`
4. Ga naar de **Web**-tab → "Add a new web app" → Flask → kies de Python-versie.
5. Zet in de WSGI-configuratie (link staat bovenaan de Web-tab):
   ```python
   import sys
   path = '/home/JOUWGEBRUIKERSNAAM/tour-de-france/scripts'
   if path not in sys.path:
       sys.path.insert(0, path)
   from app import app as application
   ```
6. Zet "Source code" / "Working directory" op de map met `scripts/` erin.
7. Klik **Reload** (groene knop bovenaan de Web-tab) — je site staat nu op
   `jouwgebruikersnaam.pythonanywhere.com`, en `/admin` vraagt om een wachtwoord in te stellen.
8. **Na elke wijziging** (nieuwe etappe-uitslag, codewijziging): update de bestanden op
   PythonAnywhere (git pull, of via de admin-GUI zelf als het om ploegwijzigingen gaat)
   en klik nogmaals **Reload** — dat is de enige stap om een codewijziging live te krijgen.

De scraper (`scrape_results.py`) hoeft niet op PythonAnywhere te draaien — de gratis
tier beperkt uitgaande internettoegang tot een whitelist. Blijf die lokaal draaien zoals
nu, en zet het resulterende `data/results/stage_NN.json` op de server (upload, of via git).

## Scraper (automatisch etappe-uitslagen ophalen)

Bron: `racecenter.letour.fr` — de officiële Race Center-app van de Tour. Geen publieke
documentatie, maar de site laadt haar data via een JSON-API (`/api/...`) die we door de
JS-bundle van de app te lezen hebben gevonden. Zie `scripts/api_client.py` voor de
ontdekte endpoints.

**Eenmalig per seizoen** — koppel elke renner uit de merkploegen-lijst aan zijn officiële
rugnummer (nodig omdat de API renners alleen bij rugnummer identificeert):
```
python scripts/build_bib_map.py
```
Matcht automatisch op achternaam (spellingsverschillen, initialen en samengestelde
achternamen worden genegeerd). Wat overblijft (typefouten, dubbele achternamen zoals de
gebroeders Johannessen, of corrupte tekens in de officiële data zelf) koppel je handmatig
via de "Koppeling met startlijst" sectie op /admin.

**Na elke etappe:**
```
python scripts/scrape_results.py --stage 1
python scripts/build.py
```
Haalt de dag-/algemeenklassementen op (geel/groen/bol/wit) en schrijft
`data/results/stage_NN.json`. Bekende beperking: op een ploegentijdrit-etappe bestaat er
geen individuele etappe-uitslag (`ite`) bij de API, alleen een ploegresultaat. **Uitzondering
etappe 1**: het algemeen klassement (`itg`) na etappe 1 is wiskundig identiek aan de
dagresultaat van etappe 1 (er is nog niets opgeteld), dus daar gebruikt de scraper `itg`
automatisch als vervanging. Een ploegentijdrit op een latere etappe (waar GC wel al
opgebouwd is uit eerdere etappes) heeft dit probleem niet opgelost — daar blijft
`stage_result` leeg totdat de groep een regel afspreekt.

## Nog te doen

- **Bonusvragen-puntentelling**: de regels noemen alleen "max 25 punten" voor de
  tijdsverschil- en uitvallers-vraag, zonder de precieze afbouw-formule. `scripts/scoring.py`
  gebruikt nu voorlopig een lineaire aftrek (`25 - |verschil|`) — met de groep afstemmen.
- **TTT-etappepunten op een latere etappe** (zie hierboven) — etappe 1 is al opgelost.
- **~9 onopgeloste rennersnamen** en **~9 niet-gekoppelde rugnummers** (open /admin
  om te zien welke) — vooral bij Sepp's keuzes en een handvol echte typefouten/naamscorruptie
  in de brondata. Navragen bij die deelnemers of gewoon oplossen via de admin-GUI.
