# ✈️ TripSplit AI — Smart Group Expense Tracker & FinTech Cash-Flow Optimizer

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![HTMX](https://img.shields.io/badge/HTMX-1.9.10-336699.svg?style=flat&logo=htmx&logoColor=white)](https://htmx.org)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-38B2AC.svg?style=flat&logo=tailwind-css&logoColor=white)](https://tailwindcss.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-D71F00.svg?style=flat&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue.svg?style=flat&logo=python&logoColor=white)](https://python.org)
[![Google Gemini](https://img.shields.io/badge/Google%20Gemini-Flash%20Vision-4285F4.svg?style=flat&logo=google&logoColor=white)](https://ai.google.dev)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?style=flat&logo=docker&logoColor=white)](https://docker.com)

**TripSplit AI** is a production-ready, dynamic FinTech web application designed for group expense tracking, multimodal AI receipt scanning, and cash-flow debt simplification. Built with a modern **Hypermedia-Driven Architecture (HDA)** using **FastAPI**, **HTMX**, and **Tailwind CSS**, TripSplit AI delivers smooth real-time updates without the overhead or latency of heavy client-side JavaScript single-page application (SPA) frameworks.

---

## 🌟 Key Features

### 🔐 User Authentication & Session Security
- User registration and login powered by bcrypt password hashing and tamper-proof signed session cookies (`itsdangerous`).
- Dynamic Dark/Light mode on authentication screens with immediate theme persistence.
- Protected application routes redirecting unauthenticated users cleanly to `/login`.

### 👥 Trip Collaboration Workspace & Shareable Access Keys
- **Secure Workspace Access Keys**: Every trip generates a clean, memorable uppercase access key (e.g. `TS-8K4WP`, `TS-92MFX`), avoiding ambiguous characters (`0`, `O`, `1`, `I`) to prevent entry mistakes.
- **Shareable Join URLs**: Team members join instantly via `/join/{join_code}` links. Unauthenticated visitors are guided through quick registration with their workspace access key preserved.
- **Active Collaborators Card**: Real-time member cards showing collaborator avatars, online status, and role badges (`👑 Host` vs `💼 Member`).
- **One-Click Share Modal**: Enterprise workspace invite popup featuring the access key, direct URL with current origin, one-click copy, and animated toast confirmation.
- **Role-Based Permissions**: All members can collaboratively log expenses, scan receipts, and settle debts; trip deletion is strictly reserved for the Trip Host (returns 403 Forbidden for non-hosts).

### ☁️ Cloud Database Support (PostgreSQL / Supabase)
- Dual-engine persistence configured through `DATABASE_URL` environment variable.
- Seamless compatibility with **Supabase**, **Neon**, **PostgreSQL**, and zero-config local **SQLite** (`sqlite:///./tripsplit.db`).

### 🗂️ Multi-Trip Management
- Create, switch between, and manage multiple trips (e.g., *"Goa Roadtrip"*, *"Euro Summer 2026"*).
- Every trip features a completely isolated ledger, participant list, settlements, and category analytics.
- Easily delete trips with cascade database cleanup (Host only).

### 🧹 Clean Zero-State Guarantee
- Boots up in a pristine empty state with 0 trips, 0 participants, and 0 expenses.
- No hardcoded demo data, mock travelers, or dummy buttons.
- Clean onboarding prompt welcomes users to create their first trip.

### 🧠 Algorithmic Debt Simplification (Min-Cash-Flow)
- Solves the $N$-person debt explosion problem using a greedy graph optimization algorithm.
- Reduces raw pairwise debt edges from $\mathcal{O}(N^2)$ down to at most $N - 1$ direct transfers.
- Real-time **"Transactions Saved %"** metric shows immediate efficiency gains (typically 50%–85% fewer transfers).

### ✅ Interactive Payment Settlement Tracking
- Track real-world repayments with interactive **"Mark as Settled"** toggles.
- Settled transfers are visually marked with strikethroughs and green settlement badges.
- Settlement states persist in the SQLite database across restarts.

### 💱 Universal Currency Converter
- Support for **Indian Rupee (₹)**, **US Dollar ($)**, **Euro (€)**, and **British Pound (£)**.
- Automatically normalizes all foreign currency expenses into **INR (₹)** for consistent group settlement.
- Real-time exchange rates via public API with robust offline fallback ratios ($1\text{ USD} = 83.50\text{ INR}$, etc.).

### 🏷️ Granular & Custom Expense Categories
- **8 Granular Defaults**: *Food & Dining*, *Accommodation*, *Transport & Fuel*, *Entertainment*, *Shopping*, *Utilities*, *Groceries*, *Miscellaneous*.
- **Dynamic "➕ Custom..." Option**: Select custom category to reveal a dynamic input field to type any custom category name (e.g., *"Scuba Diving"*, *"Ski Pass"*, *"Visa Fees"*).
- Custom categories automatically receive deterministic color palettes and are integrated into the spending breakdown chart and expense ledger.

### 📸 AI-Powered Multimodal Receipt Scanner
- Powered by **Google Gemini Flash** vision models via the `google-generativeai` SDK.
- Upload receipt photos or invoices (JPEG, PNG, WEBP).
- Automatically parses merchant names, total amounts, dates, and automatically categorizes expenses with high confidence.
- Interactive review dialog allows editing parsed data before committing to the ledger.

### 🏆 Gamified Traveler Badges & Spend Health Meter
- **Group Spend Velocity**: Visual health bar showing burn rate and budget tips.
- **Dynamic Badges**:
  - 👑 **Big Spender**: Traveler who paid the most overall.
  - 🛡️ **Budget Boss**: Cautious traveler with the lowest spend.
  - ⚡ **Frequent Swiper**: Traveler with the highest number of transactions.
  - ⚖️ **Fair & Square**: Traveler closest to a zero net balance.

### 🌗 Light / Dark Mode Toggle
- Beautiful Tailwind CSS dark/light theme with persistent `localStorage` preference.
- Supports smooth color transitions across all cards, modals, and tables.

### 📥 One-Click CSV Export
- Download complete expense ledgers formatted for Microsoft Excel, Google Sheets, or tax records.

---

## 🏗️ Architecture & Tech Stack

```
TripSplit AI
├── Backend:       FastAPI (Python async ASGI framework)
├── Persistence:   SQLAlchemy ORM + SQLite (tripsplit.db)
├── Frontend:      HTMX 1.9 + Tailwind CSS + Jinja2 Templates
├── AI Vision:     Google Gemini Flash (google-generativeai)
├── Container:     Docker + Docker Compose + Uvicorn
└── Hosting:       Deployable on Render, Railway, Fly.io, or VPS
```

For detailed mathematical proofs of the greedy debt simplification algorithm, graph invariants, and API routes, see [docs/architecture_and_math.md](docs/architecture_and_math.md).

---

## 📁 Project Structure

```
TripSplit_AI/
├── docs/
│   └── architecture_and_math.md # Mathematical proofs, graph theory, & API docs
├── templates/
│   ├── index.html               # Main application shell & global modals
│   └── partials/
│       ├── dashboard.html       # Dynamic HTMX trip dashboard fragment
│       └── receipt_review.html  # AI receipt confirmation fragment
├── Dockerfile                   # Multi-stage container build
├── docker-compose.yml           # Docker Compose orchestrator
├── main.py                      # FastAPI application, models, routes & algorithms
├── render.yaml                  # Cloud deployment specification
├── requirements.txt             # Python dependencies
├── tripsplit.db                 # SQLite database (auto-generated on first boot)
└── README.md                    # Project documentation
```

---

## 🚀 Quick Start & Installation

### Prerequisites
- **Python 3.10+** (tested up to Python 3.14)
- **Git**
- *(Optional)* **Google Gemini API Key** for AI receipt parsing ([Get API key](https://aistudio.google.com/))

---

### Method 1: Local Setup (Recommended)

1. **Clone or Navigate to the Repository**:
   ```bash
   cd c:\Users\avant\Downloads\TripSplit_AI
   ```

2. **Create and Activate a Virtual Environment**:
   ```bash
   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables (Optional)**:
   Create a `.env` file or export your Gemini API key:
   ```bash
   # Windows (PowerShell)
   $env:GEMINI_API_KEY="your-gemini-api-key"

   # Linux / macOS
   export GEMINI_API_KEY="your-gemini-api-key"
   ```
   > **Note:** If no API key is set, manual expense entry and all financial algorithms remain fully functional. AI receipt uploads will prompt for an API key.

5. **Run the Application**:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

6. **Open in Browser**:
   Visit [http://localhost:8000](http://localhost:8000) in your web browser.

---

### Method 2: Docker & Docker Compose

1. **Build and Run with Docker Compose**:
   ```bash
   docker-compose up --build
   ```

2. **Or Build and Run with Docker directly**:
   ```bash
   docker build -t tripsplit-ai .
   docker run -p 8000:8000 -e GEMINI_API_KEY="your-api-key" tripsplit-ai
   ```

3. Open [http://localhost:8000](http://localhost:8000).

---

## 🧮 Debt Simplification Algorithm Summary

In a group with participants $V$:
1. For each participant $v \in V$, calculate:
   $$\text{Net}(v) = \sum \text{Paid}(v) - \sum \text{Fair Share Owed}(v)$$
2. Partition into **Debtors** ($\text{Net} < 0$) and **Creditors** ($\text{Net} > 0$).
3. Iteratively pair the debtor with the largest debt against the creditor with the largest credit:
   $$\text{Transfer} = \min(|\text{Debtor Balance}|, \text{Creditor Balance})$$
4. At each step, at least one participant is eliminated, terminating in at most $N - 1$ transfers.

Read the complete technical breakdown and proofs in [docs/architecture_and_math.md](docs/architecture_and_math.md).

---

## 🌐 API Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web application shell (requires authentication) |
| `GET` | `/login` | Modern login screen with theme switcher |
| `POST` | `/login` | Form authentication & session establishment |
| `GET` | `/register` | User onboarding & account creation |
| `POST` | `/register` | Secure registration via bcrypt |
| `GET` | `/logout` | Terminate session & clear cookies |
| `GET` | `/join/{join_code}` | Collaborative workspace invite link |
| `GET` | `/api/dashboard` | Dynamic trip dashboard (HTMX) |
| `POST` | `/api/trips` | Create a new trip with unique workspace access key |
| `POST` | `/api/trips/select` | Switch active trip |
| `POST` | `/api/trips/{id}/delete` | Delete trip & cascade records (Host only, 403 for members) |
| `POST` | `/api/participants` | Add traveler to trip |
| `POST` | `/api/participants/{name}/delete` | Remove traveler |
| `POST` | `/api/expenses` | Add expense (supports custom category & multi-currency) |
| `POST` | `/api/expenses/scan-receipt` | Gemini vision AI receipt scanning |
| `POST` | `/api/expenses/confirm-receipt` | Commit scanned receipt |
| `POST` | `/api/expenses/{id}/delete` | Delete expense |
| `POST` | `/api/settlements/toggle` | Mark debt transfer as paid/settled |
| `GET` | `/api/export/csv` | Download CSV expense report |
| `GET` | `/api/fx/rates` | Current exchange rates (JSON) |

---

## 🧪 Automated Testing

TripSplit AI includes full automated integration and collaborative workspace end-to-end test suites:

```bash
# Run collaborative workspace & authentication E2E tests (9 phases)
python test_collab_e2e.py

# Run financials, custom categories, zero-state & export E2E tests (10 phases)
python test_e2e.py
```

Both test suites execute against the live FastAPI server and verify 100% of workflows without manual intervention.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License — feel free to use, modify, and distribute for personal or commercial projects.
