# Budget

A personal budget tracker that runs as a normal Mac app, with its own window and a Dock icon, and you can open it from Spotlight or Launchpad. You log card spending (by hand, from a bank CSV, or from an iPhone Shortcut). It sorts each expense into a category and shows how you're doing against your weekly and monthly limits.

Everything stays on your Mac. The one exception is optional: if you add a Claude API key, the names of merchants the app doesn't recognise are sent to Claude so it can guess a category.

---

## 1. Install the app

You need **Python 3.10 or newer** to build it (check with `python3 --version`). After that, the app contains everything it needs.

```bash
cd ~/budget-app
./build.sh --install
```

This sets up a virtualenv, installs the dependencies, runs the tests, builds `dist/Budget.app` and copies it to **/Applications**. Open **Budget** from Spotlight (`Cmd+Space`, type "Budget"), Launchpad, or the Applications folder. You can keep it in the Dock: right-click the icon, then **Options → Keep in Dock**.

If you'd rather install it by hand, run plain `./build.sh` and drag `dist/Budget.app` into Applications.

When you open Budget, it starts its server on a free port on `127.0.0.1` and shows the window. Closing the window or pressing `Cmd+Q` shuts everything down. The interface, including Tailwind and Chart.js, is bundled inside the app, so it works offline.

## 2. Where your data lives

```
~/Library/Application Support/Budget/
  budget.db       your expenses, categories, limits and learned merchants
  backups/        copies made with "Back up now"
  .env            optional settings (sections 6 and 7)
```

This folder is outside the project and outside the app, so **rebuilding, reinstalling or deleting Budget.app never touches your data**. **Settings → Your data → Show in Finder** opens it.

**Moving from the old location:** the first time Budget starts and finds no database in that folder, it copies `data/budget.db` from the project (and `data/backups/`) over. The old files are left where they were. Once you've checked everything is in the app, you can delete the project's `data/` folder.

The app writes a log to `~/Library/Logs/Budget/budget.log`. Look there if it won't start.

## Rebuilding after you change the code

```bash
cd ~/budget-app
./build.sh --install
```

That's the whole loop. If Budget is open, the script quits it, replaces `/Applications/Budget.app` with the new build, and you open it again. Your data stays in Application Support, so nothing is lost.

`./build.sh` stops if any test fails, so a broken change never gets installed.

The version shown in Finder's **Get Info** comes from the `VERSION` file. To change the icon, edit `macos/make_icon.py`, run `.venv/bin/python macos/make_icon.py`, and rebuild.

### Running from source while developing

```bash
python3 run.py            # opens the app window straight from the code (no build needed)
python3 run.py --debug    # same, with the web inspector (right-click > Inspect Element)
python3 run.py --browser  # no window: serve at http://localhost:8000 for a normal browser
```

`run.py` uses the same data folder as the installed app. Don't run both at the same time.

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

Create the settings file from the template:

```bash
cp ~/budget-app/.env.example ~/Library/"Application Support"/Budget/.env
open -e ~/Library/"Application Support"/Budget/.env
```

Put your key from https://console.anthropic.com on this line:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Then quit and reopen Budget. Merchants that none of the other layers recognise are sent to Claude (model `claude-opus-5-5`) and it picks one of your categories. Only the merchant name is sent, never amounts or dates. Each answer is cached, so the same merchant is never sent twice. If the key is missing, wrong, or you're offline, the app simply marks the expense Uncategorized.

## 7. Quick-add from your iPhone (Shortcuts)

### Set a token and turn on phone access

Create a secret token:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

In `~/Library/Application Support/Budget/.env` (see section 6), set:

```
QUICKADD_TOKEN=paste-the-token-here
BUDGET_LAN=1
BUDGET_PORT=8000
```

Quit and reopen Budget. With `BUDGET_LAN=1` it listens on your Wi-Fi at a fixed port (8000) instead of a random local one, so the Shortcut always has the same address. The first time, macOS asks whether Budget can accept incoming network connections. Click **Allow**. The Settings page shows "Reachable from your phone on Wi-Fi: yes".

To find your Mac's address, go to **System Settings → Wi-Fi → Details** for the IP address, or use its local name from **System Settings → General → Sharing → Local hostname** (e.g. `My-MacBook.local`, which doesn't change). The quick-add URL is then `http://My-MacBook.local:8000/api/expenses/quick`.

When running from source, `python3 run.py --lan` does the same and prints the URL.

> **What other devices can reach.** With phone access on, other devices on the Wi-Fi can only call the token-protected quick-add endpoint. The dashboard and your transactions are still only available on your Mac. Even so, turn `BUDGET_LAN` on only if you mostly use trusted networks like home. On public or university Wi-Fi, set it back to `0`.

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

Test it from the Mac (with `BUDGET_LAN=1`, so the port is 8000):

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

Your Mac must be awake, with Budget open, for the Shortcut to work.

## 8. Back up and restore your data

- **Back up:** go to **Settings → Your data → Back up now**. This saves a timestamped copy such as `backups/budget-2026-10-04_17-49-49.db` next to the database. It's safe to do while the app is open. For extra safety, copy the whole `~/Library/Application Support/Budget` folder to iCloud Drive or a USB stick now and then.
- **Restore:** quit Budget. In `~/Library/Application Support/Budget`, move `budget.db` aside and delete `budget.db-wal` and `budget.db-shm` if they exist. Copy the backup you want to `budget.db` and open Budget again.
- **Export:** **Settings → Export all to CSV** or **Transactions → Export CSV** opens a Save dialog. The file uses `;` separators and decimal commas, so it opens correctly in Spanish-language Excel and Numbers.

Your data and settings are never inside the project folder, so they can't end up on GitHub. `data/`, `.env`, `build/` and `dist/` are also in `.gitignore`.

## 9. Tests

```bash
.venv/bin/python -m pytest
```

The tests cover merchant clean-up, every categorization layer (including corrections beating rules, and AI caching and failure), budget maths (Monday weeks, month ends and leap years, the 75%/100% colour thresholds, € left and € per day), the quick-add API (including its token check and LAN restriction), moving data from the old `data/` folder, and the native CSV export. They use temporary folders and never touch your real data.

## Project layout

```
build.sh               build Budget.app (./build.sh --install also installs it)
run.py                 run from source: python3 run.py
VERSION                app version shown in Finder
app/
  desktop.py           native window (pywebview) + background server + shutdown
  config.py            paths (Application Support), .env settings
  main.py              web app setup, LAN restriction
  db.py                database schema, created automatically; moves old data/
  seed.py              default categories + Spanish merchant keywords
  normalize.py         merchant name clean-up
  categorizer.py       learned → similar → keyword → AI
  budgets.py           week/month maths, limits, € left / per day
  importer.py          CSV reading, date/amount parsing, duplicate checks
  routers/             the JSON API (expenses, categories, budgets, dashboard, import/export)
static/                the interface (HTML + JS; Tailwind and Chart.js in static/vendor)
macos/
  Budget.spec          PyInstaller recipe
  launcher.py          entry point inside the app
  make_icon.py         draws icon.png and Budget.icns
tests/                 pytest tests
```
