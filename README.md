# bok_to_docx — FastAPI-tjeneste for HTML/XHTML → DOCX (Pandoc)

Dette repoet inneholder en liten mikrotjeneste som tar imot en HTML/XHTML-fil og returnerer en DOCX ved å kjøre **Pandoc** under panseret. API-et er bygget med **FastAPI** og kjører i en Docker-container.

> Kort fortalt: **POST /convert** med en HTML/XHTML-fil ⇒ du får en `application/vnd.openxmlformats-officedocument.wordprocessingml.document`-strøm tilbake.

---

## Innhold

- [Arkitektur og flyt](#arkitektur-og-flyt)
- [API](#api)
  - [Helsesjekk](#helsesjekk)
  - [Konvertering](#konvertering)
- [Bygg og kjøring](#bygg-og-kjøring)
  - [Kjøre lokalt uten Docker](#kjøre-lokalt-uten-docker)
  - [Kjøre med Docker](#kjøre-med-docker)
  - [Kjøre med Docker Compose](#kjøre-med-docker-compose)
- [Mapper og vedvarende data](#mapper-og-vedvarende-data)
- [Dockerfile-detaljer](#dockerfile-detaljer)
- [Avhengigheter](#avhengigheter)
- [Eksempler på bruk](#eksempler-på-bruk)
- [Feilhåndtering og headers](#feilhåndtering-og-headers)
- [Sikkerhet og produksjonsråd](#sikkerhet-og-produksjonsråd)
- [Vanlige problemer](#vanlige-problemer)
- [Videre arbeid / TODO](#videre-arbeid--todo)

---

## Arkitektur og flyt

- **app.py** definerer en FastAPI-app (`app = FastAPI(title="bok_to_docx", version="1.0.0")`) med to endepunkter: `GET /health` og `POST /convert`.
- Ved opplasting opprettes en midlertidig arbeidsmappe under `/data/tmp`. Inndatafilen lagres her.
- Konverteringen kalles via en hjelpefunksjon `run_pandoc_to_docx(...)` som bygger en Pandoc-kommando tilsvarende:

  ```bash
  pandoc -s --from=html --to=docx --resource-path=<arbeidsmappe>          [--reference-doc=<sti-til-mal.docx>]          -o <utfil.docx> <infil.html>
  ```

  *`--resource-path` settes slik at relative ressurser (bilder, CSS o.l.) kan finnes i samme mappe som inndata.*
- Resultatet streames direkte tilbake til klienten. Hvis du ønsker å lagre en kopi, kan du be om det med `save_to_disk=true`. Da skrives filen til `/data/out` i containeren.
- Etter at strømmen er sendt, ryddes den midlertidige mappen.

> Merk: Hvis du angir `reference_doc` (Pandoc sin **reference DOCX**), tolkes relative stier i forhold til `/app` i containeren. Fins ikke filen, fortsetter konverteringen **uten** å feile, men uten referansemal.

---

## API

### Helsesjekk

**`GET /health`**  
Returnerer `{"status":"ok"}`. Brukes også av Docker `HEALTHCHECK`.

### Konvertering

**`POST /convert`** (multipart/form-data)

Form‑data:
- `file` (påkrevd): Upload av HTML/XHTML (Content-Type kan være `text/html` eller `application/xhtml+xml`).

Query‑parametre:
- `save_to_disk` (bool, default `false`): Hvis `true`, lagre også resultatet til `/data/out` i containeren.
- `reference_doc` (str, optional): Sti til en Pandoc reference‑mal (`--reference-doc`). Relativ sti tolkes fra `/app` i containeren.

Respons:
- **Body**: Strøm av DOCX (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`).
- **Headers**:
  - `Content-Disposition: attachment; filename="<navn>.docx"`
  - `X-Converter: pandoc`
  - `X-Saved-To: <full sti>` når `save_to_disk=true` og lagring lyktes (ellers `failed`).

Feil:
- `400` når filnavn mangler eller opplasting er ugyldig.
- Andre feil under konvertering vil typisk gi `500` (avhenger av underliggende Pandoc/OS-feil).

OpenAPI/Swagger finnes på **`/docs`**, og ReDoc på **`/redoc`** når appen kjører.

---

## Bygg og kjøring

### Kjøre lokalt uten Docker

1. Installer avhengigheter (Python 3.12):  
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   pip install uvicorn  # nødvendig for å starte serveren
   ```
2. Start appen:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port 9004 --reload
   ```
3. Besøk `http://localhost:9004/docs`

> `requirements.txt` inneholder **FastAPI/Starlette** og relaterte pakker, men **Uvicorn** mangler og må installeres i utviklingsmodus (se over).

### Kjøre med Docker

Bygg:
```bash
docker build -t bok-to-docx .
```

Kjør (port **9004**, som i Dockerfile):
```bash
docker run --rm -p 9004:9004 -v "$PWD/volumes:/data" bok-to-docx
```
Åpne: <http://localhost:9004/docs>

> I `build.sh` står det en kommentert eksempel‑kjøring med port **8020**. Containeren lytter faktisk på **9004**, så bruk `-p 9004:9004`.

### Kjøre med Docker Compose

Prosjektet inkluderer en minimalistisk `docker-compose.yml` med én tjeneste (`bok_to_docx`) og et **eksternt** nettverk kalt `llsyn_production_system_llsyn_network`. Denne er ment å koble seg på et overordnet system og eksponerer ikke porter som standard. (Se filen for detaljer og kommenterte felter for `ports:` og `environment:`.)

Et praktisk lokalt oppsett er å legge til en **override**‑fil for utvikling, f.eks. `docker-compose.override.yml`:

```yaml
services:
  bok_to_docx:
    ports:
      - "9004:9004"
    volumes:
      - ./volumes:/data
```

Start:
```bash
docker compose up --build
```

> Sørg for at det eksterne nettverket eksisterer, eller fjern/endre nettverksseksjonen i Compose for å kjøre helt isolert lokalt.

---

## Mapper og vedvarende data

- **/app**: Kildekode og eventuelle maler (f.eks. `templates/reference.docx`).
- **/data/tmp**: Midlertidige arbeidsmapper pr. jobb (auto‑ryddes).
- **/data/out**: Valgfri perma‑lagring når `save_to_disk=true`.  
  Mount gjerne en vertsmappedir hit i utvikling/produksjon, f.eks. `-v "$PWD/volumes:/data"`.

---

## Dockerfile‑detaljer

- Basert på `python:3.12-slim` og installerer **pandoc**, `curl` og **tini**.
- Kjører som ikke‑root‑bruker `appuser` og eksponerer port **9004**.
- Har `HEALTHCHECK` som pinger `http://127.0.0.1:9004/health`.
- Starter med:
  ```bash
  python -m uvicorn app:app --host 0.0.0.0 --port 9004
  ```

> I den vedlagte Dockerfile er seksjonen for `pip install` markert med `...`. Sørg for å installere både prosjektets avhengigheter og Uvicorn, f.eks.:
>
> ```Dockerfile
> COPY requirements.txt /app/
> RUN pip install --no-cache-dir -r /app/requirements.txt uvicorn
> ```
>
> Hvis du har malfiler (reference DOCX) eller andre ressurser, legg dem i `/app` og referer dem via `reference_doc`.

---

## Avhengigheter

- Python‑pakker fastsatt i `requirements.txt` (bl.a. **fastapi**, **starlette**, **python-multipart**, **lxml**, **beautifulsoup4**). I tillegg trenger du **uvicorn** når du kjører appen.  
- System‑pakker: **pandoc** må være tilgjengelig i PATH (installeres i Docker‑bildet).

> **NB:** `python-docx`, `numpy`, `pandas` er listet, men brukes ikke i kjernen av API‑flyten pr. nå. De kan fjernes for et tynnere image dersom de ikke er planlagt brukt.

---

## Eksempler på bruk

**1) Konverter en lokal XHTML til DOCX og lagre til disk i containeren**

```bash
curl -sS -X POST "http://localhost:9004/convert?save_to_disk=true"   -F "file=@files/eksempel.xhtml;type=application/xhtml+xml"   -o out.docx -D -
```

**2) Bruk en Pandoc reference DOCX (relativ til /app)**

```bash
curl -sS -X POST "http://localhost:9004/convert?reference_doc=templates/reference.docx"   -F "file=@files/eksempel.html;type=text/html"   -o out.docx -D -
```

**3) Hent helsesjekk**

```bash
curl -sS http://localhost:9004/health
```

---

## Feilhåndtering og headers

- Ved suksess returneres en strøm av DOCX med `Content-Disposition: attachment` slik at filen kan lagres direkte fra klient.
- Headeren `X-Converter: pandoc` forteller hvilken konverter som ble brukt.
- Dersom du ba om skrift til disk (`save_to_disk=true`), får du header `X-Saved-To` med full sti – eller `failed` om lagringen feilet.
- Hvis `reference_doc` ikke finnes, kjøres konverteringen **videre uten mal** (dette er ikke en feiltilstand per nå).

---

## Sikkerhet og produksjonsråd

- **Ikke** eksponer tjenesten direkte på internett uten front (rate‑limit, autentisering, WAF).
- Sett grenser for lastestørrelse og tidouts (FastAPI/Uvicorn/traefik/nginx) for å forhindre DoS via store filer.
- Kjør i egen nettverks‑/namespace‑kontekst og med ikke‑root‑bruker (gjort i Dockerfile).
- Overvåk `HEALTHCHECK` og legg på liveness/readiness‑prober i orkestrering.
- Logg på omvendt proxy‑nivå; vurder strukturert logging i appen dersom behov.

---

## Vanlige problemer

- **Bygget image, men containeren starter ikke (mangler uvicorn):** legg til `uvicorn` i Docker‑installasjonen (se over) eller i `requirements.txt`.
- **`/docs` svarer ikke lokalt:** sjekk at du eksponerer port **9004** (ikke 8020) og at firewall tillater tilkobling.
- **`reference_doc` funker ikke:** bekreft at malen finnes i containerens `/app` (ved relativ sti). Bruk absolutt sti hvis du mount-er andre steder.
- **Ressurser (bilder/CSS) mangler i DOCX:** Pandoc må finne ressurser via `--resource-path`. Sørg for at de ligger i samme mappe som den opplastede fila, eller bruk absolutte URL-er/data‑URI.

---

## Videre arbeid / TODO

- [ ] Legg til `uvicorn` i `requirements.txt` eller Dockerfile‑installasjonen.
- [ ] Fullfør `Dockerfile` (erstatt `...` med `pip install`).  
- [ ] Vurdér å støtte opplasting av **flere** filer (arkiv) slik at lokale bilder/CSS følger med.
- [ ] Innfør størrelsesgrenser, autentisering (API‑nøkkel/OAuth) og rate‑begrensning hvis dette skal brukes utenfor et lukket nett.
- [ ] Strukturert logging og korrelerings‑IDer for enklere feilsøking i produksjon.
- [ ] Mulighet for å gi **egendefinert filnavn** i responsen.
