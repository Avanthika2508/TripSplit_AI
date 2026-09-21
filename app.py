"""
TripSplit AI
================================================================================
An intelligent group expense ecosystem with algorithmic cash-flow optimization
and AI-driven receipt parsing.

Run with:
    streamlit run app.py

Requires a Google Gemini API key (either set as the GOOGLE_API_KEY environment
variable, or entered in the sidebar at runtime) for the AI Receipt Scanner
feature. All other features work without an API key.
================================================================================
"""

import io
import os
import json
import base64
import datetime as dt
from collections import defaultdict

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# --------------------------------------------------------------------------
# Google GenAI SDK imports (supports google-generativeai with pillow,
# and fallback to google-genai)
# --------------------------------------------------------------------------
LEGACY_GENAI_AVAILABLE = False
NEW_GENAI_AVAILABLE = False

try:
    import google.generativeai as genai_legacy
    from PIL import Image
    LEGACY_GENAI_AVAILABLE = True
except Exception:
    pass

try:
    from google import genai as new_genai
    from google.genai import types as genai_types
    NEW_GENAI_AVAILABLE = True
except Exception:
    pass

GENAI_SDK_AVAILABLE = LEGACY_GENAI_AVAILABLE or NEW_GENAI_AVAILABLE


# ==============================================================================
# PAGE CONFIG & GLOBAL STYLING
# ==============================================================================
st.set_page_config(
    page_title="TripSplit AI",
    page_icon="\U0001F9F3",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    .main > div { padding-top: 1.5rem; }
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #ffffff 0%, #f7f9fc 100%);
        border: 1px solid #eaeef3;
        border-radius: 14px;
        padding: 1rem 1.1rem;
        box-shadow: 0 1px 3px rgba(16, 24, 40, 0.06);
    }
    div[data-testid="stMetricValue"] { font-weight: 700; }
    .ts-badge {
        display: inline-block;
        padding: 0.15rem 0.6rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 0.35rem;
    }
    .ts-badge-food { background:#FFF1E6; color:#B5651D; }
    .ts-badge-lodging { background:#EAF2FF; color:#1D4ED8; }
    .ts-badge-transit { background:#EAFBF0; color:#0F9D58; }
    .ts-badge-misc { background:#F3E8FF; color:#7E22CE; }
    .ts-badge-activities { background:#FEF3F2; color:#DC2626; }
    .ts-card {
        border: 1px solid #eaeef3;
        border-radius: 14px;
        padding: 1rem 1.2rem;
        background: #ffffff;
    }
    hr { margin: 0.6rem 0 1.2rem 0; }
    h1, h2, h3 { letter-spacing: -0.01em; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

CATEGORIES = ["Food", "Lodging", "Transit", "Activities", "Misc"]
CATEGORY_BADGE = {
    "Food": "ts-badge-food",
    "Lodging": "ts-badge-lodging",
    "Transit": "ts-badge-transit",
    "Activities": "ts-badge-activities",
    "Misc": "ts-badge-misc",
}
CATEGORY_COLORS = {
    "Food": "#F59E0B",
    "Lodging": "#2563EB",
    "Transit": "#10B981",
    "Activities": "#EF4444",
    "Misc": "#8B5CF6",
}


# ==============================================================================
# SESSION STATE INITIALIZATION
# ==============================================================================
def init_state():
    if "participants" not in st.session_state:
        st.session_state.participants = []
    if "expenses" not in st.session_state:
        # each expense: id, date, payer, amount, category, description, splitters (list)
        st.session_state.expenses = []
    if "next_expense_id" not in st.session_state:
        st.session_state.next_expense_id = 1
    if "pending_receipt" not in st.session_state:
        st.session_state.pending_receipt = None  # holds AI-extracted draft for review
    if "api_key_input" not in st.session_state:
        st.session_state.api_key_input = ""


init_state()


def get_api_key() -> str:
    env_key = os.environ.get("GOOGLE_API_KEY", "")
    return st.session_state.api_key_input.strip() or env_key.strip()


def add_participant(name: str):
    name = (name or "").strip()
    if not name:
        return
    if name in st.session_state.participants:
        st.toast(f"'{name}' is already in the trip.", icon="\u26A0\uFE0F")
        return
    st.session_state.participants.append(name)


def remove_participant(name: str):
    if name in st.session_state.participants:
        st.session_state.participants.remove(name)
        # Also strip them out of any existing expenses' splitters so the
        # ledger never references a removed participant.
        for e in st.session_state.expenses:
            if name in e.get("splitters", []):
                e["splitters"] = [s for s in e["splitters"] if s != name]
            if e.get("payer") == name:
                e["payer"] = None  # orphaned payer, flagged in UI


def add_expense(date, payer, amount, category, description, splitters):
    st.session_state.expenses.append(
        {
            "id": st.session_state.next_expense_id,
            "date": pd.to_datetime(date),
            "payer": payer,
            "amount": round(float(amount), 2),
            "category": category,
            "description": description.strip() or "(no description)",
            "splitters": list(splitters),
        }
    )
    st.session_state.next_expense_id += 1


# ==============================================================================
# CORE FINANCE ENGINE
# ==============================================================================
def compute_ledger_df() -> pd.DataFrame:
    if not st.session_state.expenses:
        return pd.DataFrame(
            columns=["id", "date", "payer", "amount", "category", "description", "splitters", "split_count", "per_person_share"]
        )
    df = pd.DataFrame(st.session_state.expenses)
    df["split_count"] = df["splitters"].apply(lambda s: max(len(s), 1))
    df["per_person_share"] = df["amount"] / df["split_count"]
    df = df.sort_values("date", ascending=False).reset_index(drop=True)
    return df


def compute_balances(df: pd.DataFrame, participants: list) -> pd.DataFrame:
    """Return a DataFrame with paid / owed / net balance per participant."""
    paid = defaultdict(float)
    owed = defaultdict(float)

    for _, row in df.iterrows():
        if row["payer"] in participants:
            paid[row["payer"]] += row["amount"]
        n = max(len(row["splitters"]), 1)
        share = row["amount"] / n
        for person in row["splitters"]:
            if person in participants:
                owed[person] += share

    records = []
    for p in participants:
        total_paid = round(paid.get(p, 0.0), 2)
        total_owed = round(owed.get(p, 0.0), 2)
        net = round(total_paid - total_owed, 2)
        records.append(
            {"Participant": p, "Total Paid": total_paid, "Total Owed Share": total_owed, "Net Balance": net}
        )
    return pd.DataFrame(records)


def simplify_debts(balances_df: pd.DataFrame, epsilon: float = 0.01) -> list:
    """
    Min-cash-flow debt simplification via a greedy max-creditor / max-debtor
    matching algorithm. Reduces an arbitrary peer-to-peer debt mesh down to a
    (near-)minimal number of settling transactions.

    Returns a list of dicts: {"from": debtor, "to": creditor, "amount": float}
    """
    balances = {row["Participant"]: row["Net Balance"] for _, row in balances_df.iterrows()}

    # Use a max-heap-like repeated scan (fine for typical trip group sizes).
    creditors = {k: v for k, v in balances.items() if v > epsilon}
    debtors = {k: -v for k, v in balances.items() if v < -epsilon}

    transactions = []
    creditors = dict(sorted(creditors.items(), key=lambda kv: -kv[1]))
    debtors = dict(sorted(debtors.items(), key=lambda kv: -kv[1]))

    cred_items = list(creditors.items())
    debt_items = list(debtors.items())

    ci, di = 0, 0
    while ci < len(cred_items) and di < len(debt_items):
        c_name, c_amt = cred_items[ci]
        d_name, d_amt = debt_items[di]
        settle = round(min(c_amt, d_amt), 2)

        if settle > epsilon:
            transactions.append({"from": d_name, "to": c_name, "amount": settle})

        c_amt -= settle
        d_amt -= settle
        cred_items[ci] = (c_name, c_amt)
        debt_items[di] = (d_name, d_amt)

        if c_amt <= epsilon:
            ci += 1
        if d_amt <= epsilon:
            di += 1

    return transactions


def build_adjacency_matrix(transactions: list, participants: list) -> pd.DataFrame:
    mat = pd.DataFrame(0.0, index=participants, columns=participants)
    for t in transactions:
        if t["from"] in participants and t["to"] in participants:
            mat.loc[t["from"], t["to"]] = t["amount"]
    return mat


# ==============================================================================
# AI RECEIPT SCANNER (Google GenAI)
# ==============================================================================
RECEIPT_PROMPT = """You are a precise receipt-parsing engine. Look at the attached receipt image
and extract the following fields as STRICT JSON with no markdown fences, no commentary,
and no trailing text -- ONLY the JSON object:

{
  "merchant": "<string, best-guess merchant/vendor name>",
  "total_amount": <number, the final total paid, no currency symbols>,
  "category": "<one of: Food, Lodging, Transit, Activities, Misc>",
  "date": "<YYYY-MM-DD, best guess from receipt, else today's date>",
  "description": "<short 3-8 word human-readable summary of the purchase>"
}

Rules:
- total_amount must be a plain number (e.g. 42.50), not a string.
- category must be exactly one of the five listed options; pick the closest match.
- If a field is unclear, make the most reasonable inference rather than leaving it blank.
- Output ONLY the JSON object.
"""


def parse_receipt_with_gemini(image_bytes: bytes, mime_type: str, api_key: str) -> dict:
    if not GENAI_SDK_AVAILABLE:
        raise RuntimeError(
            "Neither 'google-generativeai' nor 'google-genai' package is installed. "
            "Add google-generativeai and pillow to requirements.txt and reinstall."
        )
    if not api_key:
        raise RuntimeError("No Gemini API key configured. Add one in the sidebar.")

    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash"]
    last_error = None

    if LEGACY_GENAI_AVAILABLE:
        genai_legacy.configure(api_key=api_key)
        try:
            pil_image = Image.open(io.BytesIO(image_bytes))
        except Exception as img_err:
            raise RuntimeError(f"Failed to open receipt image with Pillow: {img_err}")

        for model_name in models_to_try:
            try:
                model = genai_legacy.GenerativeModel(
                    model_name=model_name,
                    generation_config={
                        "response_mime_type": "application/json",
                        "temperature": 0.1,
                    },
                )
                response = model.generate_content([RECEIPT_PROMPT, pil_image])
                raw_text = response.text.strip()
                cleaned = raw_text.replace("```json", "").replace("```", "").strip()
                data = json.loads(cleaned)
                return data
            except Exception as e:
                last_error = e
                continue

    elif NEW_GENAI_AVAILABLE:
        client = new_genai.Client(api_key=api_key)
        image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[RECEIPT_PROMPT, image_part],
                    config=genai_types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                raw_text = response.text.strip()
                cleaned = raw_text.replace("```json", "").replace("```", "").strip()
                data = json.loads(cleaned)
                return data
            except Exception as e:
                last_error = e
                continue

    raise RuntimeError(f"Gemini parsing failed on all models ({', '.join(models_to_try)}). Last error: {last_error}")


# ==============================================================================
# SIDEBAR
# ==============================================================================
with st.sidebar:
    st.markdown("## \U0001F9F3 TripSplit AI")
    st.caption("Group expenses, AI receipts & optimized settlements.")

    st.divider()
    st.markdown("### ⚡ Quick Actions")
    if st.button("Reset Everything", use_container_width=True):
        st.session_state.participants = []
        st.session_state.expenses = []
        st.session_state.next_expense_id = 1
        st.session_state.pending_receipt = None
        st.toast("Trip data cleared.", icon="🧹")
        st.rerun()

    st.divider()
    st.markdown("### 👥 Travelers")
    with st.form("add_participant_form", clear_on_submit=True):
        new_name = st.text_input("Add a participant", placeholder="e.g. Priya")
        submitted = st.form_submit_button("Add Traveler", use_container_width=True)
        if submitted and new_name:
            add_participant(new_name)
            st.rerun()

    if st.session_state.participants:
        for p in st.session_state.participants:
            c1, c2 = st.columns([4, 1])
            c1.write(f"👤 {p}")
            if c2.button("✕", key=f"rm_{p}", help=f"Remove {p}"):
                remove_participant(p)
                st.rerun()
    else:
        st.info("No travelers yet. Add travelers above to start.")

    st.divider()
    st.markdown("### \U0001F511 Gemini API Key")
    env_has_key = bool(os.environ.get("GOOGLE_API_KEY", "").strip())
    if env_has_key:
        st.success("GOOGLE_API_KEY found in environment.", icon="\u2705")
    st.text_input(
        "API key (fallback / override)",
        type="password",
        key="api_key_input",
        placeholder="AIza...",
        help="Used only for the AI Receipt Scanner tab. Falls back to the "
             "GOOGLE_API_KEY environment variable if left blank.",
    )
    if not GENAI_SDK_AVAILABLE:
        st.warning("google-generativeai SDK not installed — receipt scanning disabled.", icon="\u26A0\uFE0F")

    st.divider()
    st.caption("Built with Streamlit \u00B7 Pandas \u00B7 Plotly \u00B7 Gemini")


# ==============================================================================
# HEADER
# ==============================================================================
st.title("\U0001F9F3 TripSplit AI")
st.caption("Intelligent group expense tracking with AI receipt parsing and algorithmic debt simplification.")

participants = st.session_state.participants
ledger_df = compute_ledger_df()

top1, top2, top3, top4 = st.columns(4)
top1.metric("Travelers", len(participants))
top2.metric("Logged Expenses", len(ledger_df))
top3.metric("Total Trip Spend", f"${ledger_df['amount'].sum():,.2f}" if not ledger_df.empty else "$0.00")
avg_per_person = (ledger_df["amount"].sum() / len(participants)) if (participants and not ledger_df.empty) else 0.0
top4.metric("Avg. Spend / Person", f"${avg_per_person:,.2f}")

st.markdown("<hr/>", unsafe_allow_html=True)

if not participants:
    st.warning("Add at least one traveler in the sidebar to get started.")
    st.stop()


# ==============================================================================
# TABS
# ==============================================================================
tab_manual, tab_ai, tab_ledger, tab_settle = st.tabs(
    ["\u270D\uFE0F Manual Entry", "\U0001F4F8 AI Receipt Scanner", "\U0001F4CA Ledger & Analytics", "\U0001F4B8 Settlement Engine"]
)

# ------------------------------------------------------------------------------
# TAB 1: MANUAL ENTRY
# ------------------------------------------------------------------------------
with tab_manual:
    st.subheader("Log an Expense Manually")
    with st.form("manual_expense_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            payer = st.selectbox("Who paid?", options=participants)
        with c2:
            amount = st.number_input("Total amount ($)", min_value=0.0, step=1.0, format="%.2f")
        with c3:
            category = st.selectbox("Category", options=CATEGORIES)

        description = st.text_input("Description", placeholder="e.g. Dinner at the harbor")
        exp_date = st.date_input("Date", value=dt.date.today())

        st.markdown("**Split between (beneficiaries):**")
        cols = st.columns(min(len(participants), 5) or 1)
        splitters = []
        for i, p in enumerate(participants):
            with cols[i % len(cols)]:
                if st.checkbox(p, value=True, key=f"split_{p}"):
                    splitters.append(p)

        submitted = st.form_submit_button("\u2795 Add Expense", type="primary", use_container_width=True)
        if submitted:
            if amount <= 0:
                st.error("Amount must be greater than zero.")
            elif not splitters:
                st.error("Select at least one beneficiary to split this expense with.")
            else:
                add_expense(exp_date, payer, amount, category, description, splitters)
                st.success(f"Added ${amount:,.2f} expense paid by {payer}, split {len(splitters)} ways.")
                st.rerun()

# ------------------------------------------------------------------------------
# TAB 2: AI RECEIPT SCANNER
# ------------------------------------------------------------------------------
with tab_ai:
    st.subheader("Scan a Receipt with Gemini")
    st.caption("Upload a photo of a receipt and Gemini will extract the merchant, total, category, and date for you to review before saving.")

    uploaded_file = st.file_uploader("Upload receipt image", type=["png", "jpg", "jpeg"])

    colA, colB = st.columns([1, 1])
    if uploaded_file is not None:
        with colA:
            st.image(uploaded_file, caption="Uploaded receipt", use_container_width=True)

        with colB:
            api_key = get_api_key()
            can_parse = GENAI_SDK_AVAILABLE and bool(api_key)
            if not GENAI_SDK_AVAILABLE:
                st.error("google-generativeai SDK is not installed in this environment.")
            elif not api_key:
                st.error("No Gemini API key found. Add one in the sidebar to enable AI parsing.")

            if st.button("\u2728 Extract with Gemini", type="primary", disabled=not can_parse, use_container_width=True):
                image_bytes = uploaded_file.getvalue()
                mime_type = uploaded_file.type or "image/png"
                with st.spinner("Gemini is reading the receipt..."):
                    try:
                        extracted = parse_receipt_with_gemini(image_bytes, mime_type, api_key)
                        cat = extracted.get("category", "Misc")
                        if cat not in CATEGORIES:
                            cat = "Misc"
                        try:
                            parsed_date = pd.to_datetime(extracted.get("date")).date()
                        except Exception:
                            parsed_date = dt.date.today()

                        st.session_state.pending_receipt = {
                            "merchant": extracted.get("merchant", "Unknown Merchant"),
                            "total_amount": float(extracted.get("total_amount", 0) or 0),
                            "category": cat,
                            "date": parsed_date,
                            "description": extracted.get("description", "Receipt purchase"),
                        }
                        st.success("Receipt parsed! Review and confirm below.")
                    except Exception as e:
                        st.error(f"AI extraction failed: {e}")

    if st.session_state.pending_receipt:
        st.markdown("---")
        st.markdown("#### \U0001F50D Review Extracted Data")
        draft = st.session_state.pending_receipt

        with st.form("receipt_review_form"):
            c1, c2, c3 = st.columns(3)
            with c1:
                r_payer = st.selectbox("Who paid?", options=participants, key="r_payer")
            with c2:
                r_amount = st.number_input(
                    "Total amount ($)", min_value=0.0, step=0.5,
                    value=float(draft["total_amount"]), format="%.2f", key="r_amount"
                )
            with c3:
                r_category = st.selectbox(
                    "Category", options=CATEGORIES,
                    index=CATEGORIES.index(draft["category"]) if draft["category"] in CATEGORIES else 0,
                    key="r_category",
                )

            r_description = st.text_input(
                "Description",
                value=f"{draft['merchant']} — {draft['description']}",
                key="r_description",
            )
            r_date = st.date_input("Date", value=draft["date"], key="r_date")

            st.markdown("**Split between (beneficiaries):**")
            cols = st.columns(min(len(participants), 5) or 1)
            r_splitters = []
            for i, p in enumerate(participants):
                with cols[i % len(cols)]:
                    if st.checkbox(p, value=True, key=f"r_split_{p}"):
                        r_splitters.append(p)

            confirm_col, discard_col = st.columns(2)
            confirm = confirm_col.form_submit_button("\u2705 Confirm & Add to Ledger", type="primary", use_container_width=True)
            discard = discard_col.form_submit_button("\u274C Discard", use_container_width=True)

            if confirm:
                if r_amount <= 0:
                    st.error("Amount must be greater than zero.")
                elif not r_splitters:
                    st.error("Select at least one beneficiary.")
                else:
                    add_expense(r_date, r_payer, r_amount, r_category, r_description, r_splitters)
                    st.session_state.pending_receipt = None
                    st.success("Receipt added to the ledger!")
                    st.rerun()
            if discard:
                st.session_state.pending_receipt = None
                st.info("Draft discarded.")
                st.rerun()

# ------------------------------------------------------------------------------
# TAB 3: LEDGER & ANALYTICS
# ------------------------------------------------------------------------------
with tab_ledger:
    st.subheader("Expense Ledger")

    if ledger_df.empty:
        st.info("No expenses logged yet. Add one manually or scan a receipt.")
    else:
        fc1, fc2, fc3 = st.columns([2, 1, 1])
        with fc1:
            search_term = st.text_input("\U0001F50D Search description / merchant", "")
        with fc2:
            filter_category = st.multiselect("Filter by category", options=CATEGORIES, default=[])
        with fc3:
            filter_payer = st.multiselect("Filter by payer", options=participants, default=[])

        display_df = ledger_df.copy()
        if search_term:
            display_df = display_df[display_df["description"].str.contains(search_term, case=False, na=False)]
        if filter_category:
            display_df = display_df[display_df["category"].isin(filter_category)]
        if filter_payer:
            display_df = display_df[display_df["payer"].isin(filter_payer)]

        pretty_df = display_df.copy()
        pretty_df["date"] = pretty_df["date"].dt.strftime("%Y-%m-%d")
        pretty_df["splitters"] = pretty_df["splitters"].apply(lambda s: ", ".join(s))
        pretty_df["amount"] = pretty_df["amount"].map(lambda x: f"${x:,.2f}")
        pretty_df["per_person_share"] = pretty_df["per_person_share"].map(lambda x: f"${x:,.2f}")
        pretty_df = pretty_df.rename(columns={
            "date": "Date", "payer": "Payer", "amount": "Amount", "category": "Category",
            "description": "Description", "splitters": "Split Between", "per_person_share": "Per-Person",
        })[["Date", "Payer", "Amount", "Category", "Description", "Split Between", "Per-Person"]]

        st.dataframe(pretty_df, use_container_width=True, hide_index=True)
        csv_ledger = io.StringIO()
        pretty_df.to_csv(csv_ledger, index=False)
        st.download_button(
            "⬇️ Export Ledger (CSV)",
            data=csv_ledger.getvalue(),
            file_name="tripsplit_ledger.csv",
            mime="text/csv",
            key="download_ledger_csv",
        )

        with st.expander("\U0001F5D1\uFE0F Remove an expense"):
            if not display_df.empty:
                options = {
                    f"#{row.id} — {row.description} (${row.amount:,.2f}, paid by {row.payer})": row.id
                    for row in display_df.itertuples()
                }
                to_remove_label = st.selectbox("Select expense to delete", options=list(options.keys()))
                if st.button("Delete Selected Expense", type="secondary"):
                    target_id = options[to_remove_label]
                    st.session_state.expenses = [e for e in st.session_state.expenses if e["id"] != target_id]
                    st.success("Expense removed.")
                    st.rerun()

        st.markdown("### \U0001F4C8 Spending Analytics")
        g1, g2 = st.columns(2)

        with g1:
            cat_totals = ledger_df.groupby("category", as_index=False)["amount"].sum()
            fig_pie = px.pie(
                cat_totals, names="category", values="amount", hole=0.45,
                title="Spending by Category",
                color="category", color_discrete_map=CATEGORY_COLORS,
            )
            fig_pie.update_traces(textinfo="percent+label")
            fig_pie.update_layout(margin=dict(t=60, b=10, l=10, r=10))
            st.plotly_chart(fig_pie, use_container_width=True)

        with g2:
            paid_totals = ledger_df.groupby("payer", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
            fig_bar = px.bar(
                paid_totals, x="payer", y="amount", title="Out-of-Pocket Spend per Person",
                text_auto=".2s", color="payer",
            )
            fig_bar.update_layout(showlegend=False, margin=dict(t=60, b=10, l=10, r=10), yaxis_title="Amount Paid ($)", xaxis_title="")
            st.plotly_chart(fig_bar, use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            timeline = ledger_df.sort_values("date").copy()
            timeline["cumulative"] = timeline["amount"].cumsum()
            fig_line = px.area(
                timeline, x="date", y="cumulative", title="Cumulative Trip Spend Over Time",
                markers=True,
            )
            fig_line.update_layout(margin=dict(t=60, b=10, l=10, r=10), yaxis_title="Cumulative $", xaxis_title="")
            st.plotly_chart(fig_line, use_container_width=True)

        with g4:
            cat_by_person = ledger_df.explode("splitters").groupby(["splitters", "category"])["per_person_share"].sum().reset_index()
            fig_stack = px.bar(
                cat_by_person, x="splitters", y="per_person_share", color="category",
                title="Owed Share by Person & Category", color_discrete_map=CATEGORY_COLORS,
            )
            fig_stack.update_layout(margin=dict(t=60, b=10, l=10, r=10), yaxis_title="Owed Share ($)", xaxis_title="")
            st.plotly_chart(fig_stack, use_container_width=True)

# ------------------------------------------------------------------------------
# TAB 4: SETTLEMENT ENGINE
# ------------------------------------------------------------------------------
with tab_settle:
    st.subheader("Cash-Flow Optimization Engine")

    if ledger_df.empty:
        st.info("No expenses logged yet — nothing to settle.")
    else:
        balances_df = compute_balances(ledger_df, participants)

        b1, b2 = st.columns([1.1, 1])
        with b1:
            st.markdown("#### Individual Net Balances")
            styled_balances = balances_df.copy()

            def _fmt_money(x):
                return f"${x:,.2f}"

            display_balances = styled_balances.copy()
            display_balances["Total Paid"] = display_balances["Total Paid"].map(_fmt_money)
            display_balances["Total Owed Share"] = display_balances["Total Owed Share"].map(_fmt_money)
            display_balances["Status"] = styled_balances["Net Balance"].apply(
                lambda x: "\U0001F7E2 Is Owed" if x > 0.01 else ("\U0001F534 Owes" if x < -0.01 else "\u2696\uFE0F Settled")
            )
            display_balances["Net Balance"] = styled_balances["Net Balance"].map(_fmt_money)
            st.dataframe(display_balances, use_container_width=True, hide_index=True)

        with b2:
            fig_net = px.bar(
                balances_df.sort_values("Net Balance"), x="Net Balance", y="Participant",
                orientation="h", color="Net Balance", color_continuous_scale=["#EF4444", "#D1D5DB", "#10B981"],
                title="Net Balance per Traveler",
            )
            fig_net.update_layout(margin=dict(t=60, b=10, l=10, r=10), coloraxis_showscale=False)
            st.plotly_chart(fig_net, use_container_width=True)

        st.markdown("---")
        st.markdown("#### \U0001F91D Optimized Settlement Plan (Min Cash-Flow)")
        st.caption(
            "A greedy debt-simplification algorithm matches the largest creditor against the largest "
            "debtor repeatedly, collapsing the full peer-to-peer debt mesh into the minimum number of "
            "settling transactions."
        )

        transactions = simplify_debts(balances_df)

        naive_edges = sum(1 for _, r in balances_df.iterrows() if r["Net Balance"] < -0.01) * \
            sum(1 for _, r in balances_df.iterrows() if r["Net Balance"] > 0.01)

        m1, m2, m3 = st.columns(3)
        m1.metric("Optimized Transactions", len(transactions))
        m2.metric("Naive Worst Case (all pairs)", naive_edges)
        saved = max(naive_edges - len(transactions), 0)
        m3.metric("Transactions Saved", saved)

        if not transactions:
            st.success("Everyone is already settled up! \U0001F389")
        else:
            trans_df = pd.DataFrame(transactions).rename(
                columns={"from": "Owes (From)", "to": "Paid To", "amount": "Amount"}
            )
            trans_df["Amount"] = trans_df["Amount"].map(lambda x: f"${x:,.2f}")
            st.dataframe(trans_df, use_container_width=True, hide_index=True)

            st.markdown("#### \U0001F5FA\uFE0F Debt Adjacency Heatmap")
            adj_matrix = build_adjacency_matrix(transactions, participants)
            fig_heat = go.Figure(
                data=go.Heatmap(
                    z=adj_matrix.values,
                    x=adj_matrix.columns,
                    y=adj_matrix.index,
                    colorscale="Reds",
                    text=[[f"${v:,.2f}" if v > 0 else "" for v in row] for row in adj_matrix.values],
                    texttemplate="%{text}",
                    hovertemplate="From %{y} → To %{x}<br>Amount: %{z:$.2f}<extra></extra>",
                )
            )
            fig_heat.update_layout(
                title="Who Pays Whom ($) — rows = debtor, columns = creditor",
                xaxis_title="Receives payment", yaxis_title="Sends payment",
                margin=dict(t=60, b=10, l=10, r=10),
            )
            st.plotly_chart(fig_heat, use_container_width=True)

            csv_buffer = io.StringIO()
            pd.DataFrame(transactions).to_csv(csv_buffer, index=False)
            st.download_button(
                "\u2B07\uFE0F Download Settlement Plan (CSV)",
                data=csv_buffer.getvalue(),
                file_name="tripsplit_settlement_plan.csv",
                mime="text/csv",
            )
