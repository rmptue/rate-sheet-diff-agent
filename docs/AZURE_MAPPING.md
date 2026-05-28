# Azure stack mapping

This project is built on Claude + n8n + Streamlit so it can be demoed on a
laptop, but every layer maps cleanly onto Microsoft Azure equivalents. A
production rollout inside a Microsoft shop would look like the table below.

| This project (laptop)           | Azure equivalent (production)                       | Why it's the right fit                                                                                |
| ------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `data/*.xlsx` on local disk     | **Azure Blob Storage** container `rate-sheets/`     | Versioned, access-controlled storage. Blob events drive downstream automation.                        |
| n8n manual / file trigger       | **Event Grid** subscription on Blob `Created` event | Native push trigger. No polling. Idempotency via blob ETag.                                           |
| `core/` deterministic diff      | **Azure Durable Functions** (Python)                | Orchestrator function calls activity functions; replay-safe and observable in App Insights.          |
| `ai/summarizer.py` (Claude)     | **Azure OpenAI** GPT-4o (or Claude on Azure AI Foundry) | Network-isolated model endpoint, key-vault-managed credentials, audit logs.                       |
| `agent/orchestrator.py` (tools) | **Durable Functions sub-orchestrator** + **AI Foundry agent** | Native tool-calling on Azure; activity functions wrap the deterministic engine.            |
| `agent/email_sender.py` (Gmail) | **Logic Apps** "Send email (Office 365)" connector  | First-party O365/Outlook integration, OAuth handled by the connector, no token management in code.    |
| Streamlit UI                    | **Azure App Service** (containerized) or **Static Web App + Functions API** | Auth via Entra ID; managed TLS; same Streamlit container.                          |
| `.env` secrets                  | **Azure Key Vault** + Managed Identity              | No secrets in code or env files; rotation is a Key Vault config change.                               |
| `pytest`                        | **Azure DevOps Pipelines** or **GitHub Actions on Azure runners** | Same tests, gated deploy to Functions via slot swap.                                  |

## End-to-end flow on Azure

1. Procurement uploads `rate_sheet_2026Q3.xlsx` to the `rate-sheets/` blob
   container.
2. Event Grid fires a `Microsoft.Storage.BlobCreated` event.
3. A **Durable Functions** orchestrator starts:
   - *Activity 1* downloads the new blob and the previous version
     (Blob Storage versioning gives us "previous" for free).
   - *Activity 2* runs `core.differ.diff_rate_sheets` — pure Python, no
     model.
   - *Activity 3* posts the `DiffResult` JSON to **Azure OpenAI** (or AI
     Foundry-hosted Claude) using the same prompt from `ai/prompts.py`.
   - *Activity 4* hands the resulting subject + HTML to a **Logic App**
     via HTTP webhook; Logic App sends through the Office 365 connector.
4. App Insights captures the orchestration trace; failures page on-call
   via Azure Monitor alerts.

## Why this matters in interview context

The "AI does something" layer is portable: the prompt, the tool schema,
and the deterministic engine all move 1:1 to Azure. The only thing that
changes is the *plumbing* — and Azure's first-party plumbing (Durable
Functions, Logic Apps, Event Grid, Key Vault, Entra) is what an
enterprise Microsoft customer actually wants to see on the architecture
slide.
