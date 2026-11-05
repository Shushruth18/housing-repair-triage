# housing-repair-triage

A small, privacy-aware **RAG (retrieval-augmented generation) assistant** for a housing repairs team. Ask a question about a unit, and it does three things:
- rebuilds that unit's repair history;
- finds the matching rule in the team's repair procedure;
- asks Claude for a short, **cited** answer about what happens next.

It was also built as a test bed for **AgenticAudit**, a compliance monitor that watches an AI coding agent through Claude Code hooks. The findings are in [`TEST-RESULTS.md`](TEST-RESULTS.md).

> All data in `data/` is fictional. Names and emails use `example.com`.

## Example

**Question:** *Has unit 2B's kitchen sink leak been reported before, and what follow-up does the procedure call for?*

**Answer (abridged):**
- The leak was first reported on 2026-10-03 [R201].
- A contractor replaced the drain seal and closed the case on 2026-10-05 [R202].
- Water pooled in the same place again, and the case was reopened on 2026-10-20 [R203].
- The recurrence came within 30 days of the closed repair, so the next step is to **request a follow-up inspection** [RP01].

Unit 2D also had a sink leak (R204, R205), and the answer correctly leaves it out.

## How it works

```
CSV + procedure ──► 1 validate ──► 2 redact ──► 3 chunk ──► 4 embed + store (numpy)
                                                                   │
question ──► 5 retrieve: filter by unit + issue (timeline, date order)
                         + vector search over procedure sections
                                     │
                         6 generate: Claude writes a cited answer ──► citation check
```

| Stage | What it does |
|---|---|
| 1. Validate | Loads `tenants.csv` and `repair_events.csv`. Every event's `unit_id` must exist; events are sorted by date. |
| 2. Redact | Tenant names and emails are joined locally only and stripped from any text that leaves the machine. |
| 3. Chunk | One chunk per repair event and one per procedure section. IDs, unit, date and issue are kept as local metadata. |
| 4. Embed + store | Vectors from Voyage, OpenAI, or a local hashed bag-of-words fallback, saved to `.store/`. |
| 5. Retrieve | A metadata filter picks the unit's own events, so a similar leak in another unit can't slip in. The procedure is searched separately. |
| 6. Generate | Sends the timeline and procedure to the Anthropic API and checks that every citation resolves. |

**Privacy gate:** every outbound request goes through [`triage/outbound.py`](triage/outbound.py). The gate:
- scans the payload for tenant names and emails, and blocks it if any are found;
- logs the payload to a local `outbound_log.jsonl`;
- prints the payload instead of sending it when `--dry-run` is on.

## Quick start (Windows / PowerShell)

Requires Python 3.12 and an [Anthropic API key](https://console.anthropic.com/).

```powershell
git clone https://github.com/<your-username>/housing-repair-triage.git
cd housing-repair-triage
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # then paste your ANTHROPIC_API_KEY into .env
```

On macOS/Linux, use `.venv/bin/python` and `cp` instead.

### Settings (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Required for live answers |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | |
| `EMBEDDINGS_PROVIDER` | `local` | `voyage`, `openai` or `local` (no network, no key) |
| `VOYAGE_API_KEY` / `OPENAI_API_KEY` | – | Only for that provider |

`.env` is git-ignored. Never commit real keys.

## Usage

### Web app

```powershell
.venv\Scripts\streamlit.exe run app.py
```

Open http://localhost:8501.
- **Dry run** is on by default: it shows the exact payload and sends nothing. Turn it off to get a real answer.
- The page shows the timeline, the procedure, each outbound request with its PII scan, the answer and the citation check.

### Command line

```powershell
$q = "Has unit 2B's kitchen sink leak been reported before, and what follow-up does the procedure call for?"
.venv\Scripts\python.exe -m triage validate           # 1. load + validate
.venv\Scripts\python.exe -m triage redact --unit U2B  # 2. local join vs redacted text
.venv\Scripts\python.exe -m triage chunk              # 3. chunks + metadata
.venv\Scripts\python.exe -m triage index              # 4. embed + store
.venv\Scripts\python.exe -m triage retrieve $q        # 5. timeline + procedure
.venv\Scripts\python.exe -m triage ask $q             # 6. cited answer + check
.venv\Scripts\python.exe -m triage ask $q --dry-run   # print payloads, send nothing
```

`ask --leak-test` is for compliance testing only. It deliberately places the tenant's email into the single LLM request.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -v                      # offline tests
$env:RUN_LIVE="1"; .venv\Scripts\python.exe -m pytest -v   # also calls the Anthropic API
```

The tests cover:
- **Validation:** unknown units, bad dates, duplicates.
- **Redaction:** no names or emails in any outbound payload, and dirty payloads are blocked.
- **Retrieval:** 2B never receives 2D's events.
- **The expected answer:** it must cite R201, R202, R203 and RP01 and must not mention R204/R205.

## Project layout

```
app.py              Streamlit page
triage/             pipeline: load, redact, chunk, embed, store, retrieve, generate, outbound gate, CLI
tests/              pytest suite
data/               fictional tenants, repair events and procedure
tools/              helpers for the AgenticAudit test (outbound verifier, audit summary)
audit_logs/         console output of compliance runs A–D
TEST-RESULTS.md     AgenticAudit compliance test write-up
```

## AgenticAudit findings (short version)

Four runs were made: a dry run, a redacted live run, a controlled leak and a repeat.
- AgenticAudit rated all four the same: low risk, no PII.
- It could see the command that ran, but not the HTTPS request the app made, so the controlled leak went unnoticed.

See [`TEST-RESULTS.md`](TEST-RESULTS.md) for details.
