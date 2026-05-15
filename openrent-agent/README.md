# OpenRent Agent

An AI-powered automation bot that replicates manual rental property workflows on the [OpenRent](https://www.openrent.co.uk) platform. It searches listings, manages landlord conversations, and generates AI-driven replies — all driven by a Python backend with Playwright browser automation.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask, SQLAlchemy |
| Browser automation | Playwright (headless) |
| Database | PostgreSQL (async via asyncpg) |
| AI replies | OpenAI API |
| Config | python-dotenv |

## Project Structure

```
openrent-agent/
├── app/
│   ├── ai/              # AI reply generation
│   ├── browser/         # Playwright launcher, auth, selectors
│   ├── db/              # SQLAlchemy models, repository, connection
│   ├── extraction/      # Data extractors (structured data, phone numbers)
│   └── openrent/        # Platform interactions (search, inbox, messaging, listings)
├── scripts/
│   ├── process_listings.py   # Crawl and store search results
│   ├── process_replies.py    # Auto-reply to landlord messages
│   ├── run_workers.py        # Background task runner
│   ├── run_dashboard.py      # Dashboard server
│   └── seed_data.py          # Populate test data
├── tests/
└── frontend/            # React scaffold (not yet developed)
```

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL
- Node.js (for frontend, when ready)

### Install

```bash
cd openrent-agent
pip install -r requirements.txt
playwright install chromium
```

### Environment

Create a `.env` file:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost/openrent
OPENAI_API_KEY=sk-...
OPENRENT_EMAIL=your@email.com
OPENRENT_PASSWORD=yourpassword
PROXY_URL=                  # optional
HEADLESS=true
```

### Database

```bash
python -m app.db.init_db
```

## Usage

**Search for listings:**
```bash
python scripts/process_listings.py
```

**Process and auto-reply to inbox messages:**
```bash
python scripts/process_replies.py
```

**Run background workers:**
```bash
python scripts/run_workers.py
```

**Seed test data:**
```bash
python scripts/seed_data.py
```

## Core Modules

- **`app/browser/`** — Initialises Playwright, handles login, CSS selectors
- **`app/openrent/`** — Search queries, inbox navigation, messaging, listing scraping, landlord extraction, popup handling
- **`app/db/`** — ORM models (`Property`, `Conversation`, `Job`), async CRUD repository
- **`app/ai/`** — Incoming message processing and OpenAI-backed reply generation
- **`app/extraction/`** — Structured data extraction from conversations; phone number parsing


