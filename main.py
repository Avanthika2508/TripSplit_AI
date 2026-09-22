"""
TripSplit AI - Production FinTech Collaborative SaaS Architecture
===================================================================================
Features:
1. User Authentication (Registration, Login, Password Hashing via bcrypt, signed session tokens).
2. Supabase / PostgreSQL Support via DATABASE_URL with automatic SQLite fallback.
3. Trip Collaboration Workspace & Shareable Access Keys (/join/{join_code}).
4. Collaborative Permissions (Host vs Member) and Multi-Tenant Trip Isolation.
5. Multimodal Receipt Parsing via Google Gemini Flash.
6. Algorithmic Min-Cash-Flow Cash-Flow Optimization.
7. Universal Multi-Currency Normalization to Indian Rupees (₹).
8. Gamified Achievements, Spend Velocity Health Meter, and Expense Ledger.
"""

import io
import os
import csv
import json
import secrets
import string
import logging
import urllib.parse
import datetime as dt
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import List, Optional, Generator, Dict, Any

import bcrypt
from itsdangerous import URLSafeTimedSerializer
from PIL import Image
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, Response, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, Boolean,
    ForeignKey, UniqueConstraint, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

logger = logging.getLogger("tripsplit")

# ------------------------------------------------------------------------------
# Google GenAI SDK Support (dual-sdk resilience)
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
# SQLALCHEMY ORM & SUPABASE / POSTGRESQL / SQLITE PERSISTENCE LAYER
# ------------------------------------------------------------------------------
raw_db_url = os.environ.get("DATABASE_URL", "sqlite:///./tripsplit.db")
if raw_db_url.startswith("postgres://"):
    # SQLAlchemy 1.4+ requires postgresql://
    raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
DATABASE_URL = raw_db_url

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserModel(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    hosted_trips = relationship("TripModel", back_populates="host_user", foreign_keys="TripModel.host_user_id")
    memberships = relationship("TripMemberModel", back_populates="user", cascade="all, delete-orphan")
    created_expenses = relationship("ExpenseModel", back_populates="created_by_user")


class TripModel(Base):
    __tablename__ = "trips"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    host_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    join_code = Column(String(32), unique=True, index=True, nullable=False)
    base_currency = Column(String(10), default="INR", nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    host_user = relationship("UserModel", back_populates="hosted_trips", foreign_keys=[host_user_id])
    members = relationship("TripMemberModel", back_populates="trip", cascade="all, delete-orphan")
    expenses = relationship("ExpenseModel", back_populates="trip", cascade="all, delete-orphan")
    settlements = relationship("SettlementStatusModel", back_populates="trip", cascade="all, delete-orphan")
    participants = relationship("ParticipantModel", back_populates="trip", cascade="all, delete-orphan")

    @property
    def currency(self) -> str:
        return self.base_currency


class TripMemberModel(Base):
    __tablename__ = "trip_members"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), default="member", nullable=False)  # 'host' or 'member'
    joined_at = Column(DateTime, default=dt.datetime.utcnow)

    trip = relationship("TripModel", back_populates="members")
    user = relationship("UserModel", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("trip_id", "user_id", name="uix_trip_member"),
    )


class ParticipantModel(Base):
    __tablename__ = "participants"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    trip = relationship("TripModel", back_populates="participants")

    __table_args__ = (
        UniqueConstraint("trip_id", "name", name="uix_trip_participant"),
    )


class ExpenseModel(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    payer_name = Column(String(100), nullable=False)
    amount = Column(Float, nullable=False)  # Normalized to INR (₹)
    original_amount = Column(Float, nullable=False)
    currency = Column(String(10), default="INR", nullable=False)
    category = Column(String(50), default="Miscellaneous", nullable=False)
    description = Column(String(255), default="", nullable=False)
    beneficiaries_json = Column(String, nullable=False)  # JSON-encoded array of participant names
    date = Column(String(20), nullable=False)  # YYYY-MM-DD
    receipt_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    trip = relationship("TripModel", back_populates="expenses")
    created_by_user = relationship("UserModel", back_populates="created_expenses")

    @property
    def payer(self) -> str:
        return self.payer_name

    @property
    def splitters(self) -> str:
        return self.beneficiaries_json

    @property
    def splitters_list(self) -> List[str]:
        try:
            return json.loads(self.beneficiaries_json)
        except Exception:
            return [s.strip() for s in self.beneficiaries_json.split(",") if s.strip()]

    @property
    def split_count(self) -> int:
        return max(len(self.splitters_list), 1)

    @property
    def per_person_share(self) -> float:
        return round(self.amount / self.split_count, 2)

    @property
    def original_symbol(self) -> str:
        return CURRENCY_SYMBOLS.get(self.currency, "₹")


class SettlementStatusModel(Base):
    __tablename__ = "settlements"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True)
    from_user = Column(String(100), nullable=False)
    to_user = Column(String(100), nullable=False)
    amount = Column(Float, default=0.0, nullable=False)
    is_settled = Column(Boolean, default=False, nullable=False)
    settled_at = Column(DateTime, nullable=True)

    trip = relationship("TripModel", back_populates="settlements")

    @property
    def from_name(self) -> str:
        return self.from_user

    @property
    def to_name(self) -> str:
        return self.to_user

    __table_args__ = (
        UniqueConstraint("trip_id", "from_user", "to_user", name="uix_trip_settlement_status"),
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Zero-State Initializer: strictly creates tables and upgrades schema if necessary."""
    Base.metadata.create_all(bind=engine)
    if "sqlite" in DATABASE_URL:
        with engine.connect() as conn:
            try:
                res = conn.execute(text("PRAGMA table_info(trips);")).fetchall()
                cols = [r[1] for r in res]
                if len(cols) > 0 and "host_user_id" not in cols:
                    conn.execute(text("DROP TABLE IF EXISTS settlements;"))
                    conn.execute(text("DROP TABLE IF EXISTS expenses;"))
                    conn.execute(text("DROP TABLE IF EXISTS participants;"))
                    conn.execute(text("DROP TABLE IF EXISTS trip_members;"))
                    conn.execute(text("DROP TABLE IF EXISTS trips;"))
                    conn.execute(text("DROP TABLE IF EXISTS users;"))
                    conn.commit()
                    Base.metadata.create_all(bind=engine)
                else:
                    # Check if description column exists in expenses
                    res_exp = conn.execute(text("PRAGMA table_info(expenses);")).fetchall()
                    exp_cols = [r[1] for r in res_exp]
                    if len(exp_cols) > 0 and "description" not in exp_cols:
                        conn.execute(text("ALTER TABLE expenses ADD COLUMN description VARCHAR(255) DEFAULT '';"))
                        conn.commit()
            except Exception as e:
                logger.warning(f"SQLite migration check notice: {e}")

    # Backfill any trips that lack a join_code or have an invalid one
    with SessionLocal() as db:
        try:
            trips = db.query(TripModel).all()
            updated = False
            for t in trips:
                if not t.join_code or not str(t.join_code).strip():
                    t.join_code = generate_join_code(db)
                    updated = True
            if updated:
                db.commit()
        except Exception as e:
            logger.warning(f"Passcode backfill notice: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# ------------------------------------------------------------------------------
# SECURITY, AUTHENTICATION & SESSIONS
# ------------------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "tripsplit-super-secret-production-key-9921")
session_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="tripsplit-auth-session")

def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def create_session_token(user_id: int) -> str:
    """Generate signed, tamper-proof session token."""
    return session_serializer.dumps({"uid": user_id})

def get_user_id_from_token(token: str) -> Optional[int]:
    """Verify and extract user_id from signed session token."""
    try:
        data = session_serializer.loads(token, max_age=30 * 86400)  # 30-day session
        return data.get("uid")
    except Exception:
        return None

def get_current_user_optional(request: Request, db: Session) -> Optional[UserModel]:
    """Retrieve logged-in user from session cookie if present."""
    token = request.cookies.get("tripsplit_session")
    if not token:
        return None
    user_id = get_user_id_from_token(token)
    if not user_id:
        return None
    return db.query(UserModel).filter(UserModel.id == user_id).first()

def get_current_user(request: Request, db: Session = Depends(get_db)) -> UserModel:
    """Enforce authentication dependency. Redirects unauthenticated requests to /login."""
    user = get_current_user_optional(request, db)
    if not user:
        if request.headers.get("hx-request"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"HX-Redirect": "/login"}
            )
        next_path = str(request.url.path)
        if request.url.query:
            next_path += f"?{request.url.query}"
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={urllib.parse.quote(next_path)}"}
        )
    return user

# 32 unambiguous characters (excludes 0, O, 1, I to prevent transcription errors)
PASSCODE_CHARSET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

def generate_join_code(db: Session) -> str:
    """Generate unique uppercase workspace access key, format TS-<5 ALPHANUMERIC CHARS> avoiding ambiguous characters (0, O, 1, I)."""
    for _ in range(100):
        suffix = "".join(secrets.choice(PASSCODE_CHARSET) for _ in range(5))
        code = f"TS-{suffix}"
        exists = db.query(TripModel).filter(TripModel.join_code == code).first()
        if not exists:
            return code
    suffix = "".join(secrets.choice(PASSCODE_CHARSET) for _ in range(6))
    return f"TS-{suffix}"


# ------------------------------------------------------------------------------
# CATEGORIES & COLOR PALETTE
# ------------------------------------------------------------------------------
DEFAULT_CATEGORIES = [
    "Food & Dining",
    "Accommodation",
    "Transport & Fuel",
    "Entertainment",
    "Shopping",
    "Utilities",
    "Groceries",
    "Miscellaneous",
]

CATEGORY_PALETTE = [
    {"bg": "bg-emerald-50 dark:bg-emerald-500/10", "bar": "bg-emerald-500", "text": "text-emerald-700 dark:text-emerald-400", "border": "border-emerald-200 dark:border-emerald-500/20"},
    {"bg": "bg-blue-50 dark:bg-blue-500/10", "bar": "bg-blue-500", "text": "text-blue-700 dark:text-blue-400", "border": "border-blue-200 dark:border-blue-500/20"},
    {"bg": "bg-purple-50 dark:bg-purple-500/10", "bar": "bg-purple-500", "text": "text-purple-700 dark:text-purple-400", "border": "border-purple-200 dark:border-purple-500/20"},
    {"bg": "bg-amber-50 dark:bg-amber-500/10", "bar": "bg-amber-500", "text": "text-amber-700 dark:text-amber-400", "border": "border-amber-200 dark:border-amber-500/20"},
    {"bg": "bg-pink-50 dark:bg-pink-500/10", "bar": "bg-pink-500", "text": "text-pink-700 dark:text-pink-400", "border": "border-pink-200 dark:border-pink-500/20"},
    {"bg": "bg-cyan-50 dark:bg-cyan-500/10", "bar": "bg-cyan-500", "text": "text-cyan-700 dark:text-cyan-400", "border": "border-cyan-200 dark:border-cyan-500/20"},
    {"bg": "bg-orange-50 dark:bg-orange-500/10", "bar": "bg-orange-500", "text": "text-orange-700 dark:text-orange-400", "border": "border-orange-200 dark:border-orange-500/20"},
    {"bg": "bg-rose-50 dark:bg-rose-500/10", "bar": "bg-rose-500", "text": "text-rose-700 dark:text-rose-400", "border": "border-rose-200 dark:border-rose-500/20"},
    {"bg": "bg-teal-50 dark:bg-teal-500/10", "bar": "bg-teal-500", "text": "text-teal-700 dark:text-teal-400", "border": "border-teal-200 dark:border-teal-500/20"},
    {"bg": "bg-indigo-50 dark:bg-indigo-500/10", "bar": "bg-indigo-500", "text": "text-indigo-700 dark:text-indigo-400", "border": "border-indigo-200 dark:border-indigo-500/20"},
    {"bg": "bg-lime-50 dark:bg-lime-500/10", "bar": "bg-lime-500", "text": "text-lime-700 dark:text-lime-400", "border": "border-lime-200 dark:border-lime-500/20"},
    {"bg": "bg-slate-50 dark:bg-slate-500/10", "bar": "bg-slate-500", "text": "text-slate-700 dark:text-slate-400", "border": "border-slate-200 dark:border-slate-500/20"},
]

CATEGORY_COLORS = {
    "Food & Dining": CATEGORY_PALETTE[0],
    "Accommodation": CATEGORY_PALETTE[1],
    "Transport & Fuel": CATEGORY_PALETTE[2],
    "Entertainment": CATEGORY_PALETTE[3],
    "Shopping": CATEGORY_PALETTE[4],
    "Utilities": CATEGORY_PALETTE[5],
    "Groceries": CATEGORY_PALETTE[8],
    "Miscellaneous": CATEGORY_PALETTE[11],
}

def get_category_color(category: str) -> Dict[str, str]:
    """Return styling classes for category, using deterministic hashing for custom categories."""
    if category in CATEGORY_COLORS:
        return CATEGORY_COLORS[category]
    idx = abs(hash(category)) % len(CATEGORY_PALETTE)
    return CATEGORY_PALETTE[idx]

def normalize_category_name(category: Optional[str], custom_category: Optional[str] = None) -> str:
    """Normalize category selection, supporting custom user inputs."""
    raw = (category or "").strip()
    if raw.lower() in ("custom", "custom...", "other"):
        if custom_category and custom_category.strip():
            return custom_category.strip().title()
        return "Miscellaneous"

    mapping = {
        "food": "Food & Dining",
        "food & dining": "Food & Dining",
        "dining": "Food & Dining",
        "lodging": "Accommodation",
        "accommodation": "Accommodation",
        "hotel": "Accommodation",
        "transit": "Transport & Fuel",
        "transport": "Transport & Fuel",
        "transport & fuel": "Transport & Fuel",
        "fuel": "Transport & Fuel",
        "activities": "Entertainment",
        "entertainment": "Entertainment",
        "shopping": "Shopping",
        "utilities": "Utilities",
        "utility": "Utilities",
        "groceries": "Groceries",
        "grocery": "Groceries",
        "misc": "Miscellaneous",
        "miscellaneous": "Miscellaneous",
    }
    normalized = mapping.get(raw.lower(), raw)
    return normalized if normalized else "Miscellaneous"

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
def get_user_trips(db: Session, user_id: int) -> List[TripModel]:
    """Return all trips where user is host or member."""
    return (
        db.query(TripModel)
        .join(TripMemberModel, TripMemberModel.trip_id == TripModel.id)
        .filter(TripMemberModel.user_id == user_id)
        .order_by(TripModel.id.desc())
        .all()
    )

def get_active_trip(request: Request, db: Session, current_user: Optional[UserModel], trip_id: Optional[int] = None) -> Optional[TripModel]:
    """Resolve active trip for current user, verifying access membership."""
    if not current_user:
        return None

    user_trips = get_user_trips(db, current_user.id)
    user_trip_ids = {t.id for t in user_trips}

    # 1. Explicit argument
    if trip_id and trip_id in user_trip_ids:
        return next(t for t in user_trips if t.id == trip_id)

    # 2. Query param
    param_id = request.query_params.get("trip_id")
    if param_id and param_id.isdigit() and int(param_id) in user_trip_ids:
        return next(t for t in user_trips if t.id == int(param_id))

    # 3. Cookie
    cookie_id = request.cookies.get("tripsplit_active_trip")
    if cookie_id and cookie_id.isdigit() and int(cookie_id) in user_trip_ids:
        return next(t for t in user_trips if t.id == int(cookie_id))

    # 4. Default to first trip
    return user_trips[0] if user_trips else None


def compute_financials(db: Session, active_trip: Optional[TripModel] = None, active_tab: str = "group", user_trips: Optional[List[TripModel]] = None) -> Dict[str, Any]:
    all_trips = user_trips if user_trips is not None else []

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
            "categories": DEFAULT_CATEGORIES,
            "default_categories": DEFAULT_CATEGORIES,
            "category_colors": CATEGORY_COLORS,
            "currencies": CURRENCIES,
            "currency_symbols": CURRENCY_SYMBOLS,
            "currency_rates": CURRENCY_RATES_TO_INR,
            "achievements": [],
            "health": compute_spending_health(0, 0, 0),
            "individual_profiles": {},
            "active_view": active_tab,
        }

    # Participants list (order by id)
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
            "color": get_category_color(em.category),
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

    cred_list = [[k, v] for k, v in creditors.items() if v > epsilon]
    deb_list = [[k, v] for k, v in debtors.items() if v > epsilon]

    transactions = []
    while cred_list and deb_list:
        cred_list.sort(key=lambda x: x[1], reverse=True)
        deb_list.sort(key=lambda x: x[1], reverse=True)

        c = cred_list[0]
        d = deb_list[0]
        transfer_amt = min(c[1], d[1])
        transfer_amt_rounded = round(transfer_amt, 2)

        if transfer_amt_rounded > 0:
            transactions.append({
                "from": d[0],
                "to": c[0],
                "amount": transfer_amt_rounded,
            })

        c[1] = round(c[1] - transfer_amt, 2)
        d[1] = round(d[1] - transfer_amt, 2)

        if c[1] < epsilon:
            cred_list.pop(0)
        if d[1] < epsilon:
            deb_list.pop(0)

    # Attach database settlement checkmark statuses
    settled_records = db.query(SettlementStatusModel).filter(
        SettlementStatusModel.trip_id == active_trip.id,
        SettlementStatusModel.is_settled == True
    ).all()
    settled_set = {(s.from_user, s.to_user): s.settled_at for s in settled_records}

    settled_count = 0
    settled_amount = 0.0
    for t in transactions:
        key = (t["from"], t["to"])
        if key in settled_set:
            t["is_settled"] = True
            t["settled_at"] = settled_set[key].strftime("%b %d, %H:%M") if settled_set[key] else "Paid"
            settled_count += 1
            settled_amount += t["amount"]
        else:
            t["is_settled"] = False
            t["settled_at"] = None

    # Transactions saved metric
    naive_edges = len(debtors) * len(creditors)
    if naive_edges < len(transactions):
        naive_edges = len(transactions)
    saved_transactions = max(0, naive_edges - len(transactions))
    saved_percent = round((saved_transactions / naive_edges * 100), 1) if naive_edges > 0 else 0.0

    # Peer-to-peer matrix
    matrix = {p: {other: 0.0 for other in participants} for p in participants}
    for t in transactions:
        if t["from"] in matrix and t["to"] in matrix[t["from"]]:
            matrix[t["from"]][t["to"]] = t["amount"]

    # Individual drill-down profiles
    individual_profiles = {}
    for p in participants:
        p_expenses = [e for e in expenses if e["payer"] == p]
        p_shared = [e for e in expenses if p in e["splitters"]]
        p_to_send = [t for t in transactions if t["from"] == p]
        p_to_receive = [t for t in transactions if t["to"] == p]
        p_bal = next((b for b in balances if b["participant"] == p), {"paid": 0.0, "owed": 0.0, "net": 0.0, "status": "settled"})

        individual_profiles[p] = {
            "name": p,
            "paid": p_bal["paid"],
            "owed": p_bal["owed"],
            "net": p_bal["net"],
            "status": p_bal["status"],
            "expenses_paid": p_expenses,
            "expenses_involved": p_shared,
            "transfers_to_send": p_to_send,
            "transfers_to_receive": p_to_receive,
        }

    # Dynamic categories (default + custom logged)
    seen_cats = set(DEFAULT_CATEGORIES)
    dynamic_categories = list(DEFAULT_CATEGORIES)
    for em in expenses_models:
        if em.category not in seen_cats:
            seen_cats.add(em.category)
            dynamic_categories.append(em.category)

    category_colors = {cat: get_category_color(cat) for cat in dynamic_categories}

    total_travelers = len(participants)
    avg_spend = round(total_spend / total_travelers, 2) if total_travelers > 0 else 0.0
    health = compute_spending_health(total_spend, total_travelers, len(expenses))
    achievements = compute_achievements(participants, expenses_models, balances)

    return {
        "all_trips": all_trips,
        "active_trip": active_trip,
        "participants": participants,
        "expenses": expenses,
        "balances": balances,
        "transactions": transactions,
        "matrix": matrix,
        "total_spend": round(total_spend, 2),
        "avg_spend": avg_spend,
        "total_expenses": len(expenses),
        "total_travelers": total_travelers,
        "naive_edges": naive_edges,
        "saved_transactions": saved_transactions,
        "saved_percent": saved_percent,
        "settled_count": settled_count,
        "settled_amount": round(settled_amount, 2),
        "category_spend": dict(category_spend),
        "categories": dynamic_categories,
        "default_categories": DEFAULT_CATEGORIES,
        "category_colors": category_colors,
        "currencies": CURRENCIES,
        "currency_symbols": CURRENCY_SYMBOLS,
        "currency_rates": CURRENCY_RATES_TO_INR,
        "achievements": achievements,
        "health": health,
        "individual_profiles": individual_profiles,
        "active_view": active_tab,
    }


def build_context(
    request: Request,
    db: Session,
    active_trip: Optional[TripModel] = None,
    active_tab: str = "group",
    current_user: Optional[UserModel] = None
) -> Dict[str, Any]:
    """Construct full rendering context with multi-tenant multiplayer state."""
    user_trips = get_user_trips(db, current_user.id) if current_user else []
    fin = compute_financials(db, active_trip, active_tab=active_tab, user_trips=user_trips)

    trip_members = []
    is_host = False
    join_code = ""
    invite_url = ""

    if active_trip:
        # Strictly ensure join_code is never None or empty
        if not active_trip.join_code or not str(active_trip.join_code).strip():
            active_trip.join_code = generate_join_code(db)
            db.commit()
            db.refresh(active_trip)

        trip_members = (
            db.query(TripMemberModel)
            .filter(TripMemberModel.trip_id == active_trip.id)
            .join(UserModel, UserModel.id == TripMemberModel.user_id)
            .order_by(TripMemberModel.id)
            .all()
        )
        is_host = (current_user is not None and active_trip.host_user_id == current_user.id)
        join_code = active_trip.join_code
        host = request.headers.get("host", "localhost:8000")
        proto = "https" if request.headers.get("x-forwarded-proto") == "https" else "http"
        invite_url = f"{proto}://{host}/join/{join_code}"

    has_api_key = bool(get_effective_api_key())

    ctx = {
        "request": request,
        "current_user": current_user,
        "is_host": is_host,
        "trip_members": trip_members,
        "join_code": join_code,
        "invite_url": invite_url,
        "has_api_key": has_api_key,
        "today_date": dt.date.today().isoformat(),
        **fin
    }
    return ctx


# ------------------------------------------------------------------------------
# FASTAPI APPLICATION SETUP & TEMPLATES
# ------------------------------------------------------------------------------
app = FastAPI(
    title="TripSplit AI",
    description="Collaborative Group Expense Tracker, Min-Cash-Flow Debt Simplification, & Receipt Parser",
    version="3.0.0",
    lifespan=lifespan
)

templates = Jinja2Templates(directory="templates")

# Custom HTTP exception handling for clean 303 redirects and HTMX client-side routing
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 303 and "Location" in exc.headers:
        return RedirectResponse(url=exc.headers["Location"], status_code=303)
    if exc.status_code == 401 and "HX-Redirect" in exc.headers:
        return Response(status_code=200, headers={"HX-Redirect": exc.headers["HX-Redirect"]})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


# ------------------------------------------------------------------------------
# AUTHENTICATION ENDPOINTS (LOGIN, REGISTER, LOGOUT)
# ------------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    join_code: Optional[str] = None,
    next: Optional[str] = None,
    db: Session = Depends(get_db)
):
    user = get_current_user_optional(request, db)
    target_code = join_code or request.cookies.get("pending_join_code")
    if user:
        if target_code:
            return RedirectResponse(url=f"/join/{target_code.upper()}", status_code=303)
        return RedirectResponse(url=next or "/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request, "join_code": target_code, "next_url": next, "error": None}
    )


@app.post("/login", response_class=HTMLResponse)
async def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    join_code: Optional[str] = Form(None),
    next_url: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    clean_email = email.strip().lower()
    user = db.query(UserModel).filter(UserModel.email == clean_email).first()
    target_code = join_code or request.cookies.get("pending_join_code")

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "request": request,
                "email": clean_email,
                "join_code": target_code,
                "next_url": next_url,
                "error": "Invalid email address or password. Please try again."
            },
            status_code=400
        )

    token = create_session_token(user.id)
    if target_code:
        resp = RedirectResponse(url=f"/join/{target_code.upper()}", status_code=303)
    elif next_url and next_url.startswith("/"):
        resp = RedirectResponse(url=next_url, status_code=303)
    else:
        resp = RedirectResponse(url="/", status_code=303)

    resp.set_cookie("tripsplit_session", token, max_age=30*86400, httponly=True, samesite="lax")
    return resp


@app.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    join_code: Optional[str] = None,
    next: Optional[str] = None,
    db: Session = Depends(get_db)
):
    user = get_current_user_optional(request, db)
    target_code = join_code or request.cookies.get("pending_join_code")
    if user:
        if target_code:
            return RedirectResponse(url=f"/join/{target_code.upper()}", status_code=303)
        return RedirectResponse(url=next or "/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"request": request, "join_code": target_code, "next_url": next, "error": None}
    )


@app.post("/register", response_class=HTMLResponse)
async def register_action(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    join_code: Optional[str] = Form(None),
    next_url: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    clean_name = full_name.strip()
    clean_email = email.strip().lower()
    target_code = join_code or request.cookies.get("pending_join_code")

    if not clean_name:
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"request": request, "full_name": clean_name, "email": clean_email, "join_code": target_code, "next_url": next_url, "error": "Full Name is required."},
            status_code=400
        )
    if len(password) < 6:
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"request": request, "full_name": clean_name, "email": clean_email, "join_code": target_code, "next_url": next_url, "error": "Password must be at least 6 characters long."},
            status_code=400
        )
    if password != confirm_password:
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"request": request, "full_name": clean_name, "email": clean_email, "join_code": target_code, "next_url": next_url, "error": "Passwords do not match."},
            status_code=400
        )

    existing = db.query(UserModel).filter(UserModel.email == clean_email).first()
    if existing:
        return templates.TemplateResponse(
            request=request, name="register.html",
            context={"request": request, "full_name": clean_name, "email": clean_email, "join_code": target_code, "next_url": next_url, "error": "An account with this email already exists. Please sign in."},
            status_code=400
        )

    hashed = hash_password(password)
    new_user = UserModel(
        email=clean_email,
        full_name=clean_name,
        hashed_password=hashed
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = create_session_token(new_user.id)
    if target_code:
        resp = RedirectResponse(url=f"/join/{target_code.upper()}", status_code=303)
    elif next_url and next_url.startswith("/"):
        resp = RedirectResponse(url=next_url, status_code=303)
    else:
        resp = RedirectResponse(url="/", status_code=303)

    resp.set_cookie("tripsplit_session", token, max_age=30*86400, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
@app.post("/logout")
async def logout_endpoint():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("tripsplit_session")
    resp.delete_cookie("tripsplit_active_trip")
    resp.delete_cookie("pending_join_code")
    return resp


# ------------------------------------------------------------------------------
# TRIP COLLABORATION WORKSPACE INVITE JOIN ENDPOINT
# ------------------------------------------------------------------------------
@app.get("/join/{join_code}")
async def join_trip_endpoint(
    request: Request,
    join_code: str,
    db: Session = Depends(get_db)
):
    clean_code = join_code.strip().upper()
    trip = db.query(TripModel).filter(TripModel.join_code == clean_code).first()
    if not trip:
        raise HTTPException(status_code=404, detail=f"No collaborative trip workspace found with access key '{clean_code}'.")

    current_user = get_current_user_optional(request, db)
    if not current_user:
        resp = RedirectResponse(url=f"/register?join_code={clean_code}", status_code=303)
        resp.set_cookie("pending_join_code", clean_code, max_age=3600, httponly=True)
        return resp

    # Add as TripMember if not already
    member = db.query(TripMemberModel).filter(
        TripMemberModel.trip_id == trip.id,
        TripMemberModel.user_id == current_user.id
    ).first()
    if not member:
        new_member = TripMemberModel(
            trip_id=trip.id,
            user_id=current_user.id,
            role="member"
        )
        db.add(new_member)
        db.commit()

    # Ensure user is recorded in ParticipantModel
    p = db.query(ParticipantModel).filter(
        ParticipantModel.trip_id == trip.id,
        ParticipantModel.name == current_user.full_name
    ).first()
    if not p:
        db.add(ParticipantModel(trip_id=trip.id, name=current_user.full_name))
        db.commit()

    resp = RedirectResponse(url=f"/?trip_id={trip.id}", status_code=303)
    resp.set_cookie("tripsplit_active_trip", str(trip.id), max_age=30*86400)
    resp.delete_cookie("pending_join_code")
    return resp


# ------------------------------------------------------------------------------
# CORE WEB UI ROUTES
# ------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index_endpoint(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user_optional(request, db)
    if not current_user:
        pending_code = request.query_params.get("join_code") or request.cookies.get("pending_join_code")
        if pending_code:
            return RedirectResponse(url=f"/register?join_code={pending_code.upper()}", status_code=303)
        return RedirectResponse(url="/login", status_code=303)

    active_trip = get_active_trip(request, db, current_user)
    ctx = build_context(request, db, active_trip, current_user=current_user)
    resp = templates.TemplateResponse(request=request, name="index.html", context=ctx)
    if active_trip:
        resp.set_cookie("tripsplit_active_trip", str(active_trip.id), max_age=30*86400)
    return resp


@app.get("/api/dashboard", response_class=HTMLResponse)
async def dashboard_endpoint(
    request: Request,
    tab: str = "group",
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    active_trip = get_active_trip(request, db, current_user)
    ctx = build_context(request, db, active_trip, active_tab=tab, current_user=current_user)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


# ------------------------------------------------------------------------------
# TRIP MANAGEMENT (MULTI-TRIP SCOPED TO MEMBERS)
# ------------------------------------------------------------------------------
@app.post("/api/trips", response_class=HTMLResponse)
async def create_trip_endpoint(
    request: Request,
    name: str = Form(...),
    currency: str = Form("INR"),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    clean_name = name.strip()
    if not clean_name:
        clean_name = "Untitled Trip"

    code = generate_join_code(db)
    trip = TripModel(
        name=clean_name,
        host_user_id=current_user.id,
        join_code=code,
        base_currency=currency.upper() if currency.upper() in CURRENCIES else "INR"
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)

    # Host is enrolled as Host
    member = TripMemberModel(
        trip_id=trip.id,
        user_id=current_user.id,
        role="host"
    )
    db.add(member)

    # Host is added as initial participant
    participant = ParticipantModel(
        trip_id=trip.id,
        name=current_user.full_name
    )
    db.add(participant)
    db.commit()

    ctx = build_context(request, db, trip, current_user=current_user)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    resp.set_cookie("tripsplit_active_trip", str(trip.id), max_age=30*86400)
    return resp


@app.post("/api/trips/select", response_class=HTMLResponse)
async def select_trip_endpoint(
    request: Request,
    trip_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    user_trips = get_user_trips(db, current_user.id)
    trip = next((t for t in user_trips if t.id == trip_id), None)
    if not trip:
        raise HTTPException(status_code=403, detail="You do not have access to this trip")

    ctx = build_context(request, db, trip, current_user=current_user)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    resp.set_cookie("tripsplit_active_trip", str(trip.id), max_age=30*86400)
    return resp


@app.post("/api/trips/{trip_id}/delete", response_class=HTMLResponse)
async def delete_trip_endpoint(
    request: Request,
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    # STRICT PERMISSION: Only the Host can delete the trip
    if trip.host_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the Trip Host (👑) can delete this trip.")

    db.delete(trip)
    db.commit()

    remaining_trips = get_user_trips(db, current_user.id)
    next_active = remaining_trips[0] if remaining_trips else None

    ctx = build_context(request, db, next_active, current_user=current_user)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    if next_active:
        resp.set_cookie("tripsplit_active_trip", str(next_active.id), max_age=30*86400)
    else:
        resp.delete_cookie("tripsplit_active_trip")
    return resp


@app.post("/api/reset", response_class=HTMLResponse)
async def reset_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """Wipes active trip data or all trips owned by user, returning to zero-state."""
    user_trips = db.query(TripModel).filter(TripModel.host_user_id == current_user.id).all()
    for t in user_trips:
        db.delete(t)
    db.commit()

    ctx = build_context(request, db, None, current_user=current_user)
    resp = templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)
    resp.delete_cookie("tripsplit_active_trip")
    return resp


@app.post("/api/key", response_class=HTMLResponse)
async def set_api_key(
    request: Request,
    api_key: str = Form(""),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    global GLOBAL_API_KEY_OVERRIDE
    GLOBAL_API_KEY_OVERRIDE = api_key.strip()
    active_trip = get_active_trip(request, db, current_user)
    ctx = build_context(request, db, active_trip, current_user=current_user)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


# ------------------------------------------------------------------------------
# PARTICIPANTS & EXPENSES ENDPOINTS (COLLABORATIVE)
# ------------------------------------------------------------------------------
@app.post("/api/participants", response_class=HTMLResponse)
async def add_participant_endpoint(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    active_trip = get_active_trip(request, db, current_user)
    if not active_trip:
        raise HTTPException(status_code=400, detail="No active trip selected")

    clean_name = name.strip()
    if clean_name:
        existing = db.query(ParticipantModel).filter(
            ParticipantModel.trip_id == active_trip.id,
            ParticipantModel.name == clean_name
        ).first()
        if not existing:
            new_p = ParticipantModel(trip_id=active_trip.id, name=clean_name)
            db.add(new_p)
            db.commit()

    ctx = build_context(request, db, active_trip, current_user=current_user)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


@app.post("/api/participants/{name}/delete", response_class=HTMLResponse)
async def delete_participant_endpoint(
    request: Request,
    name: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    active_trip = get_active_trip(request, db, current_user)
    if not active_trip:
        raise HTTPException(status_code=400, detail="No active trip selected")

    p = db.query(ParticipantModel).filter(
        ParticipantModel.trip_id == active_trip.id,
        ParticipantModel.name == name
    ).first()
    if p:
        db.delete(p)
        db.commit()

    ctx = build_context(request, db, active_trip, current_user=current_user)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


@app.post("/api/expenses", response_class=HTMLResponse)
async def add_expense_endpoint(
    request: Request,
    description: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("INR"),
    category: str = Form("Miscellaneous"),
    custom_category: Optional[str] = Form(None),
    date: str = Form(...),
    payer: str = Form(...),
    splitters: List[str] = Form(...),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    active_trip = get_active_trip(request, db, current_user)
    if not active_trip:
        raise HTTPException(status_code=400, detail="No active trip selected")

    clean_curr = currency.upper() if currency.upper() in CURRENCIES else "INR"
    clean_amt = max(float(amount), 0.01)
    normalized_inr = normalize_to_inr(clean_amt, clean_curr)
    resolved_category = normalize_category_name(category, custom_category)

    expense = ExpenseModel(
        trip_id=active_trip.id,
        created_by_user_id=current_user.id,
        payer_name=payer.strip(),
        amount=normalized_inr,
        original_amount=clean_amt,
        currency=clean_curr,
        category=resolved_category,
        description=description.strip(),
        beneficiaries_json=json.dumps(splitters),
        date=date.strip(),
    )
    db.add(expense)
    db.commit()

    ctx = build_context(request, db, active_trip, current_user=current_user)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


@app.post("/api/expenses/{expense_id}/delete", response_class=HTMLResponse)
async def delete_expense_endpoint(
    request: Request,
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    active_trip = get_active_trip(request, db, current_user)
    if not active_trip:
        raise HTTPException(status_code=400, detail="No active trip selected")

    e = db.query(ExpenseModel).filter(
        ExpenseModel.id == expense_id,
        ExpenseModel.trip_id == active_trip.id
    ).first()
    if e:
        db.delete(e)
        db.commit()

    ctx = build_context(request, db, active_trip, current_user=current_user)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


@app.post("/api/settlements/toggle", response_class=HTMLResponse)
async def toggle_settlement_endpoint(
    request: Request,
    from_name: str = Form(...),
    to_name: str = Form(...),
    amount: float = Form(0.0),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    active_trip = get_active_trip(request, db, current_user)
    if not active_trip:
        raise HTTPException(status_code=400, detail="No active trip selected")

    settlement = db.query(SettlementStatusModel).filter(
        SettlementStatusModel.trip_id == active_trip.id,
        SettlementStatusModel.from_user == from_name,
        SettlementStatusModel.to_user == to_name,
    ).first()

    if not settlement:
        settlement = SettlementStatusModel(
            trip_id=active_trip.id,
            from_user=from_name,
            to_user=to_name,
            amount=amount,
            is_settled=True,
            settled_at=dt.datetime.utcnow(),
        )
        db.add(settlement)
    else:
        settlement.is_settled = not settlement.is_settled
        settlement.settled_at = dt.datetime.utcnow() if settlement.is_settled else None

    db.commit()

    ctx = build_context(request, db, active_trip, current_user=current_user)
    return templates.TemplateResponse(request=request, name="partials/dashboard.html", context=ctx)


# ------------------------------------------------------------------------------
# MULTIMODAL RECEIPT SCANNING (GEMINI VISION)
# ------------------------------------------------------------------------------
RECEIPT_PROMPT = """
You are a precision FinTech receipt and invoice parser. Analyze this receipt image and return ONLY a valid JSON object:
{
  "merchant": "Business or Store Name",
  "total_amount": 0.00,
  "currency": "INR",
  "category": "Food & Dining",
  "date": "YYYY-MM-DD",
  "description": "Brief summary of purchased items"
}
Categories must be one of: Food & Dining, Accommodation, Transport & Fuel, Entertainment, Shopping, Utilities, Groceries, Miscellaneous.
Currencies must be one of: INR, USD, EUR, GBP. Default to INR if ₹ or Rs is seen.
"""

@app.post("/api/expenses/scan-receipt", response_class=HTMLResponse)
@app.post("/api/scan-receipt", response_class=HTMLResponse)
async def scan_receipt_endpoint(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    active_trip = get_active_trip(request, db, current_user)
    ctx = build_context(request, db, active_trip, current_user=current_user)

    api_key = get_effective_api_key()
    if not api_key:
        return HTMLResponse(
            '<div class="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-600 dark:text-amber-400">'
            '⚠️ Gemini API key is missing. Set <code>GOOGLE_API_KEY</code> environment variable or provide an override in the sidebar.'
            '</div>'
        )

    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))

        response_text = ""
        if NEW_GENAI_AVAILABLE:
            client = new_genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[image, RECEIPT_PROMPT]
            )
            response_text = resp.text
        elif LEGACY_GENAI_AVAILABLE:
            genai_legacy.configure(api_key=api_key)
            model = genai_legacy.GenerativeModel('gemini-1.5-flash')
            resp = model.generate_content([image, RECEIPT_PROMPT])
            response_text = resp.text

        clean_json = response_text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_json)

        receipt_ctx = {
            "request": request,
            "merchant": data.get("merchant", "Receipt Item"),
            "amount": float(data.get("total_amount", 0.0)),
            "currency": data.get("currency", "INR"),
            "category": normalize_category_name(data.get("category", "Miscellaneous")),
            "date": data.get("date", dt.date.today().isoformat()),
            "description": data.get("description", "Scanned Receipt Expense"),
            "participants": ctx["participants"],
            "categories": ctx["categories"],
            "currencies": CURRENCIES,
            "currency_symbols": CURRENCY_SYMBOLS,
            "currency_rates": CURRENCY_RATES_TO_INR,
        }
        return templates.TemplateResponse(request=request, name="partials/receipt_review.html", context=receipt_ctx)

    except Exception as e:
        logger.error(f"Receipt parsing error: {e}")
        return HTMLResponse(
            f'<div class="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-xs text-rose-600 dark:text-rose-400">'
            f'❌ Receipt scan failed: {str(e)}'
            f'</div>'
        )


@app.post("/api/expenses/confirm-receipt", response_class=HTMLResponse)
@app.post("/api/confirm-receipt", response_class=HTMLResponse)
async def confirm_receipt_endpoint(
    request: Request,
    description: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("INR"),
    category: str = Form("Miscellaneous"),
    custom_category: Optional[str] = Form(None),
    date: str = Form(...),
    payer: str = Form(...),
    splitters: List[str] = Form(...),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    return await add_expense_endpoint(
        request=request,
        description=description,
        amount=amount,
        currency=currency,
        category=category,
        custom_category=custom_category,
        date=date,
        payer=payer,
        splitters=splitters,
        db=db,
        current_user=current_user
    )


# ------------------------------------------------------------------------------
# UNIVERSAL CURRENCY CONVERTER ENDPOINTS
# ------------------------------------------------------------------------------
@app.get("/api/fx/rates")
async def get_fx_rates():
    return {
        "base": "INR",
        "rates": CURRENCY_RATES_TO_INR,
        "symbols": CURRENCY_SYMBOLS
    }


@app.get("/api/fx/convert")
async def convert_currency(amount: float = 1.0, from_curr: str = "USD", to_curr: str = "INR"):
    clean_from = from_curr.upper() if from_curr.upper() in CURRENCIES else "USD"
    clean_to = to_curr.upper() if to_curr.upper() in CURRENCIES else "INR"

    rate_to_inr = CURRENCY_RATES_TO_INR.get(clean_from, 1.0)
    amt_inr = float(amount) * rate_to_inr
    rate_from_inr = 1.0 / CURRENCY_RATES_TO_INR.get(clean_to, 1.0)
    final_amt = amt_inr * rate_from_inr

    return {
        "from_currency": clean_from,
        "to_currency": clean_to,
        "original_amount": round(float(amount), 2),
        "converted_amount": round(final_amt, 2),
        "rate": round(rate_to_inr * rate_from_inr, 4),
        "symbol": CURRENCY_SYMBOLS.get(clean_to, "₹")
    }


# ------------------------------------------------------------------------------
# CSV EXPORT ROUTES (TRIP-SCOPED)
# ------------------------------------------------------------------------------
@app.get("/api/export/settlement")
async def export_settlement_csv(
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    active_trip = get_active_trip(request, db, current_user)
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
async def export_ledger_csv(
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    active_trip = get_active_trip(request, db, current_user)
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


@app.get("/api/export/csv")
async def export_csv_alias(
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """Convenience alias for ledger CSV export."""
    return await export_ledger_csv(request, db, current_user)
