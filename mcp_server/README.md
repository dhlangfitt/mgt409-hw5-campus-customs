# Campus Customs MCP server

## What it's for

This server is the only way the agent team reads or changes the shop's data.
Agents have no database code of their own. They call the tools here, so every
agent gets the same data in the same shape, with the same rules applied.

## Which database it uses

It uses only the working copy, `data/campus_customs_new.db`. The path is worked
out from this file's location. The original `data/campus_customs.db` is never
opened. For tests, `CAMPUS_CUSTOMS_DB` can point at a throwaway copy, but the
server refuses to start if it points at the original.

- Read tools open the database read-only.
- Write tools open it read-write and do all their work in a single transaction.
- If the working copy is missing, every tool returns `database_unavailable` with
  the command to recreate it. The server never creates an empty database.

On first use, the server adds four workflow tables to the working copy:
`payment_requests`, `purchase_requests`, `message_drafts` and `ticket_notes`. It
doesn't change the structure of any shop table.

## Two modes

| Mode | Command | Who starts it | Tools |
| --- | --- | --- | --- |
| Agent (default) | `python mcp_server/server.py` | `mcp.json`: the agent team and Claude Code | 13: read and prepare tools. **None moves money.** |
| Approver | `python mcp_server/server.py --approver` | The backend API (`backend/human_mcp.py`) for the human-approval process only | The same 13, plus 4 human-only tools |

In agent mode, the payment-execution tool isn't registered at all, so an agent
calling it gets "Unknown tool". The backend also refuses to start the agents'
connection if `mcp.json` ever contains `--approver`.

## The tools

### Read (agent mode)

| Tool | Inputs | Returns |
| --- | --- | --- |
| `list_ticket_board` | `include_resolved` (default false) | Tickets on the board, with counts of pending requests and drafts |
| `get_ticket_details` | `ticket_id` | The ticket, summaries of its linked invoice, lease and stock row, and its notes, drafts and requests |
| `get_invoice_and_vendor_status` | `invoice_id` | The invoice and whether it's overdue; the vendor, its lead time, all its unpaid invoices and whether it's on a shipping hold; linked tickets; cash coverage |
| `get_rent_payment_status` | `lease_id` | The lease; days until rent is due or days overdue; rent payments recorded; linked tickets; cash coverage after every other bill |
| `get_stock_and_price_quote` | `sku`, `size`, `quantity`, `discount_percent` | Stock in this size and all sizes; the shortfall; cost and list price; break-even price; the largest discount that stays at or above cost; a quote; tickets for this SKU |
| `list_vendors_with_status` | none | Every vendor's lead time, unpaid invoices, shipping hold and earliest arrival |
| `check_cash_for_amount` | `amount` | Cash coverage for any amount, alongside every bill on record |
| `get_cash_position` | none | Balances, every bill on record, the balance after all of them, and recent payments |
| `list_pending_approvals` | `include_decided` (default false) | Payment and purchase requests waiting for a human (or all of them, with their status) |

### Prepare (agent mode; writes requests, notes and drafts, but never moves money or contacts anyone)

| Tool | Who may use it | What it does |
| --- | --- | --- |
| `prepare_payment_request` | accounting | Creates a `pending_approval` payment request for an invoice or rent. The amount and payee come from the database. Refuses duplicates and invoices that are already paid. |
| `prepare_purchase_request` | inventory, accounting | Creates a `pending_approval` restock request costed at quantity × unit cost. Records whether the vendor is on hold and the expected arrival. |
| `save_draft_message` | any agent | Saves a draft to a customer, vendor or landlord. It is never sent. |
| `update_ticket_status` | boss | Sets `open`, `in_progress`, `awaiting_approval` or `resolved`, with a note |

### Human approval (approver mode only)

| Tool | What it does |
| --- | --- |
| `execute_approved_payment` | Needs a named human (agent names are refused) and a pending request. It re-checks, inside the transaction, that the bill is unchanged and **refuses if the balance is less than the amount**. A refusal marks the request `failed` with the reason, and no money moves. Otherwise, in one transaction, it records the payment, lowers the balance, marks the invoice `paid` or moves the lease's `next_due` forward a month, and marks the request `executed`. |
| `reject_payment_request` | Marks a pending payment request rejected. No money moves. |
| `decide_purchase_request` | Approves or rejects a restock request. Records the decision only. |
| `add_human_note` | Records a person's decision or instruction on a ticket (author `human:<name>`). The Boss reads it on the next run. |

## How the tools respond

Every tool returns the same JSON envelope:

- `ok`: `true` with a `data` object, or `false` with an `error` object.
- `shop_today`: `desk.date_today`. Overdue and due-in checks use this date, never
  the computer's clock.
- `not_in_database`: anything relevant the database doesn't hold, such as which
  vendor supplies a product. The tools report these gaps rather than fill them in.
- `assumptions`: rules the tool applied, such as the vendor shipping-hold rule.
- `source_tables`: the tables the tool read or wrote.

The `error.type` value is one of these:

| `error.type` | When it happens |
| --- | --- |
| `invalid_input` | A bad argument |
| `not_found` | No such record. The error lists the IDs, SKUs or sizes that do exist. |
| `refused` | A shop rule stopped the action. `error.reason` says which: `insufficient_funds`, `duplicate`, `role_not_allowed`, `agent_cannot_approve`, `not_pending`, `stale_request`, `not_unpaid`, … |
| `database_unavailable` | The working copy is missing or can't be opened |
| `database_error` | Any other SQLite error |

## Setting up and connecting

Run these from the `hw5` folder. The virtual environment lives in `hw5/.venv`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

You don't run the server by hand. An MCP client starts it as a subprocess using
the project-level `hw5/mcp.json`, which always uses agent mode:

```json
{ "mcpServers": { "campus-customs": {
    "type": "stdio", "command": ".venv/bin/python",
    "args": ["mcp_server/server.py"], "env": {} } } }
```

- **Paths are relative to `hw5/`.** Start the client from the `hw5` folder. The
  database path doesn't depend on this.
- **No environment variables or secrets.** The server doesn't need any, so `env`
  is empty.
- **Windows.** The command is `.venv\Scripts\python.exe` instead.
- **Claude Code.** Use `claude --mcp-config mcp.json`, started in `hw5`. Claude
  Code only loads a config automatically if it is named `.mcp.json`, at the root
  of the folder the session starts in.
- **Coursework sessions.** These start in the sibling `mcp_servers/` folder, so
  the same entry is in `mcp_servers/.mcp.json`, with paths relative to that
  folder.

To start the server by hand for debugging (it waits for a client on stdio):

```bash
.venv/bin/python mcp_server/server.py              # agent mode
.venv/bin/python mcp_server/server.py --approver   # approver mode, human process only
```

The dashboard doesn't call this server. It goes through the backend API (`backend/main.py`).

Test records are in `backend/output/mcp_smoke.json`. Full documentation is in
`backend/output/harness.md`, sections 7–14.
