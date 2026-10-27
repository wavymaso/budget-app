# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

- **Mac and Windows:** a desktop app whose window is the web UI in `static/`. It is served by a local
  FastAPI server and also opens as a home-screen web app on phones.
- **iPhone:** a native SwiftUI app in `ios/`. It works offline and syncs with the Mac.

Both front ends show the same product and share themes: a theme picked on one device applies on the
other.

## Users

- **Primary:** the owner, a university student in Madrid. Almost all spending is on one card
  through Apple Pay.
- **Also:** a few friends or classmates install it from the public GitHub release, so a first-time
  user must understand it without help.
- **Feedback on record:** someone who saw the app said there was too much going on at first glance.

## Product Purpose

Know how much is left to spend this month and this week, and log every expense in seconds, so the
month ends within budget. Success: one glance answers "how much can I spend?", and logging a
payment never feels like a chore.

## Positioning

- **Private:** data stays on your own devices. There's no account, no cloud and no tracking.
- **One clear number:** home shows what's left to spend this month, a per-day amount, and whether
  you're ahead of or behind plan.
- **Expenses arrive by themselves:** Apple Pay payments come in by email and are read from Gmail on
  the Mac or the iPhone.
- **Knows Spanish merchants:** categories are suggested from Spanish merchant names (Mercadona,
  Glovo, Metro, Renfe, Zara…) and learn from every correction.

## Operating Context

- **The two moments that matter most:**
  1. **The glance:** open, see what's left, close. Often on the phone, during the day.
  2. **The quick log:** add a payment in a few seconds, usually on the phone, right after paying.
- **Less often:** seeing where the money went (categories and recent expenses), and the monthly
  look back with savings.

## Capabilities and Constraints

- Screens: Home, Add expense, Transactions, Settings. Charts are one tap away.
- Expense entry: amount, merchant, category (suggested), date (Today / Yesterday shortcuts).
- Budget limits: weekly and monthly, overall and per category, with green, amber and red levels.
- Monthly bills: added automatically every month.
- Savings: what's left of the month goes to savings, with an optional goal.
- Imports: bank CSVs and Apple Pay emails from Gmail.
- AI: an optional Claude API key suggests categories for unknown merchants.
- Housekeeping: a daily backup and a heads-up when the iPhone Shortcut goes quiet.
- Formats: euros, weeks start on Monday, dates are DD/MM/YYYY, Spanish number formatting
  (414,59 €).
- Web stack: vanilla JS, Tailwind with CSS-variable themes (`static/theme.js`), and a service
  worker for offline use. iPhone: SwiftUI and SwiftData, with themes mirrored in
  `ios/Budget/Theme.swift`.
- The Windows window is WebView2, and no person has checked it on a real PC yet.

## Brand Commitments

- **Name:** Budget. The current mark is a euro sign.
- **Themes:** the user wants a choice of colour themes. Keep them, redrawn inside the new look; the
  count may change, and Automatic follows the device. Themes stay shared between the Mac and the
  iPhone.

## Evidence on Hand

- Real merchants and categories in the user's data.
- `docs/dashboard.png` and `docs/add-phone.png` (7 Oct 2026, the old look).
- There are no testimonials, user counts or press, and none may be invented.

## Product Principles

1. **Answer first.** What's left to spend is the first thing on screen, and the rest is optional
   detail.
2. **Remove before adding.** Fewer metrics, fewer charts, less on screen at once. Hide rather than
   show.
3. **Logging takes seconds.** Frequent merchants and likely categories are one tap away.
4. **Private by default.** Nothing leaves the user's devices unless they connect it.
5. **Understandable without help** for a friend opening it for the first time.

## Accessibility & Inclusion

- Dynamic Type and VoiceOver on the iPhone.
- Readable contrast in every theme.
- Amounts never wrap or truncate.
