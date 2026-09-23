*[Leia em português](README.md)*

# sales-engine

End-to-end B2B prospecting pipeline: company discovery by segment,
contact enrichment and verification, AI-driven lead scoring, first
contact by email with reputation warm-up, and an AI-assisted WhatsApp
stage (human-in-the-loop copilot or automatic, depending on
configuration) — all on a single Postgres database, with an API and a
web interface to track the funnel (list, Kanban, map, metrics, export).

Personal B2B prospecting project, configurable per niche
(`config/nichos.yaml`). The commercial policy (packages, prices,
discounts) is defined in `etapa7_whatsapp/politica.py` — see the
"Commercial policy" section below.

## Architecture

```
Stage 1 — Search            Active CNPJ by CNAE (Brazilian Federal Revenue via Apify)
Stage 2 — Validation        Google Places (does it exist? phone/address match?) + site scraping (email / form)
Stage 3 — Scoring           Lead fit via AI (DeepSeek), from site content and niche
Stage 4 — Email             First-contact email generation via AI (DeepSeek)
Stage 5 — Sending           SMTP with a date-based warm-up curve (avoids burning a new domain's reputation)
Stage 6 — Manual WhatsApp   Generates a wa.me link for manual outreach (no automation)
Stage 7 — AI WhatsApp       Copilot (suggests, operator approves and sends) or automatic (gateway sends), with a versioned commercial policy
```

```
                       CNPJ (name + city + state, via CNAE)
                                    │
                          Google Places Text Search
                                    │
                does phone OR street match Federal Revenue data?
                    │ yes                        │ no
           Google Place Details            discarded
             extracts "website"        (keeps only Federal Revenue phone)
                    │
              has website?
           │ yes              │ no
    contact scraper      keeps only the
   (email / form)        verified phone
```

Verification against Federal Revenue data is mandatory: some
Google Places results are false positives (similar name, different
address/phone).

### Stage 7 — WhatsApp

The most elaborate stage of the pipeline. Three processes coordinated
through a single Postgres database:

| Process | What it does |
|---|---|
| **API** (FastAPI) | number authorization, commercial policy, commands, inbox (`/api/v1/whatsapp/*`) |
| **Worker** (Python) | ingests events, decides conversation scope, calls the LLM (DeepSeek) and writes the output |
| **Gateway** (Node + Baileys) | WhatsApp session, raw events, sends the outbound queue |

Design highlights:

- **Copilot mode by default**: the model only *suggests* a reply; a
  human reviews it, edits if needed, and sends it manually through
  their own WhatsApp. Automatic mode (the gateway sends directly) is
  opt-in and policy-driven, never hardcoded.
- **Price never comes from the language model.** The LLM picks a
  package and add-ons; the final value is always computed by a
  separate module, and any price that shows up in the generated text
  is validated against that module before going out — if it doesn't
  match, the reply is discarded and the conversation escalates to a
  human.
- **Explicit per-number authorization**: the system never starts
  automated contact without an operator authorizing that phone number;
  changing the registered phone number doesn't inherit authorization.
- **Content guardrails**: business hours, daily new-contact limit,
  discount limit, "I already paid" never turns into payment
  confirmation (there's no such field), acceptance gets recorded but
  contract/payment stay outside the system.
- **Local kill switch** (a `PAUSA` file in `services/whatsapp-gateway/`)
  stops automated sending without depending on the API being up.

More operational detail in [`docs/whatsapp-etapa7.md`](docs/whatsapp-etapa7.md)
(Portuguese).

#### Commercial policy

`etapa7_whatsapp/politica.py` defines the commercial policy — packages,
prices, discount rules and budget calculation — following the
interface documented in
[`etapa7_whatsapp/politica.example.py`](etapa7_whatsapp/politica.example.py)
(function signatures, what each one must do and guarantee). To use
stage 7, copy the example to `politica.py` and implement your own
business policy; the conversation prompt text follows the same model,
in `etapa7_whatsapp/roteiro.py` (see `roteiro.example.py`). Stage 7 is
registered in the API when that module is
present; everything else (leads, Kanban, map, metrics, export) does not
depend on it.

## Web interface

A screen over the same database to track the funnel: filterable list,
Kanban by stage, map of geolocated leads, conversion metrics by
niche/city, and export (CSV/XLSX). Details in
[`docs/web-interface.md`](docs/web-interface.md) (Portuguese).

## Tech stack

| Layer | Technology |
|---|---|
| Main language | Python 3.11 |
| API | FastAPI |
| Database | PostgreSQL + SQLAlchemy + Alembic (migrations) |
| Frontend | React + TypeScript + Vite |
| WhatsApp | Node.js + Baileys (unofficial WhatsApp Web library) |
| AI | DeepSeek (scoring, email generation, WhatsApp conversation) |
| Company discovery | Apify (CNPJ scraping actor) |
| Location verification | Google Places API |
| Site scraping | Playwright (fallback for JS-heavy sites) |
| Production processes | PM2 (API + worker + gateway) |
| Tests | pytest (unit + integration + e2e with Playwright) |

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # fill in the variables (see table below)
alembic upgrade head
```

### Environment variables (`.env`)

| Variable | Description |
|---|---|
| `DATABASE_URL` | Postgres connection string |
| `APIFY_TOKEN` | Apify account token (CNPJ actor) |
| `GOOGLE_PLACES_API_KEY` | Places API (Text Search + Place Details) |
| `DEEPSEEK_API_KEY` | Scoring, email and WhatsApp conversation |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | Email sending (stage 5) |
| `WARMUP_START_DATE` | Date of the first real send; drives the warm-up curve |
| `WHATSAPP_AUTH_KEY` | Key that encrypts the WhatsApp session in the database |
| `WHATSAPP_NOTIFICACAO_OPERADOR` | WhatsApp number that receives the deal-acceptance notice |

### Stages 1–2 (discovery and validation)

```bash
python main.py
```

1. Syncs the niches defined in `config/nichos.yaml`.
2. Fetches active companies by CNAE via Apify and inserts the new ones
   (deduped by CNPJ). Apify's free plan caps at 100 items per actor
   run — for larger volumes, use
   `CnpjClient.buscar_por_cnae_paginado`, which paginates by state.
3. For every company without a validation record: Google Places +
   verification, and contact scraping if a confirmed website exists.

### Stages 3–5 (scoring, email, sending)

Run by their own modules, outside of `main.py`:

```bash
python -m etapa3_scoring.scoring
python -m etapa4_email.email_writer
python -m etapa5_envio.smtp_sender
```

### Stage 6 — manual WhatsApp links

```bash
python -m etapa6_whatsapp.gerar_links --amostra 5
```

### Stage 7 — AI WhatsApp

```bash
# API
uvicorn api.app:app --host 127.0.0.1 --port 8000

# Worker
python -m etapa7_whatsapp.worker

# Gateway (once: npm install)
cd services/whatsapp-gateway && npm install && npm run build && npm start
```

Or all three at once via PM2 — see [`docs/pm2.md`](docs/pm2.md)
(Portuguese).

### Web interface

```bash
cd web && npm install && npm run build
uvicorn api.app:app --host 127.0.0.1 --port 8000
```

### Tests

```bash
pytest                 # unit + integration (stages 1–6, leads/Kanban/map/metrics/export API)
pytest tests/e2e        # end-to-end with Playwright (boots the web interface)
```

## Structure

```
sales-engine/
├── config/
│   └── nichos.yaml          # pain points, sales arguments and tone per niche
├── db/
│   └── models.py            # SQLAlchemy schema (Postgres)
├── migrations/               # Alembic
├── etapa1_busca/             # Apify (CNPJ by CNAE)
├── etapa2_validacao/         # Google Places + contact scraping
├── etapa3_scoring/           # lead fit via AI
├── etapa4_email/             # first-contact email generation
├── etapa5_envio/             # SMTP with warm-up
├── etapa6_whatsapp/          # manual wa.me links
├── etapa7_whatsapp/          # AI WhatsApp copilot/automation
│   ├── politica.example.py  # commercial-policy interface (implemented in politica.py)
│   └── roteiro.example.py   # conversation-prompt interface (implemented in roteiro.py)
├── services/whatsapp-gateway/  # Node + Baileys gateway
├── api/                       # FastAPI
├── web/                       # React + TypeScript
├── maintenance/               # maintenance scripts (geolocation, additional prospecting)
└── main.py                    # stages 1–2 orchestrator
```
