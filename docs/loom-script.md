# Loom walkthrough script (2–3 minutes)

Target: 2:30 total. Record terminal + browser side by side. Suggested timestamps:

## 0:00–0:30 — Code structure (30s)

Show the repo tree and name each module in one sentence:

- `cli.py` — Typer entrypoint (`lead-agent run --domains ...`)
- `orchestrator.py` — bounded agentic loop: relevance-ranked page queue, `max_pages` budget
- `fetcher.py` — Playwright first, `httpx` fallback, retries, HTTP-error pages treated as failures
- `cleaner.py` — strips scripts/styles/SVG/nav/footer, extracts text, emails, LinkedIn URLs, ranked links
- `llm.py` — Gemini structured extraction (`gemini-3.5-flash-lite`, temperature 0, Pydantic JSON schema)
- `search.py` — Tavily fallback for LinkedIn URLs only when on-site evidence is missing
- `writers.py` — `output.json` + `output.csv`, including tokens, estimated cost, call counts

## 0:30–1:00 — Setup (30s)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[browser,dev]'
playwright install chromium
cp .env.example .env
```

Open `.env` (blur the key values on screen) and point out `GEMINI_API_KEY`,
`GEMINI_MODEL=gemini-3.5-flash-lite`, and optional `TAVILY_API_KEY`.

## 1:00–2:00 — Live run (60s)

```bash
lead-agent run \
  --domains postman.com --domains supabase.com --domains vapi.ai \
  --max-pages 6 \
  --search-enabled \
  --output output/output.json \
  --csv output/output.csv
```

Narrate: progress spinner per domain, Rich summary table (`status`, confidence,
pages), and point out it continues with warnings instead of crashing if one
site fails.

## 2:00–2:30 — Outputs (30s)

Open `output/output.json` (one record: overview, ICP, emails, leadership with
LinkedIn URLs, `data_confidence_score`, `source_pages`, `warnings`, `cost`
with tokens + `estimated_cost_usd`) and `output/output.csv`, then show
`docs/architecture.png` briefly.

Close with the honest limitation: leadership extraction is only as good as
public evidence — customer names on case-study pages are not company
leadership, and low-confidence rows should be manually verified.
