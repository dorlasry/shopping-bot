# shopping-bot

A Hebrew shopping-list WhatsApp bot for couples & families. Send the bot a
message like `תביא חלב וגבינה` and it adds the items to a shared list. Your
partner can pull up the list in their own chat and tap items to mark them
bought.

Built with **FastAPI + pywa + Claude + SQLAlchemy**.

## How it works

- Each person chats with the bot 1:1 (WhatsApp Cloud API has no group support).
- The list lives **server-side, shared per family** — both partners see the same list.
- Free-text Hebrew is parsed by **Claude** into structured intents (add / remove / view / clear).
- "View & mark bought" uses a WhatsApp **interactive list message**: tap a row to mark it.
- Incoming events go through a **message queue** (producer/worker split), so the
  webhook ACKs Meta instantly and the slow work (Claude + DB) happens on a worker.

```
                  enqueue                      dequeue
WhatsApp ─▶ FastAPI + pywa ─▶ [ message queue ] ─▶ worker ─┬─▶ parser (Claude)
            (producer, ACK fast)   Redis / memory          ├─▶ lists (logic)
                                                           ├─▶ repository ─▶ DB
                                                           └─▶ send reply (pywa)
```

The queue sits behind a `MessageQueue` interface (`app/queue/base.py`) with two
implementations — **Redis** (production) and **in-memory** (zero-dependency local
mode). Swapping to SQS/RabbitMQ later means adding one implementation and one line
in `app/queue/factory.py`; no handler or business-logic changes.

## Project layout

```
app/
  main.py              FastAPI app + pywa client + handler registration
  config.py            Pydantic settings (reads .env)
  logging_config.py
  domain/
    models.py          SQLAlchemy: Family, User, ShoppingList, Item
    schemas.py         Pydantic: ParsedIntent (the parser's output)
  db/
    session.py         engine + session factory
    repository.py      all DB reads/writes
  services/
    parser.py          Claude: Hebrew text -> ParsedIntent
    lists.py           business logic, orchestrates parser + repository
    whatsapp.py        builds pywa interactive messages from items
  queue/
    base.py            MessageQueue interface + IncomingJob payload
    redis_queue.py     Redis implementation (production)
    memory.py          in-memory implementation (local/tests)
    factory.py         picks the backend from config
  processing.py        consumer-side work: process_job(wa, job)
  worker.py            the consumer loop (standalone + in-thread modes)
  handlers/
    messages.py        free-text event -> enqueue
    interactions.py    list-row & button taps -> enqueue
    commands.py        helpers: pywa update -> queue job
scripts/
  try_parser.py        run the Hebrew parser locally, no WhatsApp needed
```

## The data model (onboarding-ready)

`Family` already exists with an `invite_code` column so the **next step**
(onboarding: create/join a family) is a natural extension. For the MVP, any
new phone number that messages the bot is auto-joined to a single default
family — perfect for demoing with two phones.

## Run it

### 1. Install

```bash
cd shopping-bot
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env      # fill in your WhatsApp + Anthropic values
```

### 2. Try the Hebrew parser without WhatsApp (great for a demo)

```bash
python scripts/try_parser.py "תביא חלב וגבינה ולחם"
python scripts/try_parser.py "תוריד את הביצים"
python scripts/try_parser.py "מה יש ברשימה"
```

This calls Claude and prints the structured intent — proof the NLP works before
any WhatsApp setup.

### 3. Run the bot

**Option A — memory backend (fastest, no Redis):** set `QUEUE_BACKEND=memory` in
`.env`, then one command runs everything (the worker runs in a background thread):

```bash
uvicorn app.main:app --reload --port 8000
```

**Option B — redis backend (production-shaped, two processes):** set
`QUEUE_BACKEND=redis` and make sure Redis is running
(`docker run -p 6379:6379 redis` or `brew services start redis`). Then:

```bash
# terminal 1 — web / producer
uvicorn app.main:app --port 8000

# terminal 2 — worker / consumer
python -m app.worker
```

Either way, expose the web process with ngrok and register the webhook in Meta
(Callback URL `https://<ngrok>/`, verify token = `WA_VERIFY_TOKEN`, subscribe to
`messages`). See the guard-bot README for the detailed Meta setup walkthrough —
the steps are identical.

> For the interview, Option B is the better story: it shows the producer/worker
> split and the queue doing real work. Run the worker in a visible terminal so you
> can point at jobs being consumed.

## Commands the bot understands

| You send | Bot does |
|---|---|
| `תביא חלב` / `צריך לחם` | adds items |
| `תוריד את החלב` | removes items |
| `רשימה` / `מה יש` | shows the interactive list |
| `נקה` | clears bought items |
| `עזרה` | help |

## Deploying to Railway (always-on, no ngrok)

Running on Railway gives you a **permanent HTTPS URL** (so you set Meta's callback
once and never touch ngrok again) and **managed Postgres + Redis**. The app runs
as **two services from the same repo**: a `web` (webhook producer) and a `worker`
(queue consumer).

What changes vs. local:
- **No ngrok** — the web service gets a fixed public domain.
- **SQLite → Postgres** — platform disks are ephemeral, so list data must live in
  managed Postgres. The code auto-normalizes the `DATABASE_URL` Railway provides.
- **Redis** — a managed add-on; set `REDIS_URL`.

### Steps

1. **Push the repo to GitHub** (public or private — Railway can access private repos).

2. **Create the project + web service:** Railway → **New Project → Deploy from
   GitHub repo** → pick `shopping-bot`. Railway builds from the `Dockerfile`.

3. **Add managed databases:** in the project, **New → Database → PostgreSQL**, then
   **New → Database → Redis**.

4. **Configure the WEB service:**
   - Settings → **Networking → Generate Domain** (this is your permanent URL).
   - Settings → **Start command** (if not using the Dockerfile default):
     `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Variables (see table below). For `DATABASE_URL` and `REDIS_URL`, use Railway
     references: `${{Postgres.DATABASE_URL}}` and `${{Redis.REDIS_URL}}`.

5. **Add the WORKER service:** **New → GitHub Repo** (same repo) → in its Settings
   set **Start command** to `python -m app.worker`. Give it the **same variables**
   as the web service. It needs **no** public domain.

6. **Point Meta at the permanent URL:** WhatsApp → Configuration → Callback URL =
   `https://<your-web-domain>/`, verify token = `WA_VERIFY_TOKEN`, subscribe to
   `messages`. Done once — it never changes again.

### Environment variables (set on BOTH services)

| Variable | Value |
|---|---|
| `WA_PHONE_ID` | from Meta API Setup |
| `WA_TOKEN` | your permanent System User token |
| `WA_VERIFY_TOKEN` | your chosen verify string |
| `WA_APP_SECRET` | Meta → App settings → Basic |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `CLAUDE_MODEL` | `claude-haiku-4-5-20251001` |
| `QUEUE_BACKEND` | `redis` |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` |

The web service additionally gets `PORT` injected automatically by Railway.

> Note: for the MVP the app creates tables on startup (`init_db`). For schema
> changes over time, move to Alembic migrations.

## Two environments: local dev vs cloud prod

A WhatsApp number's webhook can point to only **one** URL at a time. Production
points at Railway, so you can't also have Meta deliver to your laptop on the same
number. Here's how the two environments stay separate.

### Config is environment-driven (no code changes)

The same code runs in both places; only the env vars differ:

| Setting | Local (dev) | Cloud (prod) |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./shopping.db` | Railway Postgres |
| `QUEUE_BACKEND` | `memory` (worker in-process) | `redis` (separate worker) |
| WhatsApp creds | dev Meta app (optional) | prod Meta app |

Local reads `.env`; Railway reads its own Variables.

### Iterate locally WITHOUT WhatsApp (fast loop)

Most development never needs a live WhatsApp connection:

```bash
# 1. Test the Hebrew parser directly (calls Claude, no WhatsApp)
python scripts/try_parser.py "תביא חלב וגבינה"

# 2. Run the server locally (QUEUE_BACKEND=memory -> no Redis/worker needed)
uvicorn app.main:app --port 8000

# 3. Simulate WhatsApp events with a correctly-signed local POST:
python scripts/simulate_webhook.py "תביא חלב וגבינה"   # text message
python scripts/simulate_webhook.py "רשימה"             # view the list
python scripts/simulate_webhook.py --buy 3 --title חלב  # tap a list row (mark bought)
python scripts/simulate_webhook.py --button cmd:clear   # tap a button
```

`simulate_webhook.py` builds a realistic payload and signs it with your local
`WA_APP_SECRET`, so it goes through the exact same path Meta's real webhook would.
Watch the server logs to see it processed.

### Live local testing (optional)

When you specifically want a true end-to-end WhatsApp test on your laptop, create
a **second Meta app** (e.g. `shopping-bot-dev`) with its own test number, point its
webhook at your **ngrok** URL, and put its credentials in your local `.env`. Prod
(Railway, real number) is untouched. You message the dev test number while
developing, the prod number for real use.

## Roadmap

- **Next:** onboarding flow — create a family, invite your partner via code.
- Later: categories & smart aisle grouping, recurring items, reliable
  notifications via message templates, multi-family at scale, Alembic migrations.
