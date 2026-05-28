"""Streamlit demo UI.

Run locally:   streamlit run web/app.py
Deployed at:   (see README — Streamlit Community Cloud)

Three sections: (1) data source (upload or sample), (2) diff with the
re-dated reconciliation highlighted, (3) AI-narrated email preview that
asks the reviewer for their own email address so the demo feels real.

By design, the deployed version does **not** send actual email. Reviewers
see the rendered HTML email in-browser with their address filled in.
Real sending lives in the local CLI agent (`agent/orchestrator.py`),
which supports Gmail OAuth and SMTP. This keeps the public demo safe
from abuse and avoids exposing email credentials in a hosted app.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `streamlit run web/app.py` from the repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Hosted Streamlit Cloud surfaces secrets via st.secrets; mirror them into
# environment variables so the rest of the pipeline (which reads os.environ)
# picks them up transparently.
import streamlit as st
try:
    if "ANTHROPIC_API_KEY" in st.secrets and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
    pass  # No secrets file locally — that's fine, fallback renderer kicks in.

import pandas as pd

from core.loader import load_rate_sheet
from core.differ import diff_rate_sheets
from ai.summarizer import summarize_diff


st.set_page_config(page_title="Rate Sheet Diff Agent", layout="wide", page_icon="📑")
st.title("📑 Rate Sheet Diff Agent")
st.caption(
    "Deterministic Excel rate-sheet diff with **re-dated lane reconciliation**, "
    "narrated by Claude into a business-readable email summary."
)

with st.expander("ℹ️  How this works (30s read)", expanded=False):
    st.markdown(
        """
        - **Layer 1 — deterministic engine** decides *what changed*
          (pure Python, fully auditable, no AI). It also pairs
          *re-dated lanes* — Deleted + New rows that share
          Customer / Origin / Destination and differ only in Effective
          Date. Without this pass, the same lane being re-issued on a
          new start date looks like two unrelated changes.
        - **Layer 2 — Claude (Sonnet 4)** narrates the structured diff.
          The prompt explicitly forbids the model from recomputing or
          restating any number. AI lives *downstream* of the audit.
        - **Layer 3 — agent** (not shown in this UI) wraps the above as
          tools and uses Claude tool-use to read → diff → summarize → send.
        """
    )

# --- 1. Data source ----------------------------------------------------
st.header("1. Choose data")
source = st.radio(
    "Data source",
    ["📦 Use bundled sample data", "📤 Upload my own xlsx files"],
    horizontal=True,
    label_visibility="collapsed",
)

old_path: Path | None = None
new_path: Path | None = None

if source.startswith("📦"):
    sample_old = ROOT / "data" / "Example_1.xlsx"
    sample_new = ROOT / "data" / "Example_2.xlsx"
    if sample_old.exists() and sample_new.exists():
        old_path, new_path = sample_old, sample_new
        st.success(f"Loaded sample data — {sample_old.name} (OLD) vs {sample_new.name} (NEW), 783 rows each.")
    else:
        st.error("Sample data missing from repo.")
else:
    c1, c2 = st.columns(2)
    f_old = c1.file_uploader("OLD rate sheet (.xlsx)", type=["xlsx"], key="old")
    f_new = c2.file_uploader("NEW rate sheet (.xlsx)", type=["xlsx"], key="new")
    if f_old and f_new:
        tmp = Path("/tmp")
        tmp.mkdir(parents=True, exist_ok=True)
        old_path = tmp / "old.xlsx"
        new_path = tmp / "new.xlsx"
        old_path.write_bytes(f_old.getvalue())
        new_path.write_bytes(f_new.getvalue())

if not (old_path and new_path):
    st.info("Pick a data source above to continue.")
    st.stop()

# --- 2. Diff -----------------------------------------------------------
st.header("2. Diff")
with st.spinner("Loading and diffing..."):
    old = load_rate_sheet(old_path)
    new = load_rate_sheet(new_path)
    diff = diff_rate_sheets(old, new)

raw = diff.counts_raw()
rec = diff.counts_reconciled()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Updated", rec["updated"])
m2.metric("Re-dated lanes", rec["redated"])
m3.metric("New (reconciled)", rec["new"], delta=f"raw: {raw['new']}", delta_color="off")
m4.metric("Deleted (reconciled)", rec["deleted"], delta=f"raw: {raw['deleted']}", delta_color="off")

if diff.redated:
    st.warning(
        "**Re-dated lanes detected.** A naive row-level diff would report "
        "these as `New + Deleted`, but they are the same logical lane "
        "being re-issued on a new Effective Date. The reconciled view "
        "below pairs them correctly."
    )
    st.dataframe(
        pd.DataFrame([
            {
                "Customer": p.deleted.customer,
                "Origin": p.deleted.origin,
                "Destination": p.deleted.destination,
                "Old Effective": p.old_effective.isoformat(),
                "New Effective": p.new_effective.isoformat(),
                "Rate": p.new.rate,
            }
            for p in diff.redated
        ]),
        use_container_width=True, hide_index=True,
    )

if diff.updated:
    st.subheader("Updated rows")
    st.dataframe(
        pd.DataFrame([
            {
                "Customer": u.new.customer,
                "Origin": u.new.origin,
                "Destination": u.new.destination,
                "Effective": u.new.effective_date.isoformat(),
                "Field": d.field,
                "Old": str(d.old),
                "New": str(d.new),
            }
            for u in diff.updated for d in u.deltas
        ]),
        use_container_width=True, hide_index=True,
    )

if diff.new_after_reconcile:
    st.subheader("Genuinely new rows")
    st.dataframe(pd.DataFrame([vars(r) for r in diff.new_after_reconcile]), hide_index=True)
if diff.deleted_after_reconcile:
    st.subheader("Genuinely deleted rows")
    st.dataframe(pd.DataFrame([vars(r) for r in diff.deleted_after_reconcile]), hide_index=True)

# --- 3. AI email preview ----------------------------------------------
st.header("3. AI-generated email")

recipient = st.text_input(
    "Recipient email (this will appear in the preview header — no email is actually sent)",
    placeholder="you@yourcompany.com",
)

# Cache the draft so re-rendering the UI doesn't re-call Claude.
cache_key = f"draft::{old_path.name}::{new_path.name}::{len(diff.updated)}::{len(diff.redated)}"
if st.session_state.get("draft_key") != cache_key:
    st.session_state["draft_key"] = None

if st.button("✨ Generate email summary", type="primary") or st.session_state.get("draft_key") == cache_key:
    if st.session_state.get("draft_key") != cache_key:
        with st.spinner("Asking Claude to narrate the diff..."):
            st.session_state["draft"] = summarize_diff(diff)
            st.session_state["draft_key"] = cache_key

    draft = st.session_state["draft"]

    if draft.source == "claude":
        st.success("✅ Narrated by Claude (Sonnet 4)")
    else:
        st.info(f"ℹ️ Rendered by deterministic fallback (`{draft.source}`). "
                "Set `ANTHROPIC_API_KEY` in Streamlit secrets to switch on Claude.")

    st.markdown("---")
    st.markdown(f"**To:** `{recipient or '(enter your email above)'}`")
    st.markdown(f"**Subject:** {draft.subject}")
    st.markdown("**Body preview:**")
    st.components.v1.html(draft.html, height=560, scrolling=True)

    st.caption(
        "🛡️ The deployed demo intentionally does **not** send real email. "
        "Real sending (Gmail OAuth + SMTP fallback) lives in the local CLI agent "
        "in `agent/orchestrator.py` — see the repo README."
    )

st.markdown("---")
st.caption("Built as a take-home showcase. Source: see GitHub repo linked in the README.")
