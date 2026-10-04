# Budget

A personal budget tracker that runs on your own computer. You log card spending (by hand, from a bank CSV, or from an iPhone Shortcut). It sorts each expense into a category and shows how you're doing against your weekly and monthly limits.

Everything is stored in one file on your computer, `data/budget.db`. Nothing goes to the internet. The one exception is optional: if you add a Claude API key, the names of merchants the app doesn't recognise are sent to Claude so it can guess a category.

---

## 1. Install (once)

You need **Python 3.10 or newer**. Check with `python3 --version`.

```bash
cd ~/budget-app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Optional: copy the settings template if you want AI categorization or the iPhone quick-add:

```bash
cp .env.example .env
```

Then open `.env` in a text editor (see sections 6 and 7).

## 2. Run it

```bash
python3 run.py
```

Open **http://localhost:8000** in your browser. Press `Ctrl+C` in the terminal to stop the app.

- The database and its tables are created automatically the first time you run it.
- Closing the browser or stopping the server never loses data. Every change is saved straight to `data/budget.db`.
- The page loads its styling (Tailwind) and charts (Chart.js) from the internet, so the first load needs a connection.

Other options:

```bash
python3 run.py --port 8080   # use a different port
python3 run.py --lan         # let your phone reach the quick-add API (see section 7)
```

## 3. Using it

| Page | What it's for |
|---|---|
| **Dashboard** | This week and this month at a glance: how much you've spent against your limit, what's left, € per day, and days left. Switch between Week and Month and use ‹ › to go back to earlier periods. It shows spending by category, daily bars, month-by-month totals and your top merchants. Click anything to see the matching transactions. |
| **Add** | Quick form: amount, merchant, date (defaults to today) and an optional note. Tick "refund" for money back. |
| **Transactions** | Search, filter by category or dates, sort, and tap any row to edit or delete it. |
| **Import** | Bring in a CSV from your bank (section 5). |
| **Settings** | Weekly and monthly limits, categories (rename, recolour, reorder, delete), learned merchants, backups and export. |

Dates are shown as DD/MM/YYYY, weeks start on Monday, and amounts are in euros. You can type amounts as `12,50` or `12.50`.

### How categories are chosen

As you type a merchant, the app suggests a category and shows a small tag saying where the suggestion came from:

1. **LEARNED.** You chose a category for this merchant before. Your choice always wins.
2. **LEARNED · SIMILAR.** The name is very close to a merchant you've already categorised, such as a typo or a different store number.
3. **RULE.** A built-in keyword for common Spanish merchants (Mercadona, Glovo, Metro, Renfe, Zara, Netflix…).
4. **AI.** Claude's guess. This only happens when an API key is set.
5. If nothing matches, the expense is **Uncategorized**. Pick a category and it's remembered for next time.

Names are cleaned up before matching, so `MERCADONA MADRID 4521`, `Compra en MERCADONA, S.A.` and `Mercadona` all count as the same merchant. You can review or change everything the app has learned in **Settings → Learned merchants**.

## 4. Budgets

In **Settings → Budgets & limits**, set an overall weekly and/or monthly limit, plus optional limits per category. Each box saves as soon as you leave it, and an empty box means no limit.

Progress bars are **green** under 75%, **amber** from 75% to 100%, and **red** when you're over. The dashboard also shows "€X left this week" and how much you can spend per day until the end of the week or month (today included).

Refunds count as negative spending, so they give you budget back.

## 5. Importing a bank CSV

1. Download your card movements as CSV from your bank's website.
2. Go to **Import** and choose the file.
3. Check which columns are the **date**, **description** and **amount**. The app guesses, and it remembers your choice for the next file with the same columns.
4. Say whether spending appears as negative numbers (most Spanish banks: `-12,50`) or positive ones.
5. Click **Preview import**. Each row is categorised automatically. Change any category you disagree with, and the app will learn it.
6. **Likely duplicates are unticked.** That means rows you've already imported, or an expense you already entered by hand with the same amount and a similar merchant within a day. Tick them if they're really new.
7. Click **Import**.

Rows the app can't read, like an impossible date, are listed and skipped.

## 6. AI categorization (optional)

Put your key from https://console.anthropic.com in `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Restart the app. Merchants that none of the other layers recognise are sent to Claude (model `claude-opus-5-5`) and it picks one of your categories. Only the merchant name is sent, never amounts or dates. Each answer is cached, so the same merchant is never sent twice. If the key is missing, wrong, or you're offline, the app simply marks the expense Uncategorized.

## 7. Quick-add from your iPhone (Shortcuts)

### Set a token

Create a secret token:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(24))"
```

Put it in `.env`:

```
QUICKADD_TOKEN=paste-the-token-here
```

### Start the app in LAN mode

```bash
python3 run.py --lan
```

The terminal prints the address to use, for example `http://192.168.1.23:8000/api/expenses/quick`. The first time, macOS may ask whether Python can accept incoming connections. Click **Allow**.

> **What other devices can reach.** In `--lan` mode, other devices on the Wi-Fi can only call the token-protected quick-add endpoint. The dashboard and your transactions are still only available on your Mac. Even so, start `--lan` only on networks you trust, like home, and use plain `python3 run.py` on public or university Wi-Fi.

Your Mac's IP address can change. A steadier option is your Mac's local name: go to **System Settings → General → Sharing** and look for "Local hostname", e.g. `My-MacBook.local`. Then the URL is `http://My-MacBook.local:8000/api/expenses/quick`.

### The API

`POST /api/expenses/quick` with header `Authorization: Bearer <your token>` and a JSON body:

| Field | Required | Example |
|---|---|---|
| `amount` | yes | `4.50` or `"4,50"` |
| `merchant` | yes | `"Starbucks"` |
| `date` | no (default: today) | `"2026-10-04"` or `"04/10/2026"` |
| `note` | no | `"with Ana"` |
| `category` | no (default: auto) | `"Eating Out"` |

The reply is the saved expense plus a `message` such as `"Saved 4,50 € at Starbucks · Eating Out"`.

Test it from the Mac:

```bash
curl -X POST http://localhost:8000/api/expenses/quick \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount": "4,50", "merchant": "Starbucks"}'
```

### Build the Shortcut

In the **Shortcuts** app, tap **+** and add these actions in order:

1. **Ask for Input**: Input type *Number*, prompt "Amount (€)?"
2. **Set Variable**: name it `Amount`.
3. **Ask for Input**: Input type *Text*, prompt "Where?"
4. **Set Variable**: name it `Merchant`.
5. **Get Contents of URL**:
   - URL: `http://<your-mac>:8000/api/expenses/quick`
   - Method: **POST**
   - Headers: `Authorization` = `Bearer YOUR_TOKEN`
   - Request Body: **JSON**, with `amount` = *Amount* and `merchant` = *Merchant*
6. **Get Dictionary Value**: get the value for `message` from *Contents of URL*.
7. **Show Notification**: show *Dictionary Value*.

Add it to your Home Screen, or trigger it from an Apple Pay automation (**Automation → Wallet → When I tap a card**). An automation can pass the merchant and amount in directly, so you don't have to type them.

Your Mac must be awake with `python3 run.py --lan` running for the Shortcut to work.

## 8. Back up and restore your data

- **Back up:** go to **Settings → Your data → Back up now**. This saves a timestamped copy such as `data/backups/budget-2026-10-04_17-49-49.db`. It's safe to do while the app is running. For extra safety, copy the `data/` folder to iCloud Drive or a USB stick now and then.
- **Restore:** stop the app (`Ctrl+C`). Move the current `data/budget.db` aside, and delete `data/budget.db-wal` and `data/budget.db-shm` if they exist. Copy a backup to `data/budget.db` and start the app again.
- **Export:** **Settings → Export all to CSV** or **Transactions → Export CSV**. The file uses `;` separators and decimal commas, so it opens correctly in Spanish-language Excel and Numbers.

`data/` and `.env` are listed in `.gitignore`, so your spending and keys are never committed if you put the code on GitHub.

## 9. Tests

```bash
.venv/bin/python -m pytest
```

The tests cover merchant clean-up, every categorization layer (including corrections beating rules, and AI caching and failure), budget maths (Monday weeks, month ends and leap years, the 75%/100% colour thresholds, € left and € per day), and the quick-add API, including its token check and LAN restriction. They use a temporary database and never touch your real data.

## Project layout

```
run.py                 start the app (python3 run.py)
app/
  main.py              web app setup, LAN restriction
  db.py                database schema, created automatically
  seed.py              default categories + Spanish merchant keywords
  normalize.py         merchant name clean-up
  categorizer.py       learned → similar → keyword → AI
  budgets.py           week/month maths, limits, € left / per day
  importer.py          CSV reading, date/amount parsing, duplicate checks
  routers/             the JSON API (expenses, categories, budgets, dashboard, import/export)
static/                the web page (HTML + Tailwind + Chart.js, no build step)
tests/                 pytest tests
data/                  your database and backups (created on first run, not in git)
```
