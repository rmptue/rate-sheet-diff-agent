"""Streamlit demo UI.

Run locally:   streamlit run web/app.py
Deployed at:   https://rate-sheet-diff-agent-production.up.railway.app

Visual direction: clean, light, generous whitespace, single accent color,
modern sans (Inter via Google Fonts). The default Streamlit chrome is
deliberately overridden so the demo doesn't *look* like a stock
Streamlit app.

Flow:
    1. Data source — bundled sample (large), test fixtures (small), or upload
    2. Diff      — with the re-dated reconciliation highlighted
    3. Email     — AI-narrated preview, then "Email this to me" via Resend
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

# Mirror Streamlit Cloud / Railway secrets into env so the rest of the
# pipeline (which reads os.environ) picks them up.
try:
    for key in ("ANTHROPIC_API_KEY", "RESEND_API_KEY", "RESEND_FROM"):
        if key in st.secrets and not os.environ.get(key):
            os.environ[key] = st.secrets[key]
except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
    pass

import pandas as pd

from core.loader import load_rate_sheet
from core.differ import diff_rate_sheets
from ai.summarizer import summarize_diff
from agent.resend_sender import send_via_resend


# ---------------------------------------------------------------------------
# Page config & global styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Rate Sheet Diff Agent",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ACCENT = "#4f46e5"        # indigo-600
ACCENT_SOFT = "#eef2ff"   # indigo-50
INK = "#0f172a"           # slate-900
MUTED = "#64748b"         # slate-500
BORDER = "#e2e8f0"        # slate-200
SUCCESS = "#059669"       # emerald-600
WARN = "#d97706"          # amber-600

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"], .stMarkdown, .stText, .stButton button,
    .stTextInput input, .stRadio label, .stMetric {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }}
    code, pre, .stCode {{ font-family: 'JetBrains Mono', monospace !important; }}

    .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1100px; }}

    /* Headline */
    .rs-hero {{
        padding: 28px 32px;
        border-radius: 16px;
        background: linear-gradient(135deg, {ACCENT} 0%, #7c3aed 100%);
        color: white;
        margin-bottom: 28px;
        box-shadow: 0 1px 3px rgba(15,23,42,.08);
    }}
    .rs-hero h1 {{
        font-size: 28px; font-weight: 700; margin: 0 0 6px 0; color: white;
        letter-spacing: -0.02em;
    }}
    .rs-hero p {{ margin: 0; opacity: 0.92; font-size: 14px; line-height: 1.55; }}

    /* Section heading */
    .rs-step {{
        display: flex; align-items: center; gap: 12px;
        margin: 36px 0 14px 0;
    }}
    .rs-step-num {{
        width: 28px; height: 28px; border-radius: 8px;
        background: {ACCENT_SOFT}; color: {ACCENT};
        font-weight: 600; font-size: 14px;
        display: flex; align-items: center; justify-content: center;
    }}
    .rs-step h2 {{
        margin: 0; font-size: 18px; font-weight: 600; color: {INK};
        letter-spacing: -0.01em;
    }}

    /* Card */
    .rs-card {{
        border: 1px solid {BORDER}; border-radius: 12px;
        padding: 18px 20px; background: white;
        box-shadow: 0 1px 2px rgba(15,23,42,.03);
    }}

    /* Metric cards */
    [data-testid="stMetric"] {{
        background: white;
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 14px 18px;
        box-shadow: 0 1px 2px rgba(15,23,42,.03);
    }}
    [data-testid="stMetricLabel"] {{
        font-size: 12px !important; color: {MUTED} !important;
        font-weight: 500 !important; text-transform: uppercase; letter-spacing: 0.04em;
    }}
    [data-testid="stMetricValue"] {{
        font-size: 28px !important; font-weight: 700 !important; color: {INK} !important;
    }}
    [data-testid="stMetricDelta"] svg {{ display: none; }}
    [data-testid="stMetricDelta"] {{
        font-size: 11px !important; color: {MUTED} !important;
    }}

    /* Tables */
    .stDataFrame {{ border: 1px solid {BORDER}; border-radius: 10px; overflow: hidden; }}

    /* Buttons */
    .stButton > button {{
        border-radius: 10px; font-weight: 500; padding: 8px 18px;
        border: 1px solid {BORDER}; background: white; color: {INK};
        transition: all 0.15s ease;
    }}
    .stButton > button:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
    .stButton > button[kind="primary"] {{
        background: {ACCENT}; color: white; border-color: {ACCENT};
    }}
    .stButton > button[kind="primary"]:hover {{
        background: #4338ca; border-color: #4338ca; color: white;
    }}

    /* Inputs */
    .stTextInput input, .stTextArea textarea {{
        border-radius: 10px !important; border: 1px solid {BORDER} !important;
        font-family: 'Inter', sans-serif !important;
    }}

    /* Radio pills */
    div[role="radiogroup"] > label {{
        background: white; border: 1px solid {BORDER}; border-radius: 10px;
        padding: 10px 14px; margin-right: 8px; cursor: pointer;
        transition: all 0.15s ease;
    }}
    div[role="radiogroup"] > label:has(input:checked) {{
        border-color: {ACCENT}; background: {ACCENT_SOFT}; color: {ACCENT};
        font-weight: 500;
    }}

    /* Status pills */
    .rs-pill {{
        display: inline-block; padding: 4px 10px; border-radius: 999px;
        font-size: 11px; font-weight: 500; letter-spacing: 0.02em;
    }}
    .rs-pill-success {{ background: #ecfdf5; color: {SUCCESS}; }}
    .rs-pill-warn    {{ background: #fffbeb; color: {WARN}; }}
    .rs-pill-muted   {{ background: #f1f5f9; color: {MUTED}; }}

    /* Footer */
    .rs-footer {{
        margin-top: 48px; padding-top: 20px;
        border-top: 1px solid {BORDER}; text-align: center;
        font-size: 12px; color: {MUTED};
    }}
    .rs-footer a {{ color: {ACCENT}; text-decoration: none; }}

    /* Hide default Streamlit chrome */
    #MainMenu {{ visibility: hidden; }}
    footer {{ visibility: hidden; }}
    header {{ visibility: hidden; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def step(num: int, title: str) -> None:
    st.markdown(
        f'<div class="rs-step"><div class="rs-step-num">{num}</div><h2>{title}</h2></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="rs-hero">
      <h1>Rate Sheet Diff Agent</h1>
      <p>Deterministic Excel rate-sheet diff with <b>re-dated lane reconciliation</b>,
      narrated by Claude into a business-readable email. Pure-Python audit layer,
      LLM only narrates.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# 1. Data source
# ---------------------------------------------------------------------------

step(1, "Choose data")

source = st.radio(
    "Data source",
    ["Test fixtures (recommended — small, every change type)",
     "Full sample (783 rows from the original brief)",
     "Upload my own xlsx files"],
    horizontal=False,
    label_visibility="collapsed",
)

old_path: Path | None = None
new_path: Path | None = None
data_label = ""

if source.startswith("Test"):
    old_path = ROOT / "data" / "Test_OLD.xlsx"
    new_path = ROOT / "data" / "Test_NEW.xlsx"
    data_label = "Test fixtures (14 rows each, one of every change type)"
elif source.startswith("Full"):
    old_path = ROOT / "data" / "Example_1.xlsx"
    new_path = ROOT / "data" / "Example_2.xlsx"
    data_label = "Full sample (783 rows each, 6 real changes)"
else:
    c1, c2 = st.columns(2)
    f_old = c1.file_uploader("OLD rate sheet (.xlsx)", type=["xlsx"], key="old")
    f_new = c2.file_uploader("NEW rate sheet (.xlsx)", type=["xlsx"], key="new")
    if f_old and f_new:
        tmp = Path("/tmp"); tmp.mkdir(parents=True, exist_ok=True)
        old_path = tmp / "old.xlsx"
        new_path = tmp / "new.xlsx"
        old_path.write_bytes(f_old.getvalue())
        new_path.write_bytes(f_new.getvalue())
        data_label = f"Uploaded: {f_old.name} vs {f_new.name}"

if not (old_path and new_path) or (source.startswith(("Test", "Full")) and not (old_path.exists() and new_path.exists())):
    st.info("Pick a data source above to continue.")
    st.stop()

st.markdown(f'<span class="rs-pill rs-pill-muted">📂 {data_label}</span>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 2. Diff
# ---------------------------------------------------------------------------

step(2, "Diff")

with st.spinner("Loading and diffing..."):
    old = load_rate_sheet(old_path)
    new = load_rate_sheet(new_path)
    diff = diff_rate_sheets(old, new)

raw = diff.counts_raw()
rec = diff.counts_reconciled()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Updated", rec["updated"])
m2.metric("Re-dated lanes", rec["redated"])
m3.metric("New", rec["new"], delta=f"raw view: {raw['new']}", delta_color="off")
m4.metric("Deleted", rec["deleted"], delta=f"raw view: {raw['deleted']}", delta_color="off")

if diff.redated:
    st.markdown(
        f"""
        <div style="margin-top:18px;padding:14px 18px;border-radius:10px;
                    background:#fffbeb;border:1px solid #fde68a;color:#78350f;
                    font-size:13px;line-height:1.55">
          <b>🔁 Re-dated lane{'s' if len(diff.redated)>1 else ''} detected.</b>
          A naive row-level diff would report
          {len(diff.redated)} of the New + {len(diff.redated)} of the Deleted
          rows as unrelated changes. They are the same logical lane being
          re-issued on a new Effective Date — the reconciliation pass pairs them.
        </div>
        """,
        unsafe_allow_html=True,
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
    st.markdown("<div style='margin-top:18px;font-weight:600;color:" + INK + ";font-size:14px'>Updated rows</div>", unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame([
            {
                "Customer": u.new.customer,
                "Origin": u.new.origin,
                "Destination": u.new.destination,
                "Effective": u.new.effective_date.isoformat(),
                "Field": d.field.replace("_", " "),
                "Old": str(d.old),
                "New": str(d.new),
            }
            for u in diff.updated for d in u.deltas
        ]),
        use_container_width=True, hide_index=True,
    )

if diff.new_after_reconcile:
    st.markdown("<div style='margin-top:18px;font-weight:600;color:" + INK + ";font-size:14px'>Genuinely new rows</div>", unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([{
        "Customer": r.customer, "Origin": r.origin, "Destination": r.destination,
        "Effective": r.effective_date.isoformat(), "Expiration": r.expiration_date.isoformat(),
        "Rate": r.rate,
    } for r in diff.new_after_reconcile]), use_container_width=True, hide_index=True)

if diff.deleted_after_reconcile:
    st.markdown("<div style='margin-top:18px;font-weight:600;color:" + INK + ";font-size:14px'>Genuinely deleted rows</div>", unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([{
        "Customer": r.customer, "Origin": r.origin, "Destination": r.destination,
        "Effective": r.effective_date.isoformat(), "Expiration": r.expiration_date.isoformat(),
        "Rate": r.rate,
    } for r in diff.deleted_after_reconcile]), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# 3. AI email — preview + send via Resend
# ---------------------------------------------------------------------------

step(3, "AI-generated email")

cache_key = f"draft::{old_path.name}::{new_path.name}::{len(diff.updated)}::{len(diff.redated)}"
if st.session_state.get("draft_key") != cache_key:
    with st.spinner("Asking Claude to narrate the diff..."):
        st.session_state["draft"] = summarize_diff(diff)
        st.session_state["draft_key"] = cache_key

draft = st.session_state["draft"]

source_pill = (
    '<span class="rs-pill rs-pill-success">✓ Narrated by Claude (Sonnet 4)</span>'
    if draft.source == "claude" else
    f'<span class="rs-pill rs-pill-muted">deterministic renderer · {draft.source}</span>'
)
st.markdown(source_pill, unsafe_allow_html=True)

st.markdown(
    f"""
    <div class="rs-card" style="margin-top:14px">
      <div style="font-size:12px;color:{MUTED};text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Subject</div>
      <div style="font-size:15px;font-weight:600;color:{INK}">{draft.subject}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("<div style='margin-top:16px;font-weight:600;color:" + INK + ";font-size:13px'>Body preview</div>", unsafe_allow_html=True)
st.components.v1.html(
    f"<div style='border:1px solid {BORDER};border-radius:12px;padding:24px;background:white'>{draft.html}</div>",
    height=520, scrolling=True,
)


# --- Send -----------------------------------------------------------------
st.markdown("<br>", unsafe_allow_html=True)

resend_ready = bool(os.environ.get("RESEND_API_KEY"))

st.markdown(
    f"""
    <div class="rs-card">
      <div style="font-size:13px;font-weight:600;color:{INK};margin-bottom:4px">
        Email this summary to yourself
      </div>
      <div style="font-size:12px;color:{MUTED};margin-bottom:14px">
        {('A real email will be sent via Resend to the address you enter. '
          'For abuse-prevention, only one send per session, recipient locked '
          'to what you type below.')
         if resend_ready else
         ('Demo not yet wired to a real sender — set <code>RESEND_API_KEY</code> '
          'in the Railway environment to enable. Until then, the preview above '
          'is the deliverable.')}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if "sends_this_session" not in st.session_state:
    st.session_state["sends_this_session"] = 0
MAX_SENDS_PER_SESSION = 3

recipient = st.text_input(
    "Your email",
    placeholder="you@yourcompany.com",
    label_visibility="collapsed",
)


def _valid_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s or ""))


col_btn, col_status = st.columns([1, 3])
with col_btn:
    clicked = st.button(
        "📨 Send to me",
        type="primary",
        disabled=not resend_ready,
        use_container_width=True,
    )

with col_status:
    if not resend_ready:
        st.markdown(
            '<span class="rs-pill rs-pill-muted">Send disabled — server has no Resend key</span>',
            unsafe_allow_html=True,
        )
    elif st.session_state["sends_this_session"] >= MAX_SENDS_PER_SESSION:
        st.markdown(
            '<span class="rs-pill rs-pill-warn">Per-session send limit reached</span>',
            unsafe_allow_html=True,
        )

if clicked:
    if not _valid_email(recipient):
        st.error("Enter a valid email address.")
    elif st.session_state["sends_this_session"] >= MAX_SENDS_PER_SESSION:
        st.error("Per-session send limit reached. Reload the page to send more.")
    else:
        with st.spinner(f"Sending via Resend to {recipient}…"):
            result = send_via_resend(draft.subject, draft.html, recipient)
        if result.ok:
            st.session_state["sends_this_session"] += 1
            st.success(f"✓ {result.detail}" + (f" · id `{result.message_id}`" if result.message_id else ""))
            st.caption(
                "Check your inbox (and spam folder). The sender is "
                "`onboarding@resend.dev` — that's Resend's shared demo sender, "
                "not a custom domain."
            )
        else:
            st.error(result.detail)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="rs-footer">
      Built as a take-home AI-automation showcase ·
      <a href="https://github.com/rmptue/rate-sheet-diff-agent">source on GitHub</a> ·
      pure-Python audit · Claude Sonnet 4 narration · Resend delivery
    </div>
    """,
    unsafe_allow_html=True,
)
