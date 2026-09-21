"""
TripSplit AI - Production FinTech SaaS Architecture (INR Standard + Zero-State)
================================================================================
Group expense tracking, multi-currency normalization to Indian Rupees (₹),
AI-powered receipt parsing, algorithmic min-cash-flow debt simplification,
gamified achievements, spending health analytics, and persistent SQLite backend.
"""

import io
import os
import csv
import json
import datetime as dt
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import List, Optional, Generator, Dict, Any

import pandas as pd
import numpy as np
from PIL import Image
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, Response, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

# ------------------------------------------------------------------------------
# Google GenAI SDK Support (with dual-sdk resilience)
# ------------------------------------------------------------------------------
LEGACY_GENAI_AVAILABLE = False
NEW_GENAI_AVAILABLE = False

try:
    import google.generativeai as genai_legacy
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

# ------------------------------------------------------------------------------
# MULTI-CURRENCY CONVERSION UTILITY (BASE: INDIAN RUPEES ₹)
# ------------------------------------------------------------------------------
DEFAULT_CURRENCY = "INR"
CURRENCIES = ["INR", "USD", "EUR", "GBP"]
CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}
CURRENCY_RATES_TO_INR = {
    "INR": 1.0,
    "USD": 83.50,
    "EUR": 90.50,
    "GBP": 106.50,
}

def normalize_to_inr(amount: float, currency: str) -> float:
    """Normalize foreign currencies to Indian Rupees (₹) base currency."""
    rate = CURRENCY_RATES_TO_INR.get(currency.upper(), 1.0)
    return round(float(amount) * rate, 2)

# ------------------------------------------------------------------------------
# SQLALCHEMY ORM & DATABASE PERSISTENCE LAYER (TRIP-SCOPED)
# ------------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./tripsplit.db")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TripModel(Base):
    __tablename__ = "trips"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    currency = Column(String, default="INR", nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    participants = relationship("ParticipantModel", back_populates="trip", cascade="all, delete-orphan")
    expenses = relationship("ExpenseModel", back_populates="trip", cascade="all, delete-orphan")
    settlements = relationship("SettlementModel", back_populates="trip", cascade="all, delete-orphan")


class ParticipantModel(Base):
    __tablename__ = "participants"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    trip = relationship("TripModel", back_populates="participants")

    __table_args__ = (
        UniqueConstraint("trip_id", "name", name="uix_trip_participant"),
    )


class ExpenseModel(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(String, nullable=False)  # YYYY-MM-DD
    payer = Column(String, nullable=True)
    original_amount = Column(Float, nullable=False)
    currency = Column(String, default="INR", nullable=False)
    amount = Column(Float, nullable=False)  # Normalized to INR (₹)
    category = Column(String, default="Misc", nullable=False)
    description = Column(String, nullable=False)
    splitters = Column(String, nullable=False)  # JSON-encoded array of participant names
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    trip = relationship("TripModel", back_populates="expenses")

    @property
    def splitters_list(self) -> List[str]:
        try:
            return json.loads(self.splitters)
        except Exception:
            return [s.strip() for s in self.splitters.split(",") if s.strip()]

    @property
    def split_count(self) -> int:
        return max(len(self.splitters_list), 1)

    @property
    def per_person_share(self) -> float:
        return round(self.amount / self.split_count, 2)

    @property
    def original_symbol(self) -> str:
        return CURRENCY_SYMBOLS.get(self.currency, "₹")


class SettlementModel(Base):
    __tablename__ = "settlements"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    from_name = Column(String, nullable=False)
    to_name = Column(String, nullable=False)
    is_settled = Column(Boolean, default=False, nullable=False)
    settled_at = Column(DateTime, nullable=True)

    trip = relationship("TripModel", back_populates="settlements")

    __table_args__ = (
        UniqueConstraint("trip_id", "from_name", "to_name", name="uix_trip_settlement"),
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Zero-State Initializer: strictly creates tables without pre-populating any data."""
    Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# ------------------------------------------------------------------------------
# APP & TEMPLATES SETUP
# ------------------------------------------------------------------------------
app = FastAPI(title="TripSplit AI", description="FinTech Expense & Settlement Optimization in INR", lifespan=lifespan)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

CATEGORIES = ["Food", "Lodging", "Transit", "Activities", "Misc"]
CATEGORY_COLORS = {
    "Food": {"bg": "bg-amber-500/10 dark:bg-amber-500/15", "text": "text-amber-600 dark:text-amber-400", "border": "border-amber-500/20"},
    "Lodging": {"bg": "bg-blue-500/10 dark:bg-blue-500/15", "text": "text-blue-600 dark:text-blue-400", "border": "border-blue-500/20"},
    "Transit": {"bg": "bg-emerald-500/10 dark:bg-emerald-500/15", "text": "text-emerald-600 dark:text-emerald-400", "border": "border-emerald-500/20"},
    "Activities": {"bg": "bg-rose-500/10 dark:bg-rose-500/15", "text": "text-rose-600 dark:text-rose-400", "border": "border-rose-500/20"},
    "Misc": {"bg": "bg-purple-500/10 dark:bg-purple-500/15", "text": "text-purple-600 dark:text-purple-400", "border": "border-purple-500/20"},
}

GLOBAL_API_KEY_OVERRIDE: str = ""

def get_effective_api_key(override: Optional[str] = None) -> str:
    global GLOBAL_API_KEY_OVERRIDE
    if override and override.strip():
        return override.strip()
    if GLOBAL_API_KEY_OVERRIDE.strip():
        return GLOBAL_API_KEY_OVERRIDE.strip()
    return os.environ.get("GOOGLE_API_KEY", "").strip()


# ------------------------------------------------------------------------------
# GAMIFIED ACHIEVEMENTS & SPENDING HEALTH ANALYTICS
# ------------------------------------------------------------------------------
def compute_achievements(participants: List[str], expenses_models: List[ExpenseModel], balances: List[dict]) -> List[dict]:
    """Calculate fun dynamic badges based on group spending patterns."""
    if not participants or not expenses_models:
        return []

    paid_totals = defaultdict(float)
    paid_counts = defaultdict(int)

    for em in expenses_models:
        if em.payer:
            paid_totals[em.payer] += em.amount
            paid_counts[em.payer] += 1

    badges = []

    # 1. Highest Spender
    if paid_totals:
        highest_payer = max(paid_totals.items(), key=lambda kv: kv[1])
        if highest_payer[1] > 0:
            badges.append({
                "title": "Highest Spender",
                "recipient": highest_payer[0],
                "icon": "👑",
                "desc": f"Contributed ₹{highest_payer[1]:,.2f} out of pocket",
                "color": "from-amber-500/20 to-orange-500/20 border-amber-500/40 text-amber-500 dark:text-amber-400"
            })

    # 2. Lowest Spender (active)
    active_payers = {k: v for k, v in paid_totals.items() if v > 0}
    if len(active_payers) > 1:
        lowest_payer = min(active_payers.items(), key=lambda kv: kv[1])
        badges.append({
            "title": "Budget Guardian",
            "recipient": lowest_payer[0],
            "icon": "🪙",
            "desc": f"Prudently paid ₹{lowest_payer[1]:,.2f}",
            "color": "from-blue-500/20 to-cyan-500/20 border-blue-500/40 text-blue-500 dark:text-blue-400"
        })

    # 3. Most Frequent Payer
    if paid_counts:
        most_frequent = max(paid_counts.items(), key=lambda kv: kv[1])
        badges.append({
            "title": "Frequent Swiper",
            "recipient": most_frequent[0],
            "icon": "⚡",
            "desc": f"Logged {most_frequent[1]} individual expense transactions",
            "color": "from-indigo-500/20 to-purple-500/20 border-indigo-500/40 text-indigo-500 dark:text-indigo-400"
        })

    # 4. Zero-Debt Hero
    zero_debtors = [b["participant"] for b in balances if abs(b["net"]) <= 0.01]
    if zero_debtors:
        badges.append({
            "title": "Zero-Debt Hero",
            "recipient": zero_debtors[0] if len(zero_debtors) == 1 else f"{len(zero_debtors)} Travelers",
            "icon": "🛡️",
            "desc": "Perfectly settled with zero outstanding liabilities",
            "color": "from-emerald-500/20 to-teal-500/20 border-emerald-500/40 text-emerald-500 dark:text-emerald-400"
        })

    return badges


def compute_spending_health(total_spend: float, num_participants: int, num_expenses: int) -> dict:
    """Analyze group spend velocity and return visual progress meter metrics."""
    if num_participants == 0:
        return {
            "status": "Awaiting Travelers",
            "score": 0,
            "badge": "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-400",
            "meter_width": 0,
            "color": "bg-slate-500",
            "tip": "Add travelers to activate the group financial velocity meter."
        }

    avg = total_spend / num_participants
    if total_spend == 0:
        return {
            "status": "Fresh Canvas",
            "score": 100,
            "badge": "bg-blue-100 text-blue-800 dark:bg-blue-500/20 dark:text-blue-300",
            "meter_width": 5,
            "color": "bg-blue-500",
            "tip": "Trip budget initialized! Log your first expense to begin tracking."
        }

    if avg < 10000:
        return {
            "status": "Budget Optimal 🟢",
            "score": 92,
            "badge": "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-400",
            "meter_width": 35,
            "color": "bg-emerald-500",
            "tip": f"Avg spend of ₹{avg:,.2f} per person is highly balanced and prudent."
        }
    elif avg < 40000:
        return {
            "status": "Moderate Pace 🟡",
            "score": 75,
            "badge": "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-400",
            "meter_width": 68,
            "color": "bg-amber-500",
            "tip": f"Group expenditure is accelerating at ₹{avg:,.2f}/person. Maintain category balance."
        }
    else:
        return {
            "status": "High Spend Velocity 🟣",
            "score": 58,
            "badge": "bg-purple-100 text-purple-800 dark:bg-purple-500/20 dark:text-purple-400",
            "meter_width": 94,
            "color": "bg-purple-500",
            "tip": f"High expenditure detected (₹{avg:,.2f}/person). Review Lodging and Transit line-items."
        }


# ------------------------------------------------------------------------------
# FINANCIAL & CASH-FLOW ALGORITHMIC ENGINE (IN INR ₹, TRIP-SCOPED)
# ------------------------------------------------------------------------------
def get_active_trip(request: Request, db: Session, trip_id: Optional[int] = None) -> Optional[TripModel]:
    """Resolve the active trip from parameter, query string, cookie, or most recent."""
    if trip_id:
        trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
        if trip:
            return trip

    # Query param in request
    param_id = request.query_params.get("trip_id")
    if param_id and param_id.isdigit():
        trip = db.query(TripModel).filter(TripModel.id == int(param_id)).first()
        if trip:
            return trip

    # Cookie
    cookie_id = request.cookies.get("tripsplit_active_trip")
    if cookie_id and cookie_id.isdigit():
        trip = db.query(TripModel).filter(TripModel.id == int(cookie_id)).first()
        if trip:
            return trip

    # Most recent trip
    return db.query(TripModel).order_by(TripModel.id.desc()).first()


def compute_financials(db: Session, active_trip: Optional[TripModel] = None, active_tab: str = "group") -> Dict[str, Any]:
    all_trips = db.query(TripModel).order_by(TripModel.id.desc()).all()

    if not active_trip:
        return {
            "all_trips": all_trips,
            "active_trip": None,
            "participants": [],
            "expenses": [],
            "balances": [],
            "transactions": [],
            "matrix": {},
            "total_spend": 0.0,
            "avg_spend": 0.0,
            "total_expenses": 0,
            "total_travelers": 0,
            "naive_edges": 0,
            "saved_transactions": 0,
            "saved_percent": 0.0,
            "settled_count": 0,
            "settled_amount": 0.0,
            "category_spend": {},
            "categories": CATEGORIES,
            "category_colors": CATEGORY_COLORS,
            "currencies": CURRENCIES,
            "currency_symbols": CURRENCY_SYMBOLS,
            "currency_rates": CURRENCY_RATES_TO_INR,
            "achievements": [],
            "health": compute_spending_health(0, 0, 0),
            "individual_profiles": {},
            "active_view": active_tab,
        }

    participants = [p.name for p in db.query(ParticipantModel).filter(ParticipantModel.trip_id == active_trip.id).order_by(ParticipantModel.id).all()]
    expenses_models = db.query(ExpenseModel).filter(ExpenseModel.trip_id == active_trip.id).order_by(ExpenseModel.date.desc(), ExpenseModel.id.desc()).all()

    expenses = []
    paid = defaultdict(float)
    owed = defaultdict(float)
    category_spend = defaultdict(float)
    total_spend = 0.0

    for em in expenses_models:
        splitters = [s for s in em.splitters_list if s in participants] or participants[:]
        split_count = max(len(splitters), 1)
        exact_share = em.amount / split_count
        per_person = round(exact_share, 2)
        total_spend += em.amount

        if em.payer and em.payer in participants:
            paid[em.payer] += em.amount
        category_spend[em.category] += em.amount

        for person in splitters:
            owed[person] += exact_share

        expenses.append({
            "id": em.id,
            "date": em.date,
            "payer": em.payer,
            "original_amount": em.original_amount,
            "currency": em.currency,
            "original_symbol": em.original_symbol,
            "amount": em.amount,
            "category": em.category,
            "description": em.description,
            "splitters": splitters,
            "split_count": split_count,
            "per_person_share": per_person,
        })

    # Raw Balances before rounding
    raw_balances = []
    for p in participants:
        p_paid = paid.get(p, 0.0)
        p_owed = owed.get(p, 0.0)
        p_net = p_paid - p_owed
        raw_balances.append({
            "participant": p,
            "paid": round(p_paid, 2),
            "owed": round(p_owed, 2),
            "net": round(p_net, 2),
        })

    # Invariant: Guarantee strict zero-sum balancing (sum of net balances == 0.00)
    if raw_balances:
        net_sum = round(sum(b["net"] for b in raw_balances), 2)
        if abs(net_sum) >= 0.01:
            # Rebalance the residual penny onto the participant with the largest net magnitude
            max_bal = max(raw_balances, key=lambda b: abs(b["net"]))
            max_bal["net"] = round(max_bal["net"] - net_sum, 2)

    balances = []
    for b in raw_balances:
        p_net = b["net"]
        balances.append({
            "participant": b["participant"],
            "paid": b["paid"],
            "owed": b["owed"],
            "net": p_net,
            "status": "creditor" if p_net > 0.01 else ("debtor" if p_net < -0.01 else "settled")
        })

    # Greedy min-cash-flow simplification algorithm
    epsilon = 0.01
    creditors = {b["participant"]: b["net"] for b in balances if b["net"] > epsilon}
    debtors = {b["participant"]: -b["net"] for b in balances if b["net"] < -epsilon}

    # Ensure total creditor balance matches total debtor balance strictly
    sum_c = round(sum(creditors.values()), 2)
    sum_d = round(sum(debtors.values()), 2)
    if abs(sum_c - sum_d) >= epsilon:
        residual = round(sum_c - sum_d, 2)
        if residual > 0 and debtors:
            max_k = max(debtors.keys(), key=lambda k: debtors[k])
            debtors[max_k] = round(debtors[max_k] + residual, 2)
        elif residual < 0 and creditors:
            max_k = max(creditors.keys(), key=lambda k: creditors[k])
            creditors[max_k] = round(creditors[max_k] - residual, 2)

    cred_items = sorted(creditors.items(), key=lambda kv: -kv[1])
    debt_items = sorted(debtors.items(), key=lambda kv: -kv[1])

    transactions = []
    ci, di = 0, 0
    while ci < len(cred_items) and di < len(debt_items):
        c_name, c_amt = cred_items[ci]
        d_name, d_amt = debt_items[di]
        settle = round(min(c_amt, d_amt), 2)

        if settle > epsilon:
            transactions.append({
                "from": d_name,
                "to": c_name,
                "amount": settle
            })

        c_amt = round(c_amt - settle, 2)
        d_amt = round(d_amt - settle, 2)
        cred_items[ci] = (c_name, c_amt)
        debt_items[di] = (d_name, d_amt)

        if c_amt <= epsilon:
            ci += 1
        if d_amt <= epsilon:
            di += 1

    # Attach interactive settlement status from database
    settlement_records = {
        (s.from_name, s.to_name): s
        for s in db.query(SettlementModel).filter(SettlementModel.trip_id == active_trip.id).all()
    }
    for t in transactions:
        rec = settlement_records.get((t["from"], t["to"]))
        t["is_settled"] = bool(rec and rec.is_settled)
        t["settled_at"] = rec.settled_at.strftime("%b %d, %H:%M") if (rec and rec.settled_at) else None

    settled_count = sum(1 for t in transactions if t.get("is_settled"))
    settled_amount = round(sum(t["amount"] for t in transactions if t.get("is_settled")), 2)

    # Metrics calculation & Savings percentage
    naive_edges = len(debtors) * len(creditors)
    saved_transactions = max(0, naive_edges - len(transactions))
    saved_percent = round((saved_transactions / naive_edges) * 100, 1) if naive_edges > 0 else 0.0
    avg_spend = round(total_spend / len(participants), 2) if participants else 0.0

    # Adjacency matrix for payment distribution
    matrix = {p: {other: 0.0 for other in participants} for p in participants}
    for t in transactions:
        if t["from"] in matrix and t["to"] in matrix[t["from"]]:
            matrix[t["from"]][t["to"]] = t["amount"]

    # Individual drill-down profiles
    individual_profiles = {}
    for p in participants:
        p_paid = round(paid.get(p, 0.0), 2)
        p_owed = round(owed.get(p, 0.0), 2)
        p_net = round(p_paid - p_owed, 2)
        owes_to = [t for t in transactions if t["from"] == p]
        receives_from = [t for t in transactions if t["to"] == p]
        paid_expenses = [e for e in expenses if e["payer"] == p]
        shared_expenses = [e for e in expenses if p in e["splitters"]]

        individual_profiles[p] = {
            "name": p,
            "paid": p_paid,
            "owed": p_owed,
            "net": p_net,
            "owes_to": owes_to,
            "receives_from": receives_from,
            "paid_count": len(paid_expenses),
            "shared_count": len(shared_expenses),
            "status": "creditor" if p_net > 0.01 else ("debtor" if p_net < -0.01 else "settled")
        }

    # Gamified badges & spending health
    achievements = compute_achievements(participants, expenses_models, balances)
    health = compute_spending_health(total_spend, len(participants), len(expenses))

    return {
        "all_trips": all_trips,
        "active_trip": active_trip,
        "participants": participants,
        "expenses": expenses,
        "balances": sorted(balances, key=lambda x: x["net"], reverse=True),
        "transactions": transactions,
        "settled_count": settled_count,
        "settled_amount": settled_amount,
        "matrix": matrix,
        "total_spend": round(total_spend, 2),
        "avg_spend": avg_spend,
        "total_expenses": len(expenses),
        "total_travelers": len(participants),
        "naive_edges": naive_edges,
        "saved_transactions": saved_transactions,
        "saved_percent": saved_percent,
        "category_spend": dict(category_spend),
        "categories": CATEGORIES,
        "category_colors": CATEGORY_COLORS,
        "currencies": CURRENCIES,
        "currency_symbols": CURRENCY_SYMBOLS,
        "currency_rates": CURRENCY_RATES_TO_INR,
        "achievements": achievements,
        "health": health,
        "individual_profiles": individual_profiles,
        "active_view": active_tab,
    }


# ------------------------------------------------------------------------------
# GOOGLE GEMINI RECEIPT PARSER (with INR default)
# ------------------------------------------------------------------------------
RECEIPT_PROMPT = """You are an ultra-precise FinTech receipt parser.
Look at the attached receipt image and extract structured data as STRICT JSON.
DO NOT include markdown fences, extra commentary, or conversational remarks.
Return ONLY valid JSON matching this schema:

{
  "merchant": "<string, vendor/business name>",
  "total_amount": <number, final total paid without currency symbol>,
  "currency": "<one of: INR, USD, EUR, GBP>",
  "category": "<one of: Food, Lodging, Transit, Activities, Misc>",
  "date": "<YYYY-MM-DD, transaction date or today's date>",
  "description": "<short 3-8 word human summary of items>"
}
"""

def parse_receipt_ai(image_bytes: bytes, mime_type: str, api_key: str) -> dict:
    if not GENAI_SDK_AVAILABLE:
        raise RuntimeError("google-generativeai SDK is not available.")
    if not api_key:
        raise RuntimeError("No Gemini API key provided. Set GOOGLE_API_KEY or input in sidebar.")

    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash"]
    last_error = None

    if LEGACY_GENAI_AVAILABLE:
        genai_legacy.configure(api_key=api_key)
        pil_img = Image.open(io.BytesIO(image_bytes))
        for model in models_to_try:
            try:
                m = genai_legacy.GenerativeModel(
                    model_name=model,
                    generation_config={"response_mime_type": "application/json", "temperature": 0.1}
                )
                resp = m.generate_content([RECEIPT_PROMPT, pil_img])
                cleaned = resp.text.strip().replace("```json", "").replace("```", "").strip()
                return json.loads(cleaned)
            except Exception as err:
                last_error = err
                continue

    if NEW_GENAI_AVAILABLE:
        client = new_genai.Client(api_key=api_key)
        part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        for model in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[RECEIPT_PROMPT, part],
                    config=genai_types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
                )
                cleaned = resp.text.strip().replace("```json", "").replace("```", "").strip()
                return json.loads(cleaned)
            except Exception as err:
                last_error = err
                continue

    raise RuntimeError(f"Gemini receipt parsing failed across fallback models. Last error: {last_error}")


# ------------------------------------------------------------------------------
# FASTAPI ENDPOINTS WITH MULTI-TRIP & SETTLEMENT CHECKMARKS
# ------------------------------------------------------------------------------
def build_context(request: Request, db: Session, active_trip: Optional[TripModel] = None) -> Dict[str, Any]:
    ctx = compute_financials(db, active_trip)
    ctx.update({
        "request": request,
        "has_api_key": bool(get_effective_api_key()),
        "today_date": dt.date.today().strftime("%Y-%m-%d"),
    })
    return ctx


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, trip_id: Optional[int] = None, db: Session = Depends(get_db)):
    active_trip = get_active_trip(request, db, trip_id=trip_id)
    ctx = build_context(request, db, active_trip)
    resp = templates.TemplateResponse(request=request, name="index.html", context=ctx)
    if active_trip:
        resp.set_cookie("tripsplit_active_trip", str(active_trip.id), max_age=30*86400, httponly=True, samesite="lax")
    return resp


# ------------------------------------------------------------------------------
# MULTI-TRIP MANAGEMENT ENDPOINTS
# ------------------------------------------------------------------------------
@app.post("/api/trips", response_class=HTMLResponse)
async def create_trip_endpoint(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    clean_name = name.strip() or "New Trip"
    new_trip = TripModel(name=clean_name, currency="INR")
    db.add(new_trip)
    db.commit()
    db.refresh(new_trip)

    ctx = build_context(request, db, new_trip)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    resp.set_cookie("tripsplit_active_trip", str(new_trip.id), max_age=30*86400, httponly=True, samesite="lax")
    return resp


@app.post("/api/trips/select", response_class=HTMLResponse)
async def select_trip_endpoint(request: Request, trip_id: int = Form(...), db: Session = Depends(get_db)):
    active_trip = get_active_trip(request, db, trip_id=trip_id)
    ctx = build_context(request, db, active_trip)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    if active_trip:
        resp.set_cookie("tripsplit_active_trip", str(active_trip.id), max_age=30*86400, httponly=True, samesite="lax")
    return resp


@app.post("/api/trips/{trip_id}/delete", response_class=HTMLResponse)
async def delete_trip_endpoint(request: Request, trip_id: int, db: Session = Depends(get_db)):
    target_trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
    if target_trip:
        db.delete(target_trip)
        db.commit()

    active_trip = db.query(TripModel).order_by(TripModel.id.desc()).first()
    ctx = build_context(request, db, active_trip)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    if active_trip:
        resp.set_cookie("tripsplit_active_trip", str(active_trip.id), max_age=30*86400, httponly=True, samesite="lax")
    else:
        resp.delete_cookie("tripsplit_active_trip")
    return resp


# ------------------------------------------------------------------------------
# SETTLEMENT CHECKMARK TOGGLE ENDPOINT
# ------------------------------------------------------------------------------
@app.post("/api/settlements/toggle", response_class=HTMLResponse)
async def toggle_settlement_endpoint(
    request: Request,
    from_name: str = Form(...),
    to_name: str = Form(...),
    db: Session = Depends(get_db)
):
    active_trip = get_active_trip(request, db)
    if active_trip:
        rec = db.query(SettlementModel).filter(
            SettlementModel.trip_id == active_trip.id,
            SettlementModel.from_name == from_name,
            SettlementModel.to_name == to_name
        ).first()

        if not rec:
            rec = SettlementModel(
                trip_id=active_trip.id,
                from_name=from_name,
                to_name=to_name,
                is_settled=True,
                settled_at=dt.datetime.utcnow()
            )
            db.add(rec)
        else:
            rec.is_settled = not rec.is_settled
            rec.settled_at = dt.datetime.utcnow() if rec.is_settled else None
        db.commit()

    ctx = build_context(request, db, active_trip)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


# ------------------------------------------------------------------------------
# RESET STATE ENDPOINT (PRISTINE ZERO-STATE)
# ------------------------------------------------------------------------------
@app.post("/api/reset", response_class=HTMLResponse)
async def reset_endpoint(request: Request, db: Session = Depends(get_db)):
    """Wipes all data and returns to pristine zero-state (0 trips, 0 travelers, 0 expenses)."""
    db.query(ExpenseModel).delete()
    db.query(ParticipantModel).delete()
    db.query(SettlementModel).delete()
    db.query(TripModel).delete()
    db.commit()

    ctx = build_context(request, db, None)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    resp.delete_cookie("tripsplit_active_trip")
    return resp


@app.post("/api/key", response_class=HTMLResponse)
async def set_api_key(request: Request, api_key: str = Form(""), db: Session = Depends(get_db)):
    global GLOBAL_API_KEY_OVERRIDE
    GLOBAL_API_KEY_OVERRIDE = api_key.strip()
    active_trip = get_active_trip(request, db)
    ctx = build_context(request, db, active_trip)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


# ------------------------------------------------------------------------------
# PARTICIPANTS & EXPENSES ENDPOINTS (TRIP-SCOPED)
# ------------------------------------------------------------------------------
@app.post("/api/participants", response_class=HTMLResponse)
async def add_participant_endpoint(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    active_trip = get_active_trip(request, db)
    if not active_trip:
        # Create a default trip if none exists
        active_trip = TripModel(name="My Trip", currency="INR")
        db.add(active_trip)
        db.commit()
        db.refresh(active_trip)

    cleaned = (name or "").strip()
    if cleaned:
        existing = db.query(ParticipantModel).filter(
            ParticipantModel.trip_id == active_trip.id,
            ParticipantModel.name == cleaned
        ).first()
        if not existing:
            db.add(ParticipantModel(trip_id=active_trip.id, name=cleaned))
            db.commit()

    ctx = build_context(request, db, active_trip)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    resp.set_cookie("tripsplit_active_trip", str(active_trip.id), max_age=30*86400, httponly=True, samesite="lax")
    return resp


@app.post("/api/participants/{name}/delete", response_class=HTMLResponse)
async def delete_participant_endpoint(request: Request, name: str, db: Session = Depends(get_db)):
    active_trip = get_active_trip(request, db)
    if active_trip:
        target = db.query(ParticipantModel).filter(
            ParticipantModel.trip_id == active_trip.id,
            ParticipantModel.name == name
        ).first()
        if target:
            db.delete(target)
            # Clean up splitters in expenses for this trip
            all_expenses = db.query(ExpenseModel).filter(ExpenseModel.trip_id == active_trip.id).all()
            for exp in all_expenses:
                splitters = exp.splitters_list
                if name in splitters:
                    splitters = [s for s in splitters if s != name]
                    exp.splitters = json.dumps(splitters)
                if exp.payer == name:
                    exp.payer = None
            db.commit()

    ctx = build_context(request, db, active_trip)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


@app.post("/api/expenses", response_class=HTMLResponse)
async def add_expense_endpoint(
    request: Request,
    payer: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("INR"),
    category: str = Form("Misc"),
    date: str = Form(...),
    description: str = Form(""),
    splitters: Optional[List[str]] = Form(None),
    db: Session = Depends(get_db)
):
    active_trip = get_active_trip(request, db)
    if not active_trip:
        active_trip = TripModel(name="My Trip", currency="INR")
        db.add(active_trip)
        db.commit()
        db.refresh(active_trip)

    all_participants = [p.name for p in db.query(ParticipantModel).filter(ParticipantModel.trip_id == active_trip.id).all()]
    selected_splitters = splitters or all_participants[:]
    clean_splitters = [s for s in selected_splitters if s in all_participants] or all_participants[:]

    if amount > 0:
        clean_amount = min(float(amount), 100_000_000.0)
        clean_currency = currency.upper() if currency.upper() in CURRENCIES else "INR"
        normalized_inr = normalize_to_inr(clean_amount, clean_currency)
        new_exp = ExpenseModel(
            trip_id=active_trip.id,
            date=date,
            payer=payer,
            original_amount=round(float(clean_amount), 2),
            currency=clean_currency,
            amount=normalized_inr,
            category=category if category in CATEGORIES else "Misc",
            description=description.strip() or "Expense",
            splitters=json.dumps(clean_splitters)
        )
        db.add(new_exp)
        db.commit()

    ctx = build_context(request, db, active_trip)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    resp.set_cookie("tripsplit_active_trip", str(active_trip.id), max_age=30*86400, httponly=True, samesite="lax")
    return resp


@app.post("/api/expenses/{expense_id}/delete", response_class=HTMLResponse)
async def delete_expense_endpoint(request: Request, expense_id: int, db: Session = Depends(get_db)):
    active_trip = get_active_trip(request, db)
    if active_trip:
        exp = db.query(ExpenseModel).filter(
            ExpenseModel.trip_id == active_trip.id,
            ExpenseModel.id == expense_id
        ).first()
        if exp:
            db.delete(exp)
            db.commit()

    ctx = build_context(request, db, active_trip)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


@app.post("/api/scan-receipt", response_class=HTMLResponse)
async def scan_receipt_endpoint(
    request: Request,
    receipt_file: UploadFile = File(...),
    api_key_override: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    api_key = get_effective_api_key(api_key_override)
    if not api_key:
        return HTMLResponse(
            """<div class="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-500 dark:text-rose-400 text-sm">
                <strong>Error:</strong> No Gemini API key detected. Please add your key in the sidebar or set GOOGLE_API_KEY.
            </div>"""
        )

    try:
        content = await receipt_file.read()
        mime_type = receipt_file.content_type or "image/jpeg"
        data = parse_receipt_ai(content, mime_type, api_key)
        
        detected_curr = data.get("currency", "INR").upper()
        if detected_curr not in CURRENCIES:
            detected_curr = "INR"

        active_trip = get_active_trip(request, db)
        participants = [p.name for p in db.query(ParticipantModel).filter(ParticipantModel.trip_id == active_trip.id).order_by(ParticipantModel.id).all()] if active_trip else []
        
        ctx = {
            "request": request,
            "merchant": data.get("merchant", "Merchant"),
            "amount": float(data.get("total_amount", 0.0)),
            "currency": detected_curr,
            "category": data.get("category", "Misc") if data.get("category") in CATEGORIES else "Misc",
            "date": data.get("date", dt.date.today().strftime("%Y-%m-%d")),
            "description": data.get("description", "Receipt items"),
            "participants": participants,
            "categories": CATEGORIES,
            "currencies": CURRENCIES,
            "currency_symbols": CURRENCY_SYMBOLS,
        }
        return templates.TemplateResponse(request=request, name="partials/receipt_review.html", context=ctx)
    except Exception as e:
        return HTMLResponse(
            f"""<div class="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-500 dark:text-rose-400 text-sm">
                <strong>AI Parsing Error:</strong> {str(e)}
            </div>"""
        )


@app.post("/api/expenses/confirm-receipt", response_class=HTMLResponse)
async def confirm_receipt_endpoint(
    request: Request,
    payer: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("INR"),
    category: str = Form("Misc"),
    date: str = Form(...),
    description: str = Form(""),
    splitters: Optional[List[str]] = Form(None),
    db: Session = Depends(get_db)
):
    active_trip = get_active_trip(request, db)
    if not active_trip:
        active_trip = TripModel(name="My Trip", currency="INR")
        db.add(active_trip)
        db.commit()
        db.refresh(active_trip)

    all_participants = [p.name for p in db.query(ParticipantModel).filter(ParticipantModel.trip_id == active_trip.id).all()]
    selected_splitters = splitters or all_participants[:]
    clean_splitters = [s for s in selected_splitters if s in all_participants] or all_participants[:]

    if amount > 0:
        clean_amount = min(float(amount), 100_000_000.0)
        clean_currency = currency.upper() if currency.upper() in CURRENCIES else "INR"
        normalized_inr = normalize_to_inr(clean_amount, clean_currency)
        new_exp = ExpenseModel(
            trip_id=active_trip.id,
            date=date,
            payer=payer,
            original_amount=round(float(clean_amount), 2),
            currency=clean_currency,
            amount=normalized_inr,
            category=category if category in CATEGORIES else "Misc",
            description=description.strip() or "Receipt Purchase",
            splitters=json.dumps(clean_splitters)
        )
        db.add(new_exp)
        db.commit()

    ctx = build_context(request, db, active_trip)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    resp.set_cookie("tripsplit_active_trip", str(active_trip.id), max_age=30*86400, httponly=True, samesite="lax")
    return resp


# ------------------------------------------------------------------------------
# UNIVERSAL CURRENCY CONVERTER ENDPOINTS
# ------------------------------------------------------------------------------
@app.get("/api/fx/rates")
async def get_fx_rates():
    """Return exchange rates to INR and symbol map for live front-end calculators."""
    return {
        "base": "INR",
        "rates": CURRENCY_RATES_TO_INR,
        "symbols": CURRENCY_SYMBOLS
    }


@app.get("/api/fx/convert")
async def convert_currency(amount: float = 1.0, from_curr: str = "USD", to_curr: str = "INR"):
    """Instant normalization and conversion between supported currencies."""
    clean_from = from_curr.upper() if from_curr.upper() in CURRENCIES else "USD"
    clean_to = to_curr.upper() if to_curr.upper() in CURRENCIES else "INR"
    
    # Calculate amount in base INR
    rate_to_inr = CURRENCY_RATES_TO_INR.get(clean_from, 1.0)
    inr_amount = float(amount) * rate_to_inr
    
    # Convert from INR to target currency
    rate_from_inr = 1.0 / CURRENCY_RATES_TO_INR.get(clean_to, 1.0)
    target_amount = round(inr_amount * rate_from_inr, 2)
    
    return {
        "amount": amount,
        "from": clean_from,
        "to": clean_to,
        "result": target_amount,
        "rate": round(rate_to_inr * rate_from_inr, 4),
        "inr_equivalent": round(inr_amount, 2),
        "from_symbol": CURRENCY_SYMBOLS.get(clean_from, ""),
        "to_symbol": CURRENCY_SYMBOLS.get(clean_to, ""),
    }


# ------------------------------------------------------------------------------
# CSV EXPORT ROUTES (TRIP-SCOPED)
# ------------------------------------------------------------------------------
@app.get("/api/export/settlement")
async def export_settlement_csv(request: Request, db: Session = Depends(get_db)):
    active_trip = get_active_trip(request, db)
    fin = compute_financials(db, active_trip)
    transactions = fin["transactions"]
    trip_title = (active_trip.name if active_trip else "trip").replace(" ", "_").lower()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["From (Debtor)", "To (Creditor)", "Amount (INR ₹)", "Status"])
    for t in transactions:
        writer.writerow([t["from"], t["to"], f"{t['amount']:.2f}", "Settled" if t.get("is_settled") else "Pending"])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=tripsplit_{trip_title}_settlement.csv"}
    )


@app.get("/api/export/ledger")
async def export_ledger_csv(request: Request, db: Session = Depends(get_db)):
    active_trip = get_active_trip(request, db)
    fin = compute_financials(db, active_trip)
    expenses = fin["expenses"]
    trip_title = (active_trip.name if active_trip else "trip").replace(" ", "_").lower()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Date", "Payer", "Original Amount", "Currency",
        "Normalized Amount (INR ₹)", "Category", "Description",
        "Split Between", "Per-Person Share (INR ₹)"
    ])
    for e in sorted(expenses, key=lambda x: x["date"], reverse=True):
        writer.writerow([
            e["id"],
            e["date"],
            e["payer"] or "N/A",
            f"{e['original_amount']:.2f}",
            e["currency"],
            f"{e['amount']:.2f}",
            e["category"],
            e["description"],
            ", ".join(e["splitters"]),
            f"{e['per_person_share']:.2f}"
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=tripsplit_{trip_title}_ledger.csv"}
    )
