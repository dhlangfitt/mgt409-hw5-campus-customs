# Campus Customs Multi-Agent Operations — Technical Harness

This is the running technical documentation for the project. New sections are added
as each part of the system is built. Existing sections get corrected or extended, never
overwritten.

**How to read the tables below**

- **Found** means it was read directly from the database's schema or rows.
- **Inferred** means it's an interpretation of how the shop or the agents would use the
  data. The database doesn't say it.

The agent team: **Boss**, **Inventory**, **Accounting**, **Facilities** and **Customer
Service**.

| Date | Problem | Change |
| --- | --- | --- |
| 2026-11-06 | 2 — Study the Campus Customs Database | Created. Databases, every table and field, relationships, and traces of tickets 101–103. |
| 2026-11-06 | 3 — Build the MCP Server | Added section 7: the MCP server and its first three tools. |
| 2026-11-06 | 4 — Connect and Test the MCP Server | Added section 8: `mcp.json`, the `hw5/.venv` environment and the live MCP smoke test. No tool code changed. |
| 2026-11-06 | 5 — Build the Agent Team and Expand the MCP Tools | Added sections 9–12: the expanded MCP server (15 tools, agent and approver modes), the five agents, delegation and limits, the audit trail, and safety. Notes added to sections 7 and 8 where Problem 5 changed them. |
| 2026-11-06 | 6 — Plan How the Three Tickets Should Be Resolved | Added section 13: `desk_tickets.html` and the lean routing rule. The Boss and Accounting prompts changed (section 10.3 note). |
| 2026-11-06 | 7 — Build the Backend API Routes | Added section 14: the FastAPI routes, update strategy, approval lifecycle, locking and reset. The MCP server gained `get_cash_position`, `list_pending_approvals(include_decided)`, a `failed` payment-request state and reset-safe schema creation. Accounting gained `prepare_purchase_request` (notes in 9.3 and 10.3). |
| 2026-11-06 | 8 — Build the React Agent Dashboard | Added section 15: the dashboard in `frontend/` (design rationale in `design.md`). The audit trail's string limit went from 240 to 600 characters (section 11 note). |
| 2026-11-06 | 9 — Run the Agents and Resolve the Three Tickets | Added section 16, the finished system as it stands now (where earlier sections differ, 16 is current), and section 17, the full run and its results. New: the `add_human_note` tool, `POST /api/tickets/{id}/notes`, the dashboard notes box, run history rebuilt from the audit trail on startup, the full Boss outcome logged in `run_finished`, and a fix for the stuck "Working" state. |

---

## 1. Databases

| File | Role | Found |
| --- | --- | --- |
| `data/campus_customs.db` | Original. **Never modified.** | 53,248 bytes, SHA-1 `f447ca6a2766a90f3c1f81215c8f774ab109ea4c` |
| `data/campus_customs_new.db` | Working copy. All development and testing use this file. | Created 2026-11-06 by plain file copy. Same size and SHA-1 as the original at creation. `PRAGMA integrity_check` = `ok`. |

To get a clean working copy again, run this from `hw5/`:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

## 2. The shop's "today"

**Found.** `desk.date_today` = **2026-08-31**. It's the only `date_today` field in the
database. The project brief calls it `desk_tickets.date_today`, but the database stores
`desk` and `tickets` as two separate tables, and the date is in `desk`. All three tickets
were created on 2026-08-31, and the cash balance is dated 2026-08-31.

**Inferred.** Every due-date and overdue check must use this date, not the computer's
clock. Using the real date (2026-11-06) would make the rent look two months overdue
when it's actually due in two days.

## 3. Tables at a glance

| Table | Rows | Primary key | Declared links | What it's for (short) |
| --- | --- | --- | --- | --- |
| `desk` | 1 | none | — | Shop date |
| `tickets` | 3 | `id` | `lease_id` → `leases.id`, `invoice_id` → `invoices.id` | Open-ticket board |
| `inventory` | 10 | (`sku`, `size`) | — | Stock on hand per size |
| `pricing` | 4 | `sku` | — | Cost and selling price per product |
| `vendors` | 3 | `id` | — | Suppliers and lead times |
| `invoices` | 1 | `id` | `vendor_id` → `vendors.id` | Bills owed to vendors |
| `leases` | 1 | `id` | — | Rent obligations |
| `cash_accounts` | 1 | `name` | — | Cash available to pay with |
| `payments` | 0 | `id` | — | Record of money paid out |

## 4. Tables in detail

### 4.1 `desk`

| Field | Type | Constraint | Found values |
| --- | --- | --- | --- |
| `date_today` | TEXT | NOT NULL | `2026-08-31` |
| `notes` | TEXT | — | NULL |

**Found.** One row. It has no primary key and no other fields.

**Inferred.** This is the shop's clock. Every "is it overdue?", "how many days until
it's due?" and "when could a restock arrive?" calculation starts here. For example,
invoice 501 (due 2026-08-28) is 3 days overdue, the rent (due 2026-09-02) is due in
2 days, and a 5-day vendor lead time means 2026-09-05 at the earliest.

**Agents.** All of them. **Boss** uses it to prioritise, **Accounting** for overdue
invoices, **Facilities** for the rent date and **Inventory** for delivery estimates.

### 4.2 `tickets`

| Field | Type | Constraint | Found values |
| --- | --- | --- | --- |
| `id` | INTEGER | PRIMARY KEY | 101, 102, 103 |
| `type` | TEXT | NOT NULL | `customer_order`, `rent_notice`, `price_override` |
| `requester` | TEXT | NOT NULL | `Tauhid Zaman`, `Elm City Properties`, `Yale AI Club` |
| `subject` | TEXT | NOT NULL | `Bulldog tee`, `Rent due`, `Bulk hoodie discount` |
| `sku` | TEXT | — | `CC-TEE-WHITE` (101), `CC-HOOD-NAVY` (103) |
| `size` | TEXT | — | `S` (101), `M` (103) |
| `qty` | INTEGER | — | 1 (101), 20 (103) |
| `lease_id` | INTEGER | FK → `leases.id` | 1 (102) |
| `invoice_id` | INTEGER | FK → `invoices.id` | 501 (101) |
| `status` | TEXT | NOT NULL | `open` (all three) |
| `notes` | TEXT | — | The request in plain words |
| `created_at` | TEXT | NOT NULL | ISO timestamps with a `-04:00` offset, all on 2026-08-31 |

**Found.** Three open tickets. Which optional fields are filled depends on the type:
101 has a product plus an invoice link, 102 has only a lease link, and 103 has only a
product. `requester` is free text. There's no customers table and no contact details.
The schema doesn't define any allowed `type` or `status` values (no CHECK constraints).

**Inferred.** This is the open-ticket board. **Boss** reads `type` and the linked IDs to
decide who handles what. A `customer_order` needs Inventory and Customer Service, a
`rent_notice` needs Facilities and Accounting, and a `price_override` is a Boss decision
with input from Accounting and Inventory. `status` is the field that changes when a
ticket is resolved. Because customers are only names with no contact details,
**Customer Service** can only draft replies, which fits the "drafts stay on the board"
rule.

**Agents.** **Boss** reads every ticket. Each specialist reads the tickets routed to it.

### 4.3 `inventory`

| Field | Type | Constraint | Found values |
| --- | --- | --- | --- |
| `sku` | TEXT | NOT NULL, PK part | 4 products |
| `name` | TEXT | NOT NULL | e.g. `Classic Bulldog Tee` |
| `size` | TEXT | NOT NULL, PK part | `S`, `M`, `L`, `XL`, `OS` (one size) |
| `qty` | INTEGER | NOT NULL | 0–40 |
| `location` | TEXT | NOT NULL | `Aisle A`–`Aisle D` |

**Found.** Stock on hand, with one row per product and size:

| SKU | Product | S | M | L | XL | OS | Location |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CC-HOOD-NAVY` | Basic Hoodie Big Yale | 4 | **8** | 14 | 6 | | Aisle A |
| `CC-TEE-WHITE` | Classic Bulldog Tee | **0** | 5 | 3 | 2 | | Aisle B |
| `CC-HAT-BLUE` | Yale Cap | | | | | 40 | Aisle C |
| `CC-MUG-CREST` | Crest Mug | | | | | 0 | Aisle D |

The S tee and the mug are out of stock.

**Inferred.** This table answers "can we fill this order now?". A stock check has to
use both `sku` and `size`, because each size has its own stock. For ticket 101, the S
tee has 0 in stock, so it can't be filled. For ticket 103, there are 8 M hoodies
against the 20 requested, a shortfall of 12. Other sizes are in stock, but the club
asked for M.

**Agents.** **Inventory** is the main user. **Customer Service** uses it to know what
can be offered, and **Boss** uses it when deciding.

### 4.4 `pricing`

| Field | Type | Constraint | Found values |
| --- | --- | --- | --- |
| `sku` | TEXT | PRIMARY KEY | 4 products |
| `unit_cost` | REAL | NOT NULL | Hoodie 22.00, Tee 8.00, Cap 6.00, Mug 3.50 |
| `list_price` | REAL | NOT NULL | Hoodie 58.00, Tee 28.00, Cap 22.00, Mug 14.00 |

**Found.** One price per product. Prices don't vary by size.

**Inferred.** `unit_cost` is what the shop pays per item and `list_price` is what the
customer pays. For ticket 103, 20 hoodies cost 1,160.00 at list price and 440.00 at
cost. Cost is the floor for any discount, and **Boss** makes the final call on how far
toward it to go. If the shop pays vendors `unit_cost`, restocking the missing 12 M
hoodies would mean about 264.00 going out. In ticket 101 the tee sells for 28.00.

**Agents.** **Accounting** (margin and discount floor), **Boss** (final discount),
**Customer Service** (quoting a price in a draft) and **Inventory** (restock cost).

### 4.5 `vendors`

| Field | Type | Constraint | Found values |
| --- | --- | --- | --- |
| `id` | INTEGER | PRIMARY KEY | 1, 2, 3 |
| `name` | TEXT | NOT NULL | `Bulldog Print Co`, `Elm City Gifts`, `QuickShip CT` |
| `specialty` | TEXT | NOT NULL | `apparel reprint`, `mugs and small goods`, `local courier` |
| `lead_days` | INTEGER | NOT NULL | 5, 3, 1 |

**Found.** Three vendors. **Nothing in the database links a product to a vendor.**

**Inferred.** This table says where restock comes from and how long it takes (the brief
says vendor lead times live here). Going by `specialty`, Bulldog Print Co most likely
supplies both the tee (101) and the hoodie (103), and Elm City Gifts the mug. QuickShip
CT looks like a courier, not a supplier. The earliest arrival is `date_today` +
`lead_days`, which for Bulldog Print Co is 2026-09-05, and only once the vendor is
willing to ship.

**Agents.** **Inventory** is the main user. **Accounting** uses it to know who is owed,
and **Customer Service** for delivery estimates in drafts.

### 4.6 `invoices`

| Field | Type | Constraint | Found values |
| --- | --- | --- | --- |
| `id` | INTEGER | PRIMARY KEY | 501 |
| `vendor_id` | INTEGER | NOT NULL, FK → `vendors.id` | 1 (Bulldog Print Co) |
| `amount` | REAL | NOT NULL | 840.00 |
| `due_date` | TEXT | NOT NULL | 2026-08-28 |
| `status` | TEXT | NOT NULL | `open` |
| `description` | TEXT | — | `Rush reprint CC-TEE-WHITE S` |

**Found.** There's one bill: 840.00 owed to Bulldog Print Co for a rush reprint of
exactly the out-of-stock S tee. It's still open, 3 days past due as of `date_today`, and
ticket 101 links to it. `open` is the only status value present.

**Inferred.** This table holds the money the shop owes. An invoice is overdue when it's
`open` and its `due_date` is before `date_today`. Under the brief's vendor rule, Bulldog
Print Co won't ship anything new while invoice 501 is unpaid, which holds up ticket 101's
tee and probably ticket 103's hoodies. After a human-approved payment, the invoice's
`status` needs to change. No "paid" value exists in the data yet.

**Agents.** **Accounting** is the main user. **Inventory** uses it to check whether a
vendor is blocked, and **Boss** for priorities.

### 4.7 `leases`

| Field | Type | Constraint | Found values |
| --- | --- | --- | --- |
| `id` | INTEGER | PRIMARY KEY | 1 |
| `space_name` | TEXT | NOT NULL | `Chapel Street shop` |
| `landlord` | TEXT | NOT NULL | `Elm City Properties` |
| `monthly_rent` | REAL | NOT NULL | 2,400.00 |
| `next_due` | TEXT | NOT NULL | 2026-09-02 |
| `notes` | TEXT | — | empty |

**Found.** There's one lease: rent of 2,400.00 is due on 2026-09-02, 2 days after
`date_today`, which matches ticket 102's note. The landlord's name is the same as
ticket 102's `requester`, but the two are matched by text only. The actual link is
`tickets.lease_id`.

**Inferred.** This table holds the rent obligation. The rent is due soon but isn't
overdue. After rent is paid, `next_due` should move forward, probably by one month to
2026-10-02, but the database doesn't say how.

**Agents.** **Facilities** is the main user. **Accounting** handles the payment.

### 4.8 `cash_accounts`

| Field | Type | Constraint | Found values |
| --- | --- | --- | --- |
| `name` | TEXT | PRIMARY KEY | `checking` |
| `balance` | REAL | NOT NULL | 3,400.00 |
| `date` | TEXT | NOT NULL | 2026-08-31 |

**Found.** There's one account, `checking`, with 3,400.00 as of the shop's today.

**Inferred.** This is all the money available. The payment tool must refuse any
payment larger than the balance, so the balance can never go negative. Because this
project models only money going out, the balance can only go down. The two known bills
(840.00 + 2,400.00 = 3,240.00) would leave **160.00**.

**Agents.** **Accounting** is the main user. **Boss** uses it to decide what gets
paid first.

### 4.9 `payments`

| Field | Type | Constraint | Found values |
| --- | --- | --- | --- |
| `id` | INTEGER | PRIMARY KEY | — |
| `kind` | TEXT | NOT NULL | — |
| `ref_id` | INTEGER | — | — |
| `amount` | REAL | NOT NULL | — |
| `account` | TEXT | NOT NULL | — |
| `paid_at` | TEXT | NOT NULL | — |
| `approved_by` | TEXT | NOT NULL | — |

**Found.** The table is empty, so nothing has been paid yet. `approved_by` is NOT NULL,
so the schema itself won't accept a payment row without an approver. It has no declared
foreign keys.

**Inferred.** This is the record of money going out. `kind` says what was paid (for
example an invoice or rent), `ref_id` points to `invoices.id` or `leases.id` depending
on `kind`, and `account` names a `cash_accounts` row. A human-approved payment would
touch four tables. It would add a row here, lower `cash_accounts.balance`, and update
either `invoices.status` or `leases.next_due`. It would also change the related
ticket's `status`. These are the "relevant tables" the brief says must be updated.
None of the `kind` values are defined yet.

**Agents.** **Accounting** writes to it, but only after a human approves. **Boss** and
the human use it to check what was paid.

## 5. Relationships

```text
                       desk  (one row: date_today, the shop's clock)

  vendors ──< invoices ──< tickets >── leases
                              ┆
                        (sku, size)
                              ┆
                          inventory ┄┄ pricing  (by sku)

  payments ┄┄ (kind, ref_id) ┄┄> invoices | leases
  payments.account ┄┄> cash_accounts.name

  ── declared foreign key        ┄┄ implied link (no constraint)
```

**Declared foreign keys (found):** `invoices.vendor_id → vendors.id`,
`tickets.invoice_id → invoices.id` and `tickets.lease_id → leases.id`. SQLite only
enforces foreign keys when a connection turns on `PRAGMA foreign_keys = ON`. It's off by
default and was off when checked.

**Implied links with no constraint (found by matching values):**

- `tickets` (`sku`, `size`) → `inventory` (`sku`, `size`)
- `tickets.sku` and `inventory.sku` → `pricing.sku`
- `tickets.requester` = `leases.landlord`, for ticket 102 (text only)

**Inferred links:** `payments.ref_id` points to an invoice or a lease depending on
`payments.kind`, and `payments.account` points to `cash_accounts.name`.

**Not in the database (found by absence):**

- No link from a product to the vendor that supplies it.
- No customers table and no contact details. Requesters are names only.
- Nowhere to store drafts, approvals, messages between agents, or an audit trail.
- No defined set of `status` or `kind` values. The only status seen is `open`.

## 6. The three open tickets

### Ticket 101 — `customer_order`: Bulldog tee (Tauhid Zaman)

**Found**

- The customer wants 1 × `CC-TEE-WHITE`, size S. Note: "Needs a tee in size S."
- Stock for S is **0**. Other sizes: M 5, L 3, XL 2. The tee sells for 28.00 and costs
  8.00.
- The ticket links to **invoice 501**: Bulldog Print Co, 840.00, "Rush reprint
  CC-TEE-WHITE S". It was due 2026-08-28, is still `open`, and is **3 days overdue**.
- Bulldog Print Co's lead time is 5 days.

**Inferred**

- The S tee is out of stock, and the reprint that would restock it is held up by the
  vendor's own unpaid, overdue invoice.
- Paying invoice 501 needs human approval. At 840.00 against 3,400.00 it's affordable.
- Once it's paid, the vendor can ship. The earliest arrival is about 2026-09-05.
- Likely flow: **Inventory** checks stock and finds the blocking vendor. **Accounting**
  checks the invoice and cash, then asks for approval. A human approves.
  **Customer Service** drafts a note to the customer with the delay, the date and maybe
  other sizes. **Boss** closes the ticket.

### Ticket 102 — `rent_notice`: Rent due (Elm City Properties)

**Found**

- The ticket links to **lease 1**, the Chapel Street shop: 2,400.00, due 2026-09-02,
  which is **2 days** after `date_today`.
- Ticket note: "Email: shop rent due in 2 days."
- Cash on hand is 3,400.00.

**Inferred**

- The rent isn't overdue yet, but it's due before any vendor could deliver anything.
- **Facilities** confirms the amount and date. **Accounting** checks cash and prepares
  the payment. After a human approves, the payment is recorded and the balance and the
  lease's `next_due` are updated.

### Ticket 103 — `price_override`: Bulk hoodie discount (Yale AI Club)

**Found**

- The club wants 20 × `CC-HOOD-NAVY`, size M, and is asking for a bulk discount.
- Stock for M is **8**. Other sizes: S 4, L 14, XL 6.
- Hoodies sell for 58.00 and cost 22.00. 20 at list price would be 1,160.00.
- The ticket has no invoice or lease link.

**Inferred**

- There are two decisions here:
  - **The price.** **Boss** makes the final call. **Accounting** supplies the cost floor
    (22.00 a hoodie) and the margin.
  - **The supply.** 8 are available now, so 12 are short. A restock most likely comes
    from Bulldog Print Co, which is blocked by invoice 501 and has a 5-day lead time.
    It would cost about 264.00 going out.
- **Customer Service** drafts the reply to the club.
- The brief only requires human approval for payments, so whether a discount also
  needs a human's sign-off is an open question.

### How the tickets affect each other

1. **One vendor blocks two tickets (inferred).** Invoice 501 to Bulldog Print Co
   (ticket 101) is unpaid. Under the vendor rule that blocks the tee reprint, and
   probably also the hoodie restock for ticket 103. The database has no
   product-to-vendor link to confirm the second part.
2. **One cash account, three demands (arithmetic on found values).**
   3,400.00 − 840.00 (invoice 501) − 2,400.00 (rent) = **160.00**. A roughly 264.00
   hoodie restock wouldn't fit after both bills are paid. So the order of payments and
   decisions matters. Whether a restock has to be paid up front is not known.
3. **Similar names (found).** Elm City Properties (the landlord, ticket 102) and Elm
   City Gifts (vendor 2) are different parties. Agents should match on IDs, not names.

## 7. MCP server (`mcp_server/server.py`)

### 7.1 Structure

- Built with **FastMCP**. The server is named `campus-customs` and uses the stdio
  transport. Its one dependency, `fastmcp>=4.1,<5`, is listed in `requirements.txt`.
- **Database.** Only `data/campus_customs_new.db`, located relative to `server.py`
  and opened **read-only** (`mode=ro`). The original database is never opened. A
  missing working copy produces a `database_unavailable` error. The server never
  silently creates an empty database.
- **Read-only.** All three tools are read-only and are registered with the
  MCP read-only hint. None of them pays, writes, reserves or sends anything.

  > **Changed in Problem 5 (section 9).** These three tools are still read-only, but the
  > server now also has tools that write to the database, so it opens the working copy
  > read-write for those. `get_rent_payment_status` now lists the rent payments recorded
  > in `payments` (`kind = 'rent'`) instead of only counting rows. The server now refuses
  > to start against the original database if the `CAMPUS_CUSTOMS_DB` override points
  > at it.
- **Shared envelope.** Every tool returns these fields: `ok`, `tool`, `shop_today`,
  `data`, `not_in_database`, `assumptions` and `source_tables`. On failure it
  returns `ok: false` and an `error` with a `type` and a `message`.
- **Error types:**

  | `error.type` | Cause |
  | --- | --- |
  | `invalid_input` | A non-integer or out-of-range ID or quantity, an empty or over-long SKU or size, or a discount outside 0 to under 100 |
  | `not_found` | No such record. The error lists the IDs, SKUs or sizes that do exist. |
  | `database_unavailable` | The file is missing or can't be opened |
  | `database_error` | Any other `sqlite3` error |

  The parameter schemas also advertise these limits to MCP clients (for example
  `invoice_id` minimum 1). The same checks run inside each function as well.
- **No invented values.**
  - Dates come from `desk.date_today`. If `desk` doesn't have exactly one valid
    date, `shop_today` is null, every date-based field is null, and the reason is
    listed in `not_in_database`.
  - Broken links are reported in `not_in_database` and the affected fields are null.
    Examples: an invoice pointing at a vendor that doesn't exist, a SKU with no
    pricing row, or a due date that isn't a valid date.
- **Rules applied, all listed in each response's `assumptions`:**
  - An invoice is unpaid when `status = 'open'`, the only status value in the
    data.
  - The brief's vendor shipping-hold rule.
  - `pricing.unit_cost` is what the shop pays per unit.
  - "Other obligations on record" means every unpaid invoice plus each lease's
    next rent.

### 7.2 Tool: `get_invoice_and_vendor_status(invoice_id)`

**Built for ticket 101 (customer order: Bulldog tee, size S).**

- **What it does.**
  - Looks up one invoice: its amount, status, whether it's unpaid, its due date,
    and days overdue or days until due against `shop_today`.
  - Looks up the vendor who sent it: name, specialty and `lead_days`.
  - Lists every unpaid invoice that vendor has, and states whether the vendor
    will ship new products under the brief's rule (`vendor_will_ship_new_products`
    and `blocking_invoice_ids`).
  - Calculates the earliest arrival if the vendor shipped on `shop_today`.
  - Lists the tickets linked to the invoice.
  - For an unpaid invoice, gives the cash position: whether each account covers
    it, the balance after paying it, every other obligation on record, and what's
    left if everything on record were paid.
- **Tables read:** `invoices`, `vendors`, `tickets`, `desk`, `cash_accounts`,
  `leases`.
- **Why it matters for ticket 101.** The tee can't be supplied because ticket 101
  points at invoice 501. Run against the working copy, this one call shows:
  - Invoice 501 is 840.00, unpaid and 3 days overdue.
  - Bulldog Print Co therefore has `vendor_will_ship_new_products: false`, so the
    reprint is on hold.
  - The lead time is 5 days, so 2026-09-05 is the earliest arrival.
  - Checking can cover the 840.00, leaving 2,560.00. After the 2,400.00 rent as
    well, only 160.00 would remain.

  That's what an agent needs to propose paying the invoice for human approval, and
  to give Customer Service a realistic date for its draft reply to the customer.
- **What it doesn't do:**
  - It doesn't say which products the vendor supplies, because that link isn't in
    the database. It reports this in `not_in_database`.
  - It doesn't parse the invoice description.
  - It doesn't pay anything.

### 7.3 Tool: `get_rent_payment_status(lease_id)`

**Built for ticket 102 (rent notice from Elm City Properties).**

- **What it does.**
  - Looks up one lease: space, landlord, monthly rent, `next_due` and notes.
  - Gives the rent's due status against `shop_today` (days until due, or days
    overdue).
  - Lists the tickets linked to the lease.
  - Gives the same cash position as the invoice tool: account coverage, balance
    after paying the rent, and what's left after paying every other obligation on
    record.
  - Reports whether `payments` has any rows. It doesn't match them to the lease,
    because `payments.kind` has no defined values yet.
- **Tables read:** `leases`, `desk`, `cash_accounts`, `invoices`, `vendors`,
  `tickets`, `payments`.
- **Why it matters for ticket 102.** Ticket 102 points at lease 1. Run against the
  working copy, this call shows:
  - The 2,400.00 rent is due 2026-09-02, which is 2 days away and not overdue.
  - Checking can cover it, leaving 1,000.00.
  - The overdue 840.00 invoice 501 is the only other bill on record, and paying
    both would leave 160.00.
  - `payments` has no rows, so the rent hasn't already been paid.

  Facilities and Accounting need exactly this to put the rent payment forward for
  human approval, and the Boss needs it to see that paying rent and invoice 501
  together uses almost all the cash.
- **What it doesn't do:** it doesn't pay rent, and it doesn't move
  `leases.next_due`.

### 7.4 Tool: `get_stock_and_price_quote(sku, size, quantity, discount_percent=0)`

**Built for ticket 103 (Yale AI Club, 20 × size M hoodies, bulk discount).**

- **What it does.**
  - Matches the SKU and size without caring about case and ignores extra spaces.
  - Reports stock on hand and location for the requested size, whether the order
    can be filled from stock, the shortfall, stock for every other size, and total
    stock.
  - Reports unit cost and list price, the margin at list, the break-even price,
    and the largest discount that stays at or above cost. That discount is rounded
    down so it never undercuts cost.
  - Gives a quote at `discount_percent`: unit price, total price, total cost, gross
    margin, whether it's below cost, and the shortfall's cost at unit cost.
  - Lists every ticket that mentions this SKU.
- **Tables read:** `inventory`, `pricing`, `tickets`, `desk` (`desk` only to fill
  `shop_today`).
- **Why it matters for ticket 103.** The ticket asks two questions at once: can
  we supply 20 M hoodies, and how much discount can we give? Called with
  `CC-HOOD-NAVY`, `M`, `20`, `10`, it shows:
  - **Stock.** Only 8 M are on hand (Aisle A), so the order is 12 short. Restocking
    those 12 at unit cost would cost 264.00. Other sizes: S 4, L 14, XL 6.
  - **Price.** Cost is 22.00 and list is 58.00, so the largest discount that stays
    at or above cost is 62.0%.
  - **Quote.** At 10% off, the order comes to 1,044.00 against a cost of 440.00, a
    604.00 margin.

  The Boss makes the discount call from these numbers, Accounting can check the
  margin, and Customer Service can quote it in a draft.
- **Also used for ticket 101.** Called with `CC-TEE-WHITE`, `S`, `1`, it confirms
  0 S tees on hand (M 5, L 3, XL 2 are available), which is why ticket 101 depends
  on the vendor reprint.
- **What it doesn't do:**
  - It doesn't know which vendor supplies the SKU, so it can't give restock
    timing or vendor holds. It reports this in `not_in_database`, along with the
    absence of any discount policy.
  - It doesn't reserve stock, order anything or record a sale.

### 7.5 How the tools were checked (2026-11-06)

The server was **not started** and **no MCP client was connected**. `hw5` has no
virtual environment yet, so the check used the existing
`mcp_servers/mcp/yale_som/.venv`, which has fastmcp 4.1.3 and Python 3.14. The
script imported `server.py` and called the three functions directly.

- **Registration.** All three tools register with FastMCP. Their parameter schemas
  carry the limits (minimum 1, length 1–40, discount 0 to under 100), and the
  read-only hint is set.
- **Ticket calls.**
  - Invoice 501, lease 1, `CC-HOOD-NAVY`/`M`/20 at 10%, and `CC-TEE-WHITE`/`S`/1
    all returned the figures quoted in 7.2–7.4.
  - Mixed-case and padded input (`cc-hood-navy`, ` m `) matched correctly.
  - A 70% discount was flagged `below_cost: true`.
- **Invalid inputs.** All of these returned `invalid_input`:
  - `invoice_id` set to 0, `'abc'` or `True`
  - `lease_id` set to −1
  - a blank SKU
  - `quantity` set to 0
  - `discount_percent` set to 100 or NaN
- **Missing records.** All of these returned `not_found`, with the existing values
  listed:
  - invoice 999
  - lease 7
  - SKU `NOPE`
  - size `XXL`
- **Broken databases.** These were tested on throwaway copies outside the project:
  - **Missing file:** `database_unavailable`, and no empty file was created.
  - **Non-database file:** `database_error`.
  - **`desk` row deleted:** `shop_today` null, date fields null, and the gap
    reported.
  - **Invoice pointing at a missing vendor, no pricing row, invalid `next_due`:**
    each reported in `not_in_database`, with the affected fields null.
- **Databases untouched.** Both databases had the same checksums before and after
  the check.

## 8. MCP connection and smoke test

### 8.1 Configuration (`hw5/mcp.json`)

| Item | Setting | Why |
| --- | --- | --- |
| Server name | `campus-customs` | Same name as `FastMCP("campus-customs")` in `server.py` |
| Transport | `stdio` | The client launches the server as a subprocess, so there's no port to manage |
| Command | `.venv/bin/python` | The project's own environment. Use `.venv\Scripts\python.exe` on Windows. |
| Args | `mcp_server/server.py` | Relative path |
| Working directory | `hw5/` | Both paths above are relative to `hw5`, so the client must be started there. The database path doesn't depend on it, because `server.py` finds the database relative to its own location. |
| Environment variables | none (`"env": {}`) | The server needs no keys or settings, so the file holds no secrets |

- **Python environment.** `hw5/.venv` was created with Python 3.14.7 and
  `pip install -r requirements.txt`, which installed fastmcp 4.1.6. That's
  within the `>=4.1,<5` range. Section 7.5's earlier check used 4.1.3.
- **Claude Code.**
  - This session started in `mcp_servers/`, so `hw5/mcp.json` isn't loaded into
    it automatically. Claude Code only does that for a `.mcp.json` at the session's
    root.
  - Claude Code can load the file with `claude --mcp-config mcp.json` from `hw5`.
  - An attempt to confirm this from the command line stopped at "Not logged in",
    so that route hasn't been verified yet.
  - **Follow-up, same day.** At the user's request, a `campus-customs` entry was
    added to `mcp_servers/.mcp.json`, the config this Claude Code session starts
    from. It uses the same command and arguments, with paths relative to
    `mcp_servers/` (`../hw5/.venv/bin/python`, `../hw5/mcp_server/server.py`) and
    no environment variables. Launched from `mcp_servers/`, that entry starts the
    server, lists all three tools and answers `get_rent_payment_status(1)`
    correctly. Claude Code only reads `.mcp.json` when a session starts, so the
    tools appear after a restart, once the new project server is approved.
  - **Confirmed after the restart.** All three tools appeared in Claude Code as
    `mcp__campus-customs__*` and were called live with the same arguments as the
    smoke test. All returned `ok: true` with the same values as
    `mcp_smoke.json`.

### 8.2 Smoke test (2026-11-06) — `backend/output/mcp_smoke.json`

- **How it ran.**
  - Started in `hw5/`.
  - `fastmcp.Client` read `mcp.json`, launched the server over stdio and listed
    its tools.
  - It then called each tool through MCP `tools/call`, one call per tool.
  - The script was a one-off and isn't part of the project.
- **How the answers were checked.** Each answer was compared field by field with
  values read separately from `data/campus_customs_new.db` in read-only mode. The
  checks only verify the answers; they don't replace any tool.
- **Result.** The server listed all three tools, and every call succeeded:

  | Tool | Arguments | Fields matching the database |
  | --- | --- | --- |
  | `get_invoice_and_vendor_status` | `invoice_id` 501 | 9 / 9 |
  | `get_rent_payment_status` | `lease_id` 1 | 7 / 7 |
  | `get_stock_and_price_quote` | `CC-HOOD-NAVY`, `M`, 20, 10% | 7 / 7 |

- **Databases unchanged.** Both had the same checksums before and after.
- **Each entry in `mcp_smoke.json` records:**
  - the prompt (what the call was meant to find out, for which ticket)
  - the exact `tools/call` request
  - the tool name
  - the field-by-field database checks
  - the tool's full output
  - `successful`
- **Changes after testing.** No tool code changed. The only changes were the new
  configuration and environment, and the README's setup section.
- **Rerun in Problem 7.** Run again after the server changes. All three original tools
  pass, and the server lists 13 tools in agent mode.
- **Rerun in Problem 5.** After the server was expanded, the same script was run
  again and overwrote `mcp_smoke.json`. All three original tools still pass (9/9,
  7/7, 7/7). The server now lists 12 tools in agent mode.

## 9. Expanded MCP server (Problem 5)

### 9.1 Two modes, one server

| Mode | Started by | Tools |
| --- | --- | --- |
| **Agent mode** (default) | `mcp.json`, used by the agent team and by Claude Code | 8 read tools + 4 prepare tools. **No tool that moves money.** |
| **Approver mode** (`--approver`) | Only the human-approval process | The same 12, plus 3 human-only tools: `execute_approved_payment`, `reject_payment_request`, `decide_purchase_request` |

- `backend/mcp_connection.py` builds the agents' connection from `mcp.json` and
  refuses to start if `--approver` appears there. `backend/agents/role.py` refuses
  any agent definition that lists a human-only tool. The scripted test (section
  10.5) confirmed that a call to `execute_approved_payment` never reaches the
  server.
- The human-approval process (later, via the FastAPI backend and dashboard) starts
  its own connection in approver mode. That connection isn't attached to any agent.

### 9.2 Workflow tables added to the working copy

The server creates four tables with `CREATE TABLE IF NOT EXISTS` the first time it
opens the database. It doesn't change any existing shop table's structure.
Resetting the working copy removes them, and they're recreated empty on the next
start.

| Table | Holds |
| --- | --- |
| `payment_requests` | Prepared payments: type (`vendor_invoice` or `rent`), reference id, ticket, payee, amount, account, due date, reason, requester, status (`pending_approval`, then `executed` or `rejected`), human decision fields, `payment_id` |
| `purchase_requests` | Prepared restocks: vendor, SKU, size, quantity, unit cost, estimated cost, whether the vendor was on hold, expected arrival, status, human decision fields |
| `message_drafts` | Drafts to a customer, vendor or landlord. A CHECK constraint keeps `status` at `draft`; there is no "sent" state. |
| `ticket_notes` | A trail of who did what on each ticket. Human entries are written as `human:<name>`. |

**Checked on 2026-11-06.** After the live check (section 10.5), all nine shop
tables in the working copy were identical to the original's. The four new tables
existed, empty. The original's checksum was unchanged.

### 9.3 All tools

| Tool | Mode | What it does | Tables read (R) / written (W) |
| --- | --- | --- | --- |
| `list_ticket_board` | agent | Open tickets, with counts of pending requests and drafts | R: tickets, payment_requests, purchase_requests, message_drafts, desk |
| `get_ticket_details` | agent | One ticket, short summaries of its linked invoice, lease and stock row, and its notes, drafts and requests | R: tickets, invoices, vendors, leases, inventory, ticket_notes, message_drafts, payment_requests, purchase_requests, desk |
| `get_invoice_and_vendor_status` | agent | Section 7.2 (built for ticket 101) | R: invoices, vendors, tickets, desk, cash_accounts, leases |
| `get_rent_payment_status` | agent | Section 7.3 (built for ticket 102), plus rent payments recorded | R: leases, desk, cash_accounts, invoices, vendors, tickets, payments |
| `get_stock_and_price_quote` | agent | Section 7.4 (built for ticket 103) | R: inventory, pricing, tickets, desk |
| `list_vendors_with_status` | agent | Every vendor: lead_days, unpaid invoices, whether it's on a shipping hold, earliest arrival | R: vendors, invoices, desk |
| `check_cash_for_amount` | agent | Cash coverage for any amount (for example a restock estimate), with every bill on record | R: cash_accounts, invoices, vendors, leases, desk |
| `list_pending_approvals` | agent | Payment and purchase requests waiting for a human | R: payment_requests, purchase_requests, desk |
| `prepare_payment_request` | agent (**accounting only**) | Creates a `pending_approval` payment request. Amount and payee come from the database. Refuses duplicates and already-paid invoices, and reports whether the account covers it. **Moves no money.** | R: invoices, vendors, leases, cash_accounts, tickets, desk. W: payment_requests, ticket_notes |
| `prepare_purchase_request` | agent (**inventory, accounting**) | Creates a `pending_approval` restock request at quantity × unit cost, recording the vendor's hold status and expected arrival (none while on hold). **Orders nothing.** | R: vendors, invoices, inventory, pricing, tickets, desk. W: purchase_requests, ticket_notes |
| `save_draft_message` | agent (any agent) | Saves a draft to a customer, vendor or landlord. **Never sent.** | R: tickets, desk. W: message_drafts, ticket_notes |
| `update_ticket_status` | agent (**boss only**) | Sets `open`, `in_progress`, `awaiting_approval` or `resolved`, with a note | W: tickets.status, ticket_notes |
| `execute_approved_payment` | **approver only** | See 12.1 | R/W: payment_requests, payments, cash_accounts, invoices.status or leases.next_due, ticket_notes |
| `reject_payment_request` | **approver only** | Marks a pending payment request rejected. No money moves. | W: payment_requests, ticket_notes |
| `decide_purchase_request` | **approver only** | Approves or rejects a restock request. Records the decision only; no vendor is contacted and no money moves. | W: purchase_requests, ticket_notes |

> **Changed in Problem 7.**
> - **New tool `get_cash_position`** (agent mode, read-only): balances, every bill on
>   record, what's left after all of them, and the latest payments. It reads
>   cash_accounts, invoices, vendors, leases, payments and desk. No agent has it in
>   its allowlist; the API uses it for `GET /api/cash`. The server now has 16 tools:
>   13 in agent mode plus 3 for approvers.
> - **`list_pending_approvals(include_decided)`** can now also return executed,
>   approved, rejected and failed requests.
> - **`execute_approved_payment` failures are recorded.** When execution is refused
>   because the bill changed or the cash no longer covers it, the request is marked
>   `failed`, with the reason, in the same transaction. No money moves.
> - **Reset-safe schema.** The workflow tables are re-created after a database
>   reset; the check is keyed on the database file's identity.

The role restrictions marked in bold are enforced **on the server**, not just by
hiding tools. The backend overwrites `requested_by`, `author` and `updated_by`
with the real calling agent's name (section 10.2), so an agent can't claim to be
another agent.

## 10. The agent team (`backend/`)

### 10.1 Layout

```text
backend/
├── config.py            the one model (MODEL_ID = "gpt-6-luna"), the Portkey provider, paths
├── models.py            shared types: AgentReport, TicketOutcome, RunLimits, TicketRun, TeamDeps, AuditEvent
├── audit.py             append-only writer for output/audit_trail.json
├── mcp_connection.py    the agents' only data route: the MCP server from mcp.json (agent mode)
├── agents/
│   ├── role.py          RoleSpec: name, prompt file, MCP tool allowlist, output type
│   ├── boss.py          one file per agent, each holding that agent's definition
│   ├── inventory.py
│   ├── accounting.py
│   ├── facilities.py
│   ├── customer_service.py
│   └── team.py          builds the agents, ask_colleague delegation, loop guards, handle_ticket()
└── prompts/             one system prompt per agent (boss.md, inventory.md, …)
```

### 10.2 Model and connection

- **One model.** Every agent uses one shared `OpenAIChatModel("gpt-6-luna")`. It's
  built in `config.build_model()` and called through Portkey: `base_url`
  `https://api.portkey.ai/v1`, with `PORTKEY_API_KEY` from `.env`.
- **No other model can run.** `OPENAI_MODEL` may only equal `gpt-6-luna`; any other
  value stops the backend with an error. There is no fallback model and no default
  model string elsewhere. A search of `backend/`, `mcp_server/`, `mcp.json` and
  `.env.example` finds the model ID only in `config.py`, in the code and a
  docstring. `OPENAI_API_KEY` isn't used.
- **Settings.**
  - `openai_reasoning_effort="none"`. HW 4 found that Luna models reject tool calls
    otherwise, and every agent here uses tools.
  - `max_tokens` of 1,500 per reply.
- **Checked.** `gpt-6-luna` is listed by the Portkey gateway's `/v1/models`. The
  live check (10.5) confirmed the model object is `gpt-6-luna` at
  `https://api.portkey.ai/v1/`.
- **MCP connection.** All shop data goes through the MCP server. The agents have no
  database code. One MCP connection per ticket run is shared, and each agent sees a
  filtered view of it (its allowlist). Every MCP call passes through
  `_process_tool_call`, which:
  - stamps the real agent name into identity arguments;
  - enforces the tool-call budget;
  - writes an audit event.

### 10.3 The five agents

| Agent | Role | MCP tools | Typically asks |
| --- | --- | --- | --- |
| **Boss** | Owns each ticket. Reads it, involves only the specialists it needs, makes judgement calls (discount level, which bill first), sets the ticket status, returns a `TicketOutcome`. | `list_ticket_board`, `get_ticket_details`, `list_pending_approvals`, `update_ticket_status` | Any specialist, with a specific request |
| **Inventory** | Stock by size, which vendor can restock and when (lead time, shipping hold), restock cost, purchase requests | `get_ticket_details`, `get_stock_and_price_quote`, `list_vendors_with_status`, `get_invoice_and_vendor_status`, `check_cash_for_amount`, `prepare_purchase_request` | Accounting: can a blocking invoice be paid? |
| **Accounting** | Invoices, rent and cash, the order to pay bills in, margins and discount floors. **The only agent that can prepare a payment request.** | `get_ticket_details`, `get_invoice_and_vendor_status`, `get_rent_payment_status`, `check_cash_for_amount`, `get_stock_and_price_quote`, `list_vendors_with_status`, `list_pending_approvals`, `prepare_payment_request` | Inventory: would paying unblock supply? Facilities: lease details |
| **Facilities** | The lease, rent due dates, checking a notice against the lease record, landlord drafts | `get_ticket_details`, `get_rent_payment_status`, `list_pending_approvals`, `save_draft_message` | Accounting: prepare the rent payment request |
| **Customer Service** | Customer replies, as drafts only. Promises only what's been decided and confirmed. | `get_ticket_details`, `get_stock_and_price_quote`, `save_draft_message` | Inventory for timing, Accounting for prices |

> **Changed in Problem 6.** The Boss's prompt now says to use the smallest team: Accounting
> first for anything about money or availability, Customer Service only for customer replies, and
> Inventory or Facilities only for questions Accounting's tools can't settle. Accounting's prompt
> now says to answer factual supply questions itself instead of passing them to Inventory. The
> "Typically asks" column above shows the original design; tool allowlists didn't change.
>
> **Changed in Problem 7.** Accounting's allowlist now includes `prepare_purchase_request`
> (the server already allowed it). A scripted API test showed that with lean routing, Accounting
> couldn't record a restock for ticket 103.

Every agent also has `ask_colleague(colleague, request)`. Specialists return an
`AgentReport` with these fields:

- `status`: `done`, `needs_human_approval`, `needs_boss_decision`, `blocked` or
  `could_not_complete`
- `summary`
- `facts`, each with the tool it came from
- `actions_taken`, listing the ids of anything the agent created
- `open_questions`
- `handoff_reason`

### 10.4 Delegation and loop protection

- Any agent can ask any other agent through `ask_colleague`. The colleague runs as
  a nested agent and its report becomes the tool result. The Boss isn't a
  bottleneck: Inventory can ask Accounting directly, and so on.
- Every agent's instructions include its own name, the call chain (who is waiting
  on it), the remaining budgets, and a one-line description of each colleague.
- Before a delegation runs, `team.py` checks it:

  | Check | What happens |
  | --- | --- |
  | Asking yourself | Refused |
  | Asking anyone already in the call chain | Refused as a loop, and told to put the question in `open_questions`. This is how "asking the Boss for help" works mid-task: the Boss is normally waiting, so the question goes back to it in the report. |
  | Depth ≥ 3 (boss → specialist → specialist) | Refused: "answer with what you have" |
  | The same request (normalised) to the same colleague from the same asker | The earlier report is returned from a cache; no new run |
  | More than 6 delegations on a ticket | Refused |

- Every refusal is written to the audit trail with its reason.

**Limits for one ticket, shared by every agent on it** (`RunLimits` in
`models.py`). PydanticAI's `UsageLimits` enforces them on one usage counter that
all nested runs share.

| Limit | Value |
| --- | --- |
| Model requests, all agents together | 30 |
| Tool calls, all agents together (also counted separately for MCP) | 40 |
| Total tokens, all agents together | 150,000 |
| Output tokens per reply | 1,500 |
| Delegation depth | 3 |
| Delegations per ticket | 6 |
| Retries for an invalid tool call or output | 1 per agent |

If a limit is hit, the whole ticket stops cleanly with a `limit_reached` audit
event and a `could_not_complete` outcome. Requests and drafts already created stay
on the board for a human.

### 10.5 What was checked (2026-11-06, Problem 5)

No ticket has been run end to end yet.

1. **Approval boundary.** Tested through real MCP connections on a throwaway
   database copy; see 12.1.
2. **Delegation guards.** The real `Team` (real MCP server on a throwaway database
   copy, real guards, real audit writer) was run with each agent's model replaced
   by a scripted stand-in. The stand-ins exist only in the test script, not in the
   project, and made no API calls. The audit recorded:
   - Inventory asking the Boss back: refused as a loop.
   - Accounting asking Inventory back: refused as a loop.
   - Accounting asking Facilities at depth 3: refused for depth.
   - The Boss repeating its request to Inventory: the cached answer was returned.
   - The Boss asking itself: refused.
   - The scripted Accounting's call to `execute_approved_payment` was rejected
     inside PydanticAI as an unknown tool. It never reached the MCP server, and no
     payment row was created.
3. **Live model check.** The real Accounting agent on `gpt-6-luna` via Portkey
   was asked one read-only question about invoice 501:
   - It made one MCP call and reported correctly: 840.00, 3 days overdue, covered,
     2,560.00 left.
   - It used 2 requests and 5,725 input / 165 output tokens.
   - Its 5 audit events (`run_id run-20261106T182354Z-b3a79b`) are the first
     entries in `audit_trail.json`.

## 11. Audit trail (`backend/output/audit_trail.json`)

- **Append-only JSON array.** Each event replaces the closing `]` with
  `,<event>]`, so earlier events are never rewritten and the file stays valid JSON.
  An exclusive file lock stops writers from interleaving. A file that isn't a JSON
  array is refused, never overwritten.
- **Event types:**
  - `run_started`, `agent_started`
  - `model_step`: which tools the model asked for
  - `mcp_tool_call`, `tool_call_blocked`
  - `delegation`, `delegation_refused`
  - `agent_finished`: status and handoff reason
  - `limit_reached`, `error`, `run_finished`
- **Fields:**
  - `ts`, `run_id`, `ticket_id`, `agent`
  - `chain`: who was waiting on this agent
  - `event`, `action`
  - compact `args` and `result`
  - `reason`: why the agent stopped, handed off or was refused
  - cumulative `usage`: requests, tool calls, input and output tokens
- **Kept small and safe:**
  - Strings are cut at 240 characters (**600 from Problem 8**, so a full agent summary
    or hand-off request is readable on the dashboard; events written before then are cut
    at 240) and lists at 8 items, and nesting is limited
    to 4 levels.
  - Keys that look like secrets (`api_key`, `password`, `authorization`, …) are
    redacted.
  - Tool results are reduced to `ok` or error, the data and the database gaps.
  - The API key is never logged.

## 12. Human approval and safety

### 12.1 The approval boundary

```text
 agents (agent-mode MCP)                          human (approver-mode MCP)
 ───────────────────────                          ─────────────────────────
 Accounting: prepare_payment_request ─► payment_requests (pending_approval)
                                                      │
                                       list_pending_approvals / dashboard
                                                      ▼
                                   execute_approved_payment(id, approved_by=<human>)
                                     ├─ approver must not be an agent name
                                     ├─ request must still be pending
                                     ├─ invoice still unpaid / rent still due as prepared
                                     ├─ balance ≥ amount, else REFUSED (nothing changes)
                                     └─ one transaction: payments row, balance − amount
                                        (UPDATE … WHERE balance ≥ amount), invoice 'paid'
                                        or lease next_due + 1 month, request 'executed',
                                        ticket note
```

**Tested 2026-11-06** through real MCP stdio connections on a throwaway copy. The
project databases were unchanged.

- **Agent mode:**
  - It lists 12 tools, none of which moves money.
  - Calling `execute_approved_payment` → "Unknown tool".
  - Customer Service preparing a payment → refused (`role_not_allowed`).
  - Accounting prepares request 1 (invoice 501, 840.00) and request 2 (rent,
    2,400.00).
  - A second request for invoice 501 → refused (`duplicate`).
  - Inventory preparing a 12 × M hoodie restock → created with
    `vendor_on_hold: true`, blocked by invoice 501, and no arrival date.
  - Inventory trying to resolve a ticket → refused.
- **Approver mode:**
  - `approved_by: "accounting"` → refused (`agent_cannot_approve`).
  - A human executes request 1: balance 3,400.00 → 2,560.00, invoice 501 becomes
    `paid`, and a `payments` row is recorded with `paid_at` 2026-08-31.
  - Executing request 1 again → refused (`not_pending`).
  - With the balance set to 2,000.00, executing the 2,400.00 rent → **refused
    (`insufficient_funds`)**. The balance stayed at 2,000.00.

### 12.2 Guardrails in this build, and what a real business would add

| Area | In this build | A real business would also want |
| --- | --- | --- |
| Money | Agents can only prepare. Execution exists only in approver mode, needs a named human, re-checks the bill, refuses overdrafts and runs in one transaction. | Two-person approval above a threshold, approval limits per person, payments only to verified payee bank details, daily outflow caps, an end-of-day reconciliation |
| Purchasing | Restock requests record the vendor hold and cost at unit cost. A human decides. | Approved vendor lists, quotes or purchase orders checked against invoices, budget limits per category |
| Customers | Drafts only; nothing can be sent. Prompts forbid promising undecided discounts or dates, and mentioning internal finances. | Human review before anything is sent, tone and policy checks, privacy rules for customer data, a record of what was promised |
| Discounts | The Boss decides, using cost-floor numbers from the tools | A written discount policy with limits, and manager sign-off above it |
| Agent behaviour | Per-agent tool allowlists, role checks on the server, identity stamping, loop guards, budgets per ticket | Rate limits, alerts on unusual behaviour, regular review of audit samples, testing on red-team tickets before prompt changes go live |
| Data | MCP-only access; the original database is never opened; the audit log is compact and redacted | Backups, access control per role, retention rules for logs, separate production and test data |

## 13. Expected ticket plans (`backend/output/desk_tickets.html`)

- **The page.** A standalone page with no build step. Tabs (switched by URL hash):
  Ticket 101, Ticket 102, Ticket 103, Cash and Reflection. Each ticket tab has:
  - the ticket's facts from the database;
  - an **Expected** section: who the Boss calls first and why, a step-by-step
    table of agent, MCP tools, purpose and expected result, the expected outcome,
    and what to watch for;
  - a dashed **Actual** section, left empty.

  Cash and Reflection are placeholders.
- **When the predictions were written.** 2026-11-06, before any agent ran a ticket.
- **Lean routing.** The predictions use the smallest team. The user chose this
  after reviewing a first proposal that used 8 hand-offs (AI_prompts.md 6.1–6.3).

  | Ticket | Expected path | Hand-offs | Not involved |
  | --- | --- | --- | --- |
  | 101 | Boss → Accounting (invoice 501 hold, lead time, cash, payment request), then Boss → Customer Service (draft) | 2 | Inventory, Facilities |
  | 102 | Boss → Accounting (lease check, cash, rent payment request) | 1 | Facilities, Inventory, Customer Service |
  | 103 | Boss → Accounting (stock and shortfall, cost floor and margins, vendor hold, restock cost against cash), Boss decides the discount, Boss → Customer Service (draft) | 2 | Inventory, Facilities |

- **Prompts changed to match.** To keep the comparison between Expected and Actual
  fair, `prompts/boss.md` and `prompts/accounting.md` were changed so the agents are
  told to work this way (see the note in 10.3).

## 14. Backend API (`backend/main.py`)

### 14.1 How it fits together

```text
React dashboard ──HTTP/JSON──► FastAPI (backend/main.py, :8000)
                                 ├─ reads + human decisions ─► MCP server, --approver mode (human_mcp.py; never given to agents)
                                 ├─ POST …/runs ─► Team.handle_ticket() in a background task
                                 │                    └─ agents ─► MCP server, agent mode (mcp_connection.py)
                                 ├─ GET /api/activity ◄─ audit_trail.json (append-only, read with a shared lock)
                                 └─ POST /api/admin/reset ─► copies data/campus_customs.db over the working copy
```

- **One interface.** The dashboard never calls MCP and never sees table names. All
  data comes from the API's response models (`backend/models.py`, "API shapes").
- **Errors** always come back as `{"error": {"code", "message", "details"}}`:

  | Status | Meaning |
  | --- | --- |
  | 404 | Not found |
  | 409 | Busy or not allowed now, including `insufficient_funds` |
  | 422 | Invalid request |
  | 500 | Internal error |
  | 503 | MCP server or configuration unavailable |

  MCP error types are mapped onto these.
- **Live updates by polling.** The dashboard calls
  `GET /api/activity?run_id=…&since=N` every 1–2 seconds and receives only new
  events, plus `next_since` and the run's status.
  - **Why polling:** runs last tens of seconds, the audit trail is already the
    record, polling works across restarts and dropped connections, and it can be
    tested with `curl`.
  - **Alternatives:** Server-Sent Events would save about a second of latency but
    need an event bus and reconnect logic. WebSockets add two-way plumbing that
    nothing here needs.
- **One writer at a time.** An agent run, a human decision and a database reset
  all take the same in-process lock. If it is held, the request gets
  `409 busy`, with what is holding it. That means:
  - reset can't run during an agent run;
  - an approval can't run during an agent run;
  - two runs can't overlap.

  The lock is a flag set without an `await` between the check and the set, on
  uvicorn's single event loop.
- **Approval lifecycle** (`state` on every payment or purchase request):

  | State | Meaning |
  | --- | --- |
  | `proposed` | An agent created it and that ticket's run is still going |
  | `awaiting_approval` | The run has finished; waiting for a human |
  | `executed` | A payment a human approved; the money moved |
  | `approved` | A purchase a human approved; recorded only, no vendor contacted |
  | `rejected` | A human rejected it, with a reason |
  | `failed` | A human approved a payment but execution was refused (bill changed or not enough cash); no money moved |

- **Money only moves on a human's explicit approve.**
  - Approving a payment calls `execute_approved_payment` on the approver-mode
    server.
  - That tool re-reads the balance inside the payment transaction and refuses if it
    is below the amount.
  - The balance is reduced with `UPDATE … WHERE balance >= amount`.
  - The API also refuses agent names as `decided_by`.
- **Reset safety.**
  - It needs the body `{"confirm": "RESET"}`, and takes the writer lock.
  - It checks that the source is `data/campus_customs.db` and the target is
    `data/campus_customs_new.db`, and that they are different files.
  - It copies the original, which is only read, to a temporary file in `data/`,
    verifies its SHA-256 matches the original, keeps the working copy's
    permissions, and atomically swaps it in with `os.replace`.
  - The audit trail isn't touched.
- **Runs are kept in memory.** The run registry resets when the API restarts. Every
  event stays in the audit trail.
- **CORS.** Allowed origins come from `CORS_ORIGINS` (default
  `http://localhost:5173` and `http://127.0.0.1:5173`). Methods are GET and POST;
  the only allowed header is `Content-Type`.

### 14.2 Routes (one line each)

| Method and URL | What it does, and what it touches |
| --- | --- |
| `GET /api/health` | Readiness: the configured model (only `gpt-6-luna` passes), whether a Portkey key is set, whether the MCP server answers, and what is running. |
| `GET /api/tickets` | All tickets, open or resolved, with `is_resolved`, pending-request and draft counts, and the latest run. MCP `list_ticket_board` (tickets, workflow tables). |
| `GET /api/tickets/{id}` | One ticket: linked invoice, lease and stock row, notes, drafts, approval requests with their states, and its runs. MCP `get_ticket_details` and `list_pending_approvals`. |
| `POST /api/tickets/{id}/runs` | Starts the agent team on the ticket in the background and returns 202 with `run_id` and `activity_url`. Returns 404 for an unknown ticket, 409 if resolved or busy, 503 if not configured. Calls `Team.handle_ticket`; the agents use their own agent-mode MCP connection. |
| `GET /api/runs?ticket_id=` | Runs since the API started, newest first, with status (`running`, `completed`, `failed`) and the Boss's `TicketOutcome`. In memory only. |
| `GET /api/runs/{run_id}` | One run's status and outcome. |
| `GET /api/activity?since=&run_id=&ticket_id=&limit=` | Audit-trail events after a cursor. Each has a one-line `summary` ("accounting used get_invoice_and_vendor_status (ok)"), the agent, the call chain, compact arguments and result, the reason and usage. Also returns `next_since`, the run and `busy`. Reads `audit_trail.json`. |
| `GET /api/approvals?state=&ticket_id=` | All payment and purchase requests with their lifecycle `state`. MCP `list_pending_approvals(include_decided=true)`. |
| `POST /api/approvals/{payment\|purchase}/{id}/decision` | A human's `{decision: approve\|reject, decided_by, note}`. Approving a payment executes it now (cash re-checked; refusal → 409 and `failed`). Rejecting needs a note. Approving a purchase records it. Uses the approver-mode tools and writes a `human_decision` audit event. |
| `GET /api/cash` | The checking balance from cash_accounts, as-of date, bills on record, the balance after all of them, and recent payments with approvers. MCP `get_cash_position`. |
| `POST /api/admin/reset` | Body `{"confirm":"RESET"}`. Replaces the working copy with a fresh copy of the original (409 if busy) and writes a `database_reset` audit event. Returns whether the copy matches the original, the balance and the open-ticket count. |

### 14.3 Starting it (for the eventual root README)

1. Set up the environment, from `hw5/`:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

2. **Key.** Put `PORTKEY_API_KEY` in `hw5/.env` (copy `.env.example`), or export
   it in the shell. `config.py` reads `hw5/.env`.
3. **Working copy.** Create it once with
   `cp data/campus_customs.db data/campus_customs_new.db`. After that, use
   `POST /api/admin/reset`.
4. **Start**, from `hw5/backend/` with the virtual environment active:

   ```bash
   source ../.venv/bin/activate
   uvicorn main:app --reload --port 8000
   ```

   The API starts the MCP server itself. Nothing else needs to be running.
5. **`--reload` only watches `.py` files.** Editing a `.py` file during a run
   restarts the API and cancels that run.

### 14.4 Tests (2026-11-06)

**A. Live server** (`uvicorn main:app --reload --port 8000`, started from `backend/`):

- `GET /api/health` → ok, model `gpt-6-luna`, MCP connected.
- `GET /api/tickets` → 101, 102 and 103 open.
- `GET /api/tickets/101` → invoice 501 and the stock row with 0 S.
- Errors:
  - `/api/tickets/999` → 404, listing the existing ids.
  - `/api/tickets/abc` → 422.
  - `?state=bogus` → 422.
  - `kind=refund` → 422.
  - `decided_by: "accounting"` → 422.
  - A reset with no `confirm` → 422.
- `GET /api/cash` → checking 3,400.00, 160.00 after both bills.
- CORS: `http://localhost:5173` allowed; another origin gets no allow-origin
  header.
- A live reset → 200, copy matches the original, 3 open tickets, 3,400.00.

**B. Unplanned real run.**

- **What happened.** `POST /api/tickets/101/runs` was expected to return 503,
  because there's no `hw5/.env`. But `PORTKEY_API_KEY` is exported in the user's
  shell, so the API started a **real `gpt-6-luna` run on ticket 101**
  (`run-20261106T191329Z-215534`). It finished in about 19 seconds and used
  6 requests and 16,616 input / 928 output tokens.
- **What it did.** Boss → Accounting, as in the lean plan. Accounting called
  `get_stock_and_price_quote`, `get_invoice_and_vendor_status` and
  `list_vendors_with_status`.
- **How it differed from Expected.**
  - No payment request was prepared.
  - No Customer Service draft was written.
  - The Boss set the ticket to `in_progress` and returned `needs_human_input`,
    citing the unconfirmed vendor-to-product link.
- **Records.** The events are in `audit_trail.json` (entries 5–22). Its database
  changes were removed by the resets that followed. `desk_tickets.html` was not
  filled in from this run.

**C. Scripted in-process test.**

- **Setup.** The real routes, MCP server and working database were used through
  httpx's ASGI transport. Only the models were scripted stand-ins, defined in the
  test file. No API calls were made, and audit events went to a throwaway file.
- **Concurrency.** `POST /api/tickets/101/runs` → 202. A second run → 409 busy. A
  reset during the run → 409 busy.
- **Polling.** The activity cursor returned only new events (14 events over
  8 polls). Mid-run, the invoice 501 request showed as `proposed`; after the run,
  `awaiting_approval`.
- **Approvals:**
  - Payment 1 (840.00) → `executed`, balance 3,400.00 → 2,560.00, payment row
    with approver.
  - Approving it again → 409 `not_awaiting_approval`.
  - With the balance set to 2,000.00 by a test fixture, approving the 2,400.00 rent
    → 409 `insufficient_funds`. The state became `failed`, the balance stayed
    2,000.00 and no payment row was created.
  - Approving the failed request → 409.
  - Rejecting the purchase with no note → 422.
  - Approving the purchase → `approved` ("no vendor was contacted and no money
    moved").
- **Reset.** → 200. Balance 3,400.00, no requests, all tickets open.
- **Bug found and fixed.** The first pass showed Accounting couldn't call
  `prepare_purchase_request` (it wasn't in its allowlist). After the fix, the
  rerun passed every step.

**D. Databases.** After the final reset, all nine shop tables in the working copy
match the original, and the original's SHA-1 is unchanged (`f447ca6a…`). The reset
now keeps the working copy's file permissions; the first version left it
owner-only, which was then fixed.

**E. Clean-up.** The API was stopped and port 8000 is free. The one remaining
`mcp_server/server.py` process belongs to this Claude Code session, which started
it from `mcp_servers/.mcp.json`, not to the API.

## 15. Dashboard (`frontend/`)

- **Stack.** React 19, Vite 8 and TypeScript 7. Fonts are bundled through
  `@fontsource` (Fraunces, Space Grotesk, JetBrains Mono). The design rationale is
  in `backend/output/design.md`.
- **Data.** Only through the backend API: `src/api.ts` calls the routes in section
  14.2 at `VITE_API_BASE` (default `http://localhost:8000`). There is no mock data,
  no MCP and no database access.
- **Polling:**
  - `/api/activity`, with its cursor: every 1.2 s while the selected ticket is
    running, every 5 s otherwise;
  - tickets: every 1.5 s during a run, every 5 s otherwise;
  - approvals: every 2–4 s;
  - cash: every 5 s;
  - health: every 4 s.

  Everything refreshes as soon as a run finishes or a decision is made.
- **Start it.** `cd frontend && npm install && npm run dev`, then open
  http://localhost:5173. Port 5173 is fixed (`strictPort`) to match the backend's
  CORS setting.

### 15.1 Checked on 2026-11-06

- **Build.** `tsc --noEmit` passes and a production build succeeds.
- **CORS.** `GET /api/tickets` from origin `http://localhost:5173` returns
  `access-control-allow-origin: http://localhost:5173`.
- **Real data.** With the API and `npm run dev` running, the dashboard showed the
  three tickets, the 3,400.00 balance with 160.00 left after the bills on record,
  and ticket 101's history.
- **A real run through the dashboard.** Clicking **Send to the team** on ticket 102
  started a real `gpt-6-luna` run (`run-20261106T192621Z-d9d50f`). The run took 8 requests and 22,997
  input / 728 output tokens.
  - The dashboard updated live. The ticket was stamped WORKING, the Boss showed
    "Waiting on Accounting" and Accounting lit up.
  - A Boss → Accounting hand-off card quoted the request, and Accounting's tool
    lines (`get_rent_payment_status`, `list_pending_approvals`,
    `prepare_payment_request`) were indented under it.
  - It followed the Expected lean plan exactly. The outcome was
    `awaiting_approval`, with payment request 1 for 2,400.00 shown as a
    **"Not paid · needs your signature"** slip.
  - The till kept showing 3,400.00 in checking, with 2,400.00 listed separately as
    "waiting for signature (not paid)".
- **Approval.** **Not done by the assistant.** Its click on "Approve & pay" was
  blocked by the session's permission system (no self-approval of payments).
  Payment request 1 is left `awaiting_approval` for the user to decide. The API
  route behind it was tested in section 14.4.
- **Disconnection.** Stopping the API brought up the offline banner. The last data
  stayed on screen and the actions were disabled. Restarting the API cleared the
  banner and restored the log automatically.
  - This test found a bug: the shift log cleared itself when the run ended while
    the API was offline. It was fixed so the feed resets only when you switch
    tickets.
- **Two other fixes from viewing the page:**
  - Switching tickets briefly showed the previous ticket's facts.
  - The staff strip clipped agent names at 1440 px.
- **Phone width.** At 375 px the layout stacks in workflow order (rail, floor,
  till).
- **Console.** No errors except the connection-refused messages from the
  deliberate offline test.

## 16. The finished system (current as of Problem 9)

This section describes the system as it now stands. Earlier sections record how
it got here; where they differ, this one is current.

### 16.1 Databases and tables

- **Original:** `data/campus_customs.db`. Never opened by any code path. Its
  SHA-1 is `f447ca6a…`, unchanged throughout.
- **Working copy:** `data/campus_customs_new.db`, used only through the MCP
  server. Reset with `POST /api/admin/reset` or the dashboard's "Start fresh".
- **Shop tables** (from the original; section 4): `desk`, `tickets`, `inventory`,
  `pricing`, `vendors`, `invoices`, `leases`, `cash_accounts`, `payments`.
- **Workflow tables** (created by the MCP server; section 9.2):

  | Table | Holds |
  | --- | --- |
  | `payment_requests` | Status `pending_approval`, `executed`, `rejected` or `failed` |
  | `purchase_requests` | Status `pending_approval`, `approved` or `rejected` |
  | `message_drafts` | Always `draft` |
  | `ticket_notes` | Agent notes, plus `human:<name>` notes and decisions |

- **Values this system writes into shop tables:**
  - `invoices.status = 'paid'`;
  - `leases.next_due` moved forward one month;
  - `payments` rows (kind `invoice` or `rent`, `approved_by` a human);
  - `cash_accounts.balance` lowered only by an executed payment;
  - `tickets.status`: `open`, `in_progress`, `awaiting_approval` or `resolved`.

### 16.2 MCP server: 17 tools

`mcp_server/server.py`, built on FastMCP, uses stdio.

- **Agent mode (13)** is what `mcp.json` starts, for both the agents and Claude
  Code:
  - **Read (9):** `list_ticket_board`, `get_ticket_details`,
    `get_invoice_and_vendor_status`, `get_rent_payment_status`,
    `get_stock_and_price_quote`, `list_vendors_with_status`,
    `check_cash_for_amount`, `get_cash_position`, `list_pending_approvals`.
  - **Prepare (4):** `prepare_payment_request` (accounting),
    `prepare_purchase_request` (inventory, accounting), `save_draft_message`
    (any agent), `update_ticket_status` (boss).
- **Approver mode (`--approver`, used only by `backend/human_mcp.py`)** adds 4:
  - `execute_approved_payment`
  - `reject_payment_request`
  - `decide_purchase_request`
  - `add_human_note`

  All four refuse agent names as the human.
- **Tables per tool:** see section 9.3. In addition:
  - `get_cash_position` reads cash_accounts, invoices, vendors, leases, payments
    and desk.
  - `add_human_note` writes ticket_notes and reads tickets and desk.

### 16.3 The five agents (PydanticAI, `gpt-6-luna` via Portkey, one model object)

| Agent | Role | MCP allowlist |
| --- | --- | --- |
| Boss | Owns the ticket and uses the smallest team. Follows `human:` notes. Sets status and returns a `TicketOutcome`. | list_ticket_board, get_ticket_details, list_pending_approvals, update_ticket_status |
| Accounting | Money **and** availability facts. The only agent that prepares payments; can also prepare purchases. | get_ticket_details, get_invoice_and_vendor_status, get_rent_payment_status, check_cash_for_amount, get_stock_and_price_quote, list_vendors_with_status, list_pending_approvals, prepare_payment_request, prepare_purchase_request |
| Inventory | Judgement on stock and restock | get_ticket_details, get_stock_and_price_quote, list_vendors_with_status, get_invoice_and_vendor_status, check_cash_for_amount, prepare_purchase_request |
| Facilities | Lease and landlord questions the rent tool can't answer | get_ticket_details, get_rent_payment_status, list_pending_approvals, save_draft_message |
| Customer Service | Customer reply drafts, never sent | get_ticket_details, get_stock_and_price_quote, save_draft_message |

**Delegation.** Every agent has `ask_colleague`. Requests are refused when they
would loop: asking yourself, asking anyone in the call chain, going past depth 3,
or going past 6 hand-offs per ticket. A repeated request gets the cached answer.

**Budgets per ticket:** 30 model requests, 40 tool calls, 150k tokens, and 1,500
output tokens per reply (section 10.4).

### 16.4 API routes (`backend/main.py`, port 8000)

All the routes in section 14.2, plus:

| Method and URL | What it does, and what it touches |
| --- | --- |
| `POST /api/tickets/{id}/notes` | Body `{author, note}`. A human's decision or instruction on a ticket; agent names are refused. Calls the approver-mode `add_human_note`, writing ticket_notes, and writes a `human_decision` audit event. The Boss reads it on the next run. |

Other API changes in Problem 9:

- On startup, the API rebuilds its run history from `audit_trail.json`, so the
  dashboard keeps each ticket's wrap-up after a restart.
- `run_finished` events now carry the Boss's full `TicketOutcome`.

### 16.5 Dashboard (`frontend/`, port 5173)

The layout is a rail, the floor and the till (`design.md`).

- **Ticket rail:** receipts with status stamps.
- **The floor:**
  - the staff strip;
  - the Boss's wrap-up;
  - **"Notes from you to the team"**, a new box that needs a name under "Signing
    as";
  - drafts;
  - the shift log.
- **The till:** the real balance, kept apart from amounts awaiting approval.
- **Signature slips:** these are the only way money moves, and approving takes two
  steps.

**Fixed in Problem 9:** a ticket stayed stamped "Working" after its run finished.
The dashboard now tracks the started run's ID and clears the flag as soon as the
server reports that run finished.

### 16.6 Safety measures

- **Money moves only on a named human's explicit approval.**
  - It goes through a separate approver-mode MCP connection that no agent can
    reach.
  - Cash is re-checked inside the payment transaction, and the balance update is
    guarded (`UPDATE … WHERE balance >= amount`).
  - Overdrafts are refused and recorded as `failed`.
- **Preparing is separate from executing.** The amount and payee come from the
  database, duplicates are refused, and a stale request is refused if the bill has
  changed.
- **Role checks on the server, identity stamping, and per-agent allowlists.** The
  human-only tools are blocked from every agent's allowlist when the code loads.
- **Messages are drafts only.** There is no send tool, and the drafts table can
  only hold `draft`.
- **Data access:**
  - MCP-only, with the working copy only.
  - The reset never writes to the original, verifies the copy and swaps it in
    atomically.
  - One writer at a time: runs, decisions, notes and resets are serialised.
- **Budgets and loop guards on every ticket,** and an append-only, redacted audit
  trail.

## 17. The full run (Problem 9, 2026-11-06)

### 17.1 Reset and starting point

- **No activity.** Before the reset, `GET /api/health` showed `busy: null`.
- **Reset.** `POST /api/admin/reset` returned `working_copy_matches_original: true`.
  All nine shop tables were identical to the original, and the workflow tables
  were empty.
- **Starting balance.** Read directly from `cash_accounts`: **checking 3,400.00**
  (as of 2026-08-31). Tickets 101–103 were open, with no payments.

### 17.2 The runs

All runs were started from the dashboard.

| Ticket | Run | Path | MCP tools | Result | Requests, tokens |
| --- | --- | --- | --- | --- | --- |
| 101 | `run-20261106T193433Z-7c7610` | Boss → Accounting; Boss → Customer Service | Boss: get_ticket_details ×2, update_ticket_status ×2. Accounting: get_stock_and_price_quote, get_invoice_and_vendor_status, get_ticket_details. CS: get_ticket_details, get_stock_and_price_quote, save_draft_message | **resolved**. Draft 1 to Tauhid Zaman offers sizes M, L or XL. No payment request for invoice 501. | 13, 37,804 / 1,649 |
| 102 | `run-20261106T193544Z-727263` | Boss → Accounting | Boss: get_ticket_details, update_ticket_status. Accounting: get_rent_payment_status, list_pending_approvals, prepare_payment_request | **awaiting_approval**. Payment request 1 for 2,400.00 rent. | 8, 22,997 / 728 (see note) |
| 103 (1st) | `run-20261106T193606Z-847db7` | Boss → Accounting | Boss: get_ticket_details, update_ticket_status. Accounting: get_stock_and_price_quote, list_vendors_with_status, get_ticket_details | `needs_human_input`. The Boss didn't set the discount. | 6, 16,904 / 1,109 |
| 103 (2nd) | `run-20261106T194212Z-e9b5ae` | Boss → Accounting; Boss → Customer Service | Boss: get_ticket_details, update_ticket_status. Accounting: list_vendors_with_status, get_stock_and_price_quote, get_ticket_details. CS: get_ticket_details, get_stock_and_price_quote, save_draft_message | **resolved**. The Boss set 10% off ($52.20 each, $1,044 for 20). Draft 2 to the Yale AI Club. | 11, 31,401 / 1,515 |

**Inventory and Facilities were never involved,** which matches the lean plan.
**No delegations were refused.**

**Note on 102.** The run finished in about 4 seconds with token usage identical to
the Problem 8 demo run. Portkey most likely returned cached model responses for an
identical prompt. The MCP calls were executed for real.

### 17.3 Human decisions

- **102:** asked to approve payment request 1, the user chose **"Leave it
  pending"**. It is not approved or rejected, and no money moved.
- **103:** after the first run asked for a human decision, the user chose to add a
  human-note feature. Asked for the decision, they had **no preference**. The note
  posted in their name (`human:Dan Langfitt`) told the Boss to decide, and the
  second run did.

### 17.4 Verified final state (working database, read directly)

- **Tickets:** 101 `resolved`, 102 `awaiting_approval`, 103 `resolved`.
- **Requests:** `payment_requests` has one row (rent, 2,400.00,
  `pending_approval`). `purchase_requests` is empty.
- **Drafts:** `message_drafts` has drafts 1 (101) and 2 (103), both `draft`.
- **Cash:** `payments` has 0 rows. Start 3,400.00 − paid 0.00 = 3,400.00, which
  equals `cash_accounts.checking` 3,400.00. ✓
- **Unchanged records:** invoice 501 is still `open`, and lease 1 is still due
  2026-09-02.
- **Audit trail:** 146 events. The 44 events that existed before the run are
  byte-for-byte unchanged, and every Problem 9 event was appended after them. The
  scripted test runs from Problems 5 and 7 wrote to throwaway files, never to this
  trail.

### 17.5 Outputs

All generated from the audit trail and the database, not typed by hand:

- `desk_tickets.html`: the Actual sections, the Cash tab and the reconciliation.
- `resolved_tickets.json`: the structured record.
- `resolved_board.html`: six real screenshots of the React dashboard taken from
  the browser pane after the runs, embedded in the page.
