# Rate Sheet Diff Agent

An AI automation that compares two Excel freight-rate sheets, classifies
every change (New / Updated / Deleted), reconciles **re-dated lanes**
that a naive diff would misreport, and autonomously drafts and sends a
business-readable email summary.

## The interesting design choice

The LLM lives **downstream** of a deterministic diff engine.

- `core/` decides *what changed* — pure Python, fully auditable, no AI.
- `ai/` decides *how to talk about what changed* — Claude narrates the
  structured diff. The prompt forbids it from recomputing or restating
  any number.

Pricing data must be reproducible. An LLM is not allowed to decide
whether `4.29` and `4.27` are the same number. So it doesn't.

## What it catches that a naive diff misses

The example files hide one subtle case: a single logical lane
(`Customer 115 / HAN → AZ`) whose Effective Date shifts from
`2026-06-01` to `2026-07-01`. A naive row diff reports this as
`1 New + 1 Deleted` and pollutes the summary. The reconciliation pass
in [`core/differ.py`](core/differ.py) detects the shared
`(Customer, Origin, Destination)` and pairs them into a `RE-DATED`
bucket. The email then reads:

> 0 new, 0 deleted, **4 updated, 1 re-dated** (Customer 115 / HAN → AZ
> re-issued for July).

That's the production-grade summary a freight ops manager actually wants.

## Project layout

```
core/        deterministic engine (loader, differ, models)
ai/          Claude narration layer + versioned prompts
agent/       tool-calling orchestrator + Gmail/SMTP senders
web/         Streamlit demo UI
n8n/         importable n8n workflow mirror
docs/        deliverable + Azure mapping
tests/       pytest ground-truth tests
data/        Example_1.xlsx, Example_2.xlsx
```

## Run it

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env                                    # fill in keys (optional)

# Full agent, dry-run (default — prints the email, sends nothing):
python -m agent.orchestrator

# Actually send (requires Gmail OAuth setup or SMTP App Password):
python -m agent.orchestrator --send --to you@example.com

# Streamlit:
streamlit run web/app.py

# n8n:
# Workflows → Import from File → n8n/workflow.json
# Replace Anthropic + Gmail credentials inside the imported workflow.

# Tests:
pytest -v
```

## Verified ground truth

`pytest -v` proves the engine against the real files:

| View         | New | Deleted | Updated | Re-dated |
| ------------ | --- | ------- | ------- | -------- |
| Raw          | 1   | 1       | 4       | —        |
| Reconciled   | 0   | 0       | 4       | 1        |

Updated breakdown: **2 Rate changes** (`Customer 106 / PNH / OH`,
both Effective Dates), **2 Expiration Date extensions**
(`Customer 107 / DEL / OH`, `Customer 115 / HAN / AZ`).

## Azure mapping

See [docs/AZURE_MAPPING.md](docs/AZURE_MAPPING.md) for how this stack
ports 1:1 to Azure (Durable Functions + Azure OpenAI + Logic Apps +
Blob Storage + Event Grid + Key Vault).

## Graceful degradation

| Missing                  | Behavior                                                     |
| ------------------------ | ------------------------------------------------------------ |
| `ANTHROPIC_API_KEY`      | AI layer renders a deterministic HTML fallback.              |
| `anthropic` SDK          | Orchestrator runs a scripted (no-LLM) tool sequence.         |
| `credentials.json`       | Gmail API path fails cleanly; SMTP path still works.         |
| `SMTP_USER/APP_PASSWORD` | SMTP path fails cleanly; Gmail API path still works.         |
| `--dry-run` (default)    | Email is printed to stdout. Nothing leaves the machine.      |
