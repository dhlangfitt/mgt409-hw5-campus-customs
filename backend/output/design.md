# Campus Customs Ops Desk — Design Notes

The dashboard lives in `frontend/` (React + Vite + TypeScript) and talks only to the
FastAPI backend at `http://localhost:8000`. These notes explain the creative
direction and the reasoning behind each part of the screen.

## 1. Creative direction: the back counter after closing

Most agent dashboards look like a log viewer. I wanted the opposite: the room a
small shop's manager actually sits in at the end of the day, with the shutters
down, one neon sign still on, receipts clipped to a rail, and the till within
reach. Three things follow from that:

- **Everything is a familiar shop object.** Tickets are paper receipts. The agents
  are staff with name badges. The cash is a till. A payment needs a **signature
  slip**. Someone who has worked a till already knows what each part of the screen
  is for, without reading a legend.
- **One loud colour, used sparingly.** The near-black "counter" and a single
  neon pink (the workspace's black-and-pink house style) make pink mean *pay
  attention*: the shop sign, the selected ticket, the "Send to the team" button,
  and above all a slip waiting for a signature. If pink were everywhere it would
  stop meaning anything, so it isn't.
- **Paper versus screen.** The tickets are the only light-coloured objects on the
  page: warm off-white paper with dark ink. That makes the rail readable at a
  glance and makes it obvious that tickets are *things to act on*. The work
  happening *about* them sits on the dark counter.

**Typography carries the mood:**

- **Fraunces**, a soft, slightly old-fashioned serif, for the shop sign and ticket
  titles. It feels like signage, not software.
- **Space Grotesk** for everything you read.
- **JetBrains Mono** for anything that is a number or a machine name (money, dates,
  tool names, run IDs).

The rule for mono is simple: if it's a figure you'd check or a name you'd search
for, it's in mono. The fonts are bundled with the app (`@fontsource`), so the
desk looks the same with no internet connection.

## 2. Layout: rail, floor, till

```text
┌───────────────────────── shop sign · shop date · connection · checking balance ─────────────────────────┐
│ TICKET RAIL          │ THE FLOOR                                             │ THE TILL                  │
│ paper receipts       │ ticket header + facts            [stamp] [Send ▶]     │ In checking now  $3,400   │
│  #101 OPEN           │ staff strip: 5 name badges, lit when involved          │ waiting for signature     │
│  #102 NEEDS YOU      │ Boss's wrap-up (when a run ends)                       │ bills on record / paid    │
│  #103 OPEN           │ drafts on the board (never sent)                       │───────────────────────────│
│                      │ SHIFT LOG: hand-offs, tool use, what each agent said   │ NEEDS YOUR SIGNATURE (1)  │
│                      │                                                       │ [signature slips]         │
└──────────────────────┴───────────────────────────────────────────────────────┴───────────────────────────┘
```

- **The left-to-right order follows the workflow.** Pick a ticket (left), watch
  the team work it (centre), then sign for anything that costs money (right).
- **The till and the signature slips sit together on the right.** The question
  "can we afford this?" and the button that spends the money should be in view
  together.
- **The balance also appears in the top bar** ("Checking $3,400.00"). It stays
  visible when the right column is pushed below the floor on smaller screens.
- **Responsive.** On narrower screens the till column moves under the floor. On a
  phone everything stacks in workflow order. The staff strip wraps instead of
  squeezing names until they're unreadable; an early version at 1440 px clipped
  "Accounting" to "Accou…", which is why it now wraps.

## 3. The agents' visual identities

Each agent has one hue, one glyph and a role title, like a staff name badge. The
same badge appears everywhere that agent appears: staff strip, shift log,
hand-offs, signature slips and the footer. You learn the five once, then
recognise them by colour from across the screen.

| Agent | Badge | Hue | Role title | Why |
| --- | --- | --- | --- | --- |
| Boss | ★ | neon pink `#ff4fa3` | Shift lead | The Boss owns the ticket, so it wears the shop's own colour |
| Accounting | $ | amber `#f5b83d` | The ledger | Gold for money, and it sits next to the till's figures without clashing |
| Inventory | ▦ | teal `#35d0b4` | Stockroom | Boxes on shelves; a cool colour for a factual, counting job |
| Facilities | ⌂ | violet `#a98bff` | Premises | The building itself; a calm colour for the quietest role |
| Customer Service | ❝ | sky blue `#5fb2ff` | Front counter | A quotation mark, because their output is words to a customer |
| A human | ✎ | mint | You | A pen for the person who signs |

**Readability rules:**

- The hues are only ever used for the badge disc, its border, the agent's name
  and thin accent lines. Body text is always light grey on near-black, never
  coloured text on a coloured background.
- The glyph means the badges still work for anyone who can't tell two of the
  colours apart.

**Staff strip states.** Each card shows:

- **On shift:** the run is going, but this agent hasn't been called yet.
- **Working:** the card glows in the agent's colour, with a pulsing dot and its
  latest action ("checked the rent").
- **Waiting:** a dashed border, plus "waiting on Accounting".
- **Reported:** the status from the agent's report.
- **Not needed:** the card dims.

Because of the lean routing (Boss plus usually one specialist), a dimmed card is
information: you can see straight away that the Boss didn't send in the whole team.

## 4. Activity and delegation: the shift log

The shift log reads like the conversation on the shop floor, not a server log.
Each audit event becomes one of a few shapes:

- **Hand-off cards.** "Boss ⟶ Accounting" with both badges and the actual request
  quoted underneath. Delegation is the most interesting thing a multi-agent team
  does, so it gets the most visual weight.
- **Tool lines.** A plain-English verb ("checked the rent", "prepared a payment
  request") followed by a small mono chip with the real tool name and a ✓ or ✗.
  The verb is for reading. The chip is for the curious: clicking it expands the
  exact arguments and result.
- **Speech bubbles.** When an agent reports back, its summary appears as a
  message with the agent's colour along the top, its status pill (for example
  "needs human approval") and its handing-back reason.
- **Indentation for depth.** Work done *inside* a delegation is indented under the
  hand-off. So "Accounting checked the rent, checked approvals, prepared a payment
  request" visibly belongs to the Boss's request.
- **Dividers** mark "Run started" and "Run finished" with times. Activity that
  wasn't part of a full ticket run (such as the Problem 5 wiring check) is labelled
  "Earlier activity" rather than passed off as a run.
- **Noise removed.** Internal "model step" events and the duplicate start event of
  a delegated agent are hidden, because the hand-off card and the tool lines say
  the same thing more clearly.
- **While a run is going,** a "the team is working…" line with animated dots sits
  at the bottom, and the log scrolls itself.

**Updates by polling** (see harness.md section 14). The log asks for new events
every 1.2 s while the selected ticket is running, and every 5 s otherwise, using
the API's cursor so only new lines arrive. Tickets, approvals and cash refresh on
their own timers, faster during a run, and immediately when a run ends or after
any decision.

## 5. Ticket status, resolution and summaries

- **Rubber stamps.** Each receipt carries a slightly tilted stamp:
  - OPEN (grey)
  - WORKING (pulsing pink)
  - NEEDS YOU (pink on a pink wash)
  - IN PROGRESS (amber)
  - RESOLVED (green)

  It's the kind of mark a person would put on a paper ticket, and the colour plus
  the word means it never depends on colour alone.
- **Chips on the receipt.** "✎ 1 to sign" and "✉ 2 drafts" mean you can see which
  ticket needs you without opening it.
- **The Boss's wrap-up.** When a run ends, a card appears above the shift log with:
  - the final status;
  - the Boss's summary;
  - the badges of the agents involved;
  - the decisions it made;
  - a "For you" list of next steps.

  A **resolved** ticket gets a green edge and wash, and its summary is also
  printed on the receipt in the rail. You can read what happened to every resolved
  ticket without clicking.
- **Drafts are labelled "draft · not sent".** The dashboard never implies a
  customer was contacted.

## 6. Money: preparing is not paying

This was the most important design constraint. The rule: **money is shown as
having moved only when the backend says a payment was executed.** Everything else
is visibly a request.

- **"In checking now".** The till's large figure is the actual balance from
  `cash_accounts`, with its shop date. It is never adjusted for pending requests.
- **Separate lines underneath:**
  - "Waiting for signature *(not paid)*": total and count;
  - "If every bill on record were paid": shown in red if it would go negative.
- **Signature slips** are the only place money can be spent. Each slip's state has
  its own wording and look:

  | State | What the slip says and looks like |
  | --- | --- |
  | Being prepared | Dashed pink outline. The team is still working; buttons disabled. |
  | **Not paid · needs your signature** | A bright pink frame and glow, a pink amount, and the line "No money has left the account. It moves only if you approve." |
  | Paid | Green edge, "$X left the account · payment #N · signed by …" |
  | Approved · recorded | For purchases: nothing ordered, no money moved |
  | Rejected · not paid | Struck-through amount, with the reason |
  | Refused · not paid | Red edge, struck-through amount, with the backend's reason (for example, not enough cash) |

- **Signing is deliberate.**
  - You must enter your name under "Signing as". It's saved in the browser, and
    the backend refuses agent names.
  - Approving a payment takes two steps: "Approve & pay $2,400.00", then a
    confirmation ("Pay $2,400.00 from checking now? The balance is re-checked at the
    moment of payment.").
  - Rejecting requires a reason.
- **After a real payment,** the till's balance flashes green as it changes, and
  the payment appears under "Paid out" with who signed it.

## 7. Loading, errors, empty states and disconnection

- **Loading.** Skeleton shapes (receipt-shaped on the rail, line-shaped in the
  log) instead of spinners, so the layout doesn't jump.
- **Empty states speak in the shop's voice.**
  - Shift log: "Quiet on the floor. Nobody has worked this ticket yet…"
  - Signature slips: "Nothing waiting for a signature… nothing is paid until you
    approve it."
- **Backend offline.** A red banner names the URL it can't reach and gives the
  exact command to start the backend. The connection light turns red and pulses.
  - The last data received stays on screen, slightly desaturated, so you don't lose
    context.
  - Every action that would change something is disabled with a reason.
  - When the backend comes back, everything reconnects by itself.
  - Tested: stopping the API showed the banner. Restarting it cleared the banner
    and restored the log within one polling cycle.
- **Degraded backend.** An amber banner appears if the API is up but its MCP server
  isn't answering.
- **Action errors appear where the action was taken.** A failed start shows under
  the button; a refused payment shows on its slip. Each uses the backend's own
  message (for example "Busy: agent run … on ticket 101").
- **Accessibility.**
  - The log is an `aria-live` region.
  - The rail is a listbox.
  - Focus outlines are visible.
  - Animations stop under `prefers-reduced-motion`.

## 8. Implementation notes

- **Files:**
  - `frontend/src/api.ts`: the typed client for the real routes, configured by
    `VITE_API_BASE` (default `http://localhost:8000`). There is no mock data.
  - `types.ts`: mirrors `backend/models.py`.
  - `agents.ts`: the identities.
  - `usePoll.ts`: polling that keeps the last good data.
  - `components/`: the rail, staff strip, shift log, signature slips and till.
- **CORS checked.** The backend answers `Access-Control-Allow-Origin:
  http://localhost:5173` for requests from the Vite origin.
- **Start it:** `cd frontend && npm install && npm run dev`, then open
  http://localhost:5173. Vite is pinned to port 5173 (`strictPort`) to match the
  backend's CORS setting.
