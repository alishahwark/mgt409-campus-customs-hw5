# Campus Customs — MGT 409 Homework 5

Campus Customs is a local operations desk for a campus apparel shop. A Boss
agent coordinates Inventory, Accounting, Facilities, and Customer Service
agents. The team reads shop facts through FastMCP, exposes the workflow through
FastAPI, and presents tickets, activity, approvals, and cash in a React/Vite
dashboard backed by SQLite.

## Stack and prerequisites

- Python 3.12 (the submitted environment was built with Python 3.12)
- Node.js 20 or newer and npm
- FastAPI, Uvicorn, FastMCP, MCP stdio transport, and PydanticAI
- React, Vite, TypeScript, and SQLite 3

All agents use only `gpt-6-luna` through Portkey. No API key is stored here.

## Installation

From this `hw5/` directory:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set a local `PORTKEY_API_KEY`. Keep `.env` private; it is
excluded by `.gitignore`.

Install the dashboard dependencies:

```bash
cd frontend
npm install
cd ..
```

## Run the application

Start FastAPI from `hw5/`:

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

The backend is available at <http://localhost:8000>. In a second terminal,
start the dashboard:

```bash
cd frontend
npm run dev -- --host localhost --port 5173
```

The dashboard is available at <http://localhost:5173>.

The backend launches the local FastMCP server over stdio using `.mcp.json` and
the relative `.venv/bin/python` path. To initialize the MCP server directly:

```bash
.venv/bin/python mcp_server/server.py
```

The MCP server and backend use `data/campus_customs_new.db`. The original
`data/campus_customs.db` is never modified.

## Dashboard workflow

Use **+ New Ticket** to enter a required subject and description. The ticket is
created as Open with a SQLite-assigned ID and is not run automatically. Select
an Open ticket and choose **Run Ticket** to start the bounded Boss-led team.
The dashboard displays MCP calls, delegations, findings, and outcomes.

Payments and purchases always stop for explicit human approval. The approval
dialog rechecks the obligation, existing payments, and checking cash before an
approved payment can execute. It prevents duplicate payments, negative cash,
unverified invoice/lease links, and vendor restrictions. Customer messages are
drafts only; no customer or vendor is contacted automatically.

## Clean copy, reset, and reproducing the assignment run

To prepare a clean working copy before a new full run, stop the backend and any
MCP client, then run:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

Alternatively, use **Reset Shop** or the API only after explicit confirmation.
Reset restores the working copy from the original and preserves append-only
audit history. Do not reset the completed submission unless a clean run is
intended.

For the completed three-ticket workflow:

1. Start from a clean copy and confirm Tickets 101, 102, and 103 are Open.
2. Start the backend and dashboard.
3. Run Ticket 101. If invoice 501 is proposed, verify it and approve exactly one `$840.00` payment as a human.
4. Run Ticket 101 again if follow-up evidence is required.
5. Run Ticket 102. Verify lease 1 and `desk.date_today`, then approve exactly one `$2,400.00` rent payment if unpaid.
6. Run Ticket 103 and review verified stock, pricing, margin, and the unsent draft.
7. Confirm final balances and statuses through the dashboard and MCP.

Never approve an agent request automatically, invent stock or supplier data, or
represent an unsent draft as a sent message or fulfilled order.

## Validation and outputs

From `hw5/`:

```bash
.venv/bin/python -m unittest discover -s tests
cd frontend
npm run build
npm run test:smoke
```

The submission artifacts are in `output/`: `harness.md`, `mcp_smoke.json`,
`desk_tickets.html`, `resolved_tickets.json`, `resolved_board.html`,
`audit_trail.json`, `design.md`, and `github_url.txt`. Prompts are preserved
in `AI_prompts.md`.
