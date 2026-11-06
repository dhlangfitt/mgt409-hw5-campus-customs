# Campus Customs Multi-Agent Operations

**Campus Customs** is a small campus shop that sells custom apparel and gifts (tees,
hoodies, caps, mugs). Its open-ticket board collects everything that needs attention:
customer orders, rent notices, unpaid vendor bills and discount requests.

This project puts a **team of five AI agents** in charge of that board. A human
watches the team in a dashboard and approves anything that costs money.

It has three parts that talk to each other:

| Part | Folder | What it does |
| --- | --- | --- |
| **MCP server** | `mcp_server/` | The only way anything reads or changes the shop database. It has 17 tools in two modes. **Agent mode** (13 tools) reads data and *prepares* payment requests, purchase requests, message drafts and ticket notes. **Approver mode** (4 more tools) can execute payments and record human decisions, and is never given to an agent. |
| **Backend** (FastAPI and PydanticAI) | `backend/` | Runs the agent team (Boss, Inventory, Accounting, Facilities, Customer Service) on `gpt-6-luna` through Portkey. It is the dashboard's only interface: tickets, agent runs, activity, approvals, cash and database reset. |
| **Dashboard** (React, Vite, TypeScript) | `frontend/` | The operations desk. It shows the ticket rail, the live activity of the agents, the checking balance, and signature slips for approving or rejecting payments. |

```text
React dashboard ──HTTP──► FastAPI backend ──► agent team (PydanticAI, gpt-6-luna via Portkey)
   :5173                    :8000                 │
                              │                    └─ MCP server, agent mode ─┐
                              └─ MCP server, approver mode (human decisions) ─┴─► data/campus_customs_new.db
```

**The rules the system enforces:**

- "Today" is the shop's date in the database (`desk.date_today`), not the real
  calendar.
- Vendors won't ship while they have an unpaid invoice.
- Every payment needs a named human's approval, and a payment that would take
  checking below zero is refused.
- Only money going out is modelled.
- Customer, vendor and landlord messages are drafts only. Nothing is ever sent.

---

## 1. What you need

- **Python 3.11 or newer.** Tested with 3.14.
- **Node.js 20 or newer, with npm.** Tested with Node 24.
- **A Portkey API key** that can call the model `gpt-6-luna`. You need it only to run
  the agents. Everything else (the MCP server, the API, the dashboard, approvals and
  reset) works without it.
- macOS or Linux shell commands are shown. Windows notes are in
  [Troubleshooting](#7-troubleshooting).

## 2. Install (once, from a fresh clone)

Run these from the repository root (the folder this README is in).

```bash
# Python: MCP server and backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Dashboard
cd frontend && npm install && cd ..
```

**Environment variables.** Copy the example file and add your key:

```bash
cp .env.example .env
```

| Variable | Required? | Default | Purpose |
| --- | --- | --- | --- |
| `PORTKEY_API_KEY` | **Yes, to run agents** | — | Key for the Portkey gateway; every agent call goes through it |
| `OPENAI_MODEL` | No | `gpt-6-luna` | The only accepted value is `gpt-6-luna`; anything else stops the backend |
| `PORTKEY_BASE_URL` | No | `https://api.portkey.ai/v1` | Portkey endpoint |
| `LLM_REASONING_EFFORT` | No | `none` | Luna models need `none` to use tools |
| `CORS_ORIGINS` | No | `http://localhost:5173,http://127.0.0.1:5173` | Origins allowed to call the API |
| `VITE_API_BASE` (in `frontend/.env.local`) | No | `http://localhost:8000` | Where the dashboard finds the API (see `frontend/.env.example`) |

`.env` is git-ignored. Never commit a real key. Instead of a `.env` file, you can also
export `PORTKEY_API_KEY` in your shell.

## 3. The databases

| File | Role |
| --- | --- |
| `data/campus_customs.db` | **The original. Never modified by any code.** Every reset starts from it. |
| `data/campus_customs_new.db` | The **working copy** that the MCP server reads and writes. |

As committed, the working copy holds the **final state of the recorded run**
(`backend/output/resolved_tickets.json`):

- Tickets 101 and 103 are resolved.
- Ticket 102 is awaiting approval, with a $2,400 rent payment request left pending.
- Checking is $3,400.00.

When the MCP server opens the working copy, it adds four workflow tables
(`payment_requests`, `purchase_requests`, `message_drafts`, `ticket_notes`). It
doesn't change the structure of any shop table.

### Reset the working copy before a full run

Use either method. Both copy the original over the working copy and leave the
original untouched.

```bash
# A) From the shell, with nothing running
cp data/campus_customs.db data/campus_customs_new.db

# B) Through the running API (refused with 409 while an agent run or approval is in progress)
curl -X POST http://localhost:8000/api/admin/reset -H 'Content-Type: application/json' -d '{"confirm":"RESET"}'
```

You can also use the dashboard's **Start fresh** button, which calls B. After a
reset, checking is back to **$3,400.00** and tickets 101, 102 and 103 are open.

## 4. Start the system

Use two terminals, both starting from the repository root.

**Terminal 1: the backend (it starts the MCP server for you)**

```bash
source .venv/bin/activate
cd backend
uvicorn main:app --reload --port 8000
```

- Check it at http://localhost:8000/api/health. It should show `"status": "ok"`,
  `"mcp_connected": true`, and `"portkey_key_configured": true` if your key is set.
- The interactive API docs are at http://localhost:8000/docs.

**Terminal 2: the dashboard**

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. Port 5173 is fixed to match the backend's CORS setting.

**The MCP server.** You don't start it by hand in normal use. The backend launches it
as a subprocess over stdio: once in agent mode for the agents, and once in approver
mode for human decisions. Both use the settings in `mcp.json`. To run or test it on
its own:

```bash
.venv/bin/python mcp_server/server.py              # agent mode (13 tools), waits for a client on stdio
.venv/bin/python mcp_server/server.py --approver   # approver mode (17 tools): human-approval process only
```

To use the tools from Claude Code, run `claude --mcp-config mcp.json` from the
repository root. `mcp_server/README.md` documents every tool.

## 5. Running the three tickets

1. **Reset the working copy** (section 3).
2. **In the dashboard, pick a ticket on the left rail** (101, 102 or 103) and click
   **Send to the team**. The shift log fills in live: which agents work, who hands off
   to whom, and which MCP tools they call.
3. **If the agents prepare a payment,** it appears on the right as a pink
   **"Not paid · needs your signature"** slip.
   - Enter your name under **Signing as**.
   - Then choose **Approve & pay** (confirmed in two steps) or **Reject** (a reason
     is required).
   - Money moves only when you approve, and the backend re-checks the balance at that
     moment.
4. **If the Boss asks for a human decision,** use **Notes from you to the team** on
   that ticket, then click **Send to the team again**.
5. **The till** shows the real checking balance, kept apart from amounts that are
   merely waiting for a signature.

Each run takes about 20–40 seconds and uses roughly 20–40k tokens.

## 6. What's in the repository

```text
.
├── README.md                 this file
├── AI_prompts.md             the full prompt log of how this project was built
├── requirements.txt          Python dependencies (MCP server + backend)
├── .env.example              required environment variables (no real values)
├── .gitignore
├── mcp.json                  MCP client config: launches the server in agent mode
├── github_url.txt            the public repository URL
├── data/
│   ├── campus_customs.db     original database (never modified)
│   └── campus_customs_new.db working copy (final state of the recorded run)
├── mcp_server/
│   ├── server.py             FastMCP server: 17 tools, agent and approver modes
│   └── README.md             tool reference
├── frontend/                 React + Vite + TypeScript dashboard (src/, package.json)
└── backend/
    ├── main.py               FastAPI app: all API routes
    ├── models.py             shared data types and API shapes
    ├── config.py             the one model (gpt-6-luna) and Portkey settings
    ├── mcp_connection.py     the agents' MCP connection (agent mode only)
    ├── human_mcp.py          the API's approver-mode MCP connection
    ├── audit.py              append-only audit trail writer
    ├── agents/               one file per agent, plus team.py (delegation, loop guards, limits)
    ├── prompts/              system prompts: boss, inventory, accounting, facilities, customer_service
    └── output/
        ├── harness.md            technical documentation of the whole system
        ├── mcp_smoke.json        MCP connection test record
        ├── desk_tickets.html     Expected vs Actual for each ticket, Cash, Reflection (open in a browser)
        ├── design.md             dashboard design notes
        ├── resolved_tickets.json structured results of the recorded run
        ├── resolved_board.html   screenshots of the dashboard after the run (open in a browser)
        └── audit_trail.json      append-only log of every agent run and human decision
```

**Where to read more:**

- `backend/output/harness.md` is the technical reference. Section 16 summarises the
  finished system: tables, tools, agents, routes, the dashboard and safety measures.
- `backend/output/desk_tickets.html` holds the evaluation.

## 7. Troubleshooting

| Problem | Fix |
| --- | --- |
| `Address already in use` on 8000 or 5173 | Another server is running. Stop it, or find it with `lsof -i :8000` and stop that process. Vite uses a fixed port on purpose, so CORS keeps working. |
| `/api/health` shows `portkey_key_configured: false` | Put `PORTKEY_API_KEY` in `.env` at the repository root, or export it, then restart uvicorn. |
| The dashboard shows "Backend offline" | Start Terminal 1. The dashboard reconnects by itself. |
| "OPENAI_MODEL is …" error at start | Remove `OPENAI_MODEL`, or set it to `gpt-6-luna`. |
| "The working database … was not found" | `cp data/campus_customs.db data/campus_customs_new.db` |
| **Windows** | Create the virtual environment with `py -m venv .venv`, install with `.venv\Scripts\pip install -r requirements.txt`, activate with `.venv\Scripts\activate`, and change `command` in `mcp.json` to `.venv\\Scripts\\python.exe`. Use `copy` instead of `cp`. |
| Editing a `.py` file during a run | `--reload` restarts the API and cancels that run. The run history is rebuilt from the audit trail. |
