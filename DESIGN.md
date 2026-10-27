# Budget design: Campo

Spanish identity design of the Cruz Novillo school (flat colour marks): one flat field of colour
and one number. **The field's colour is the budget's state.** Everything else stays quiet and
standard so the glance and the quick log stay fast (PRODUCT.md).

Sources:
- Web (Mac and Windows window): `static/theme.js`, `static/index.html` (styles) and `static/app.js`.
- iPhone: `ios/Budget/Theme.swift`, `HomeView.swift` and `ExpenseViews.swift`.

Keep the two in step.

## The field

**State rule** (`budgetState` in app.js, `monthPace` in Logic.swift). It's the same on both
platforms:
- **red:** spent more than the monthly budget.
- **amber:** everyday spending (monthly bills left out) is more than 3% of the everyday budget ahead
  of an even pace through the month.
- **green:** otherwise.
- **none:** no monthly budget, so the theme's own colour.

**Where the field appears:**
- Home: the hero band, full width, running up under the header or bar.
- Add: the amount is typed on the field. While you type, the field previews the state the
  expense would lead to: "Still green", or "Turns amber" / "Turns red".
- The `€` mark in the header, on every page.
- The login page and the app icon.

**Decoration:** one deeper-shade disc bleeds off the top-right corner. It never sizes the layout.

**Text on the field** is white; secondary text is white at 86%. Never grey on the field.

**Motion:** the field's colour changes over 600 ms (`cubic-bezier(.16,1,.3,1)`), and the ring's
arc over 700 ms. Nothing else animates beyond a 200 ms fade. Reduce Motion turns both off.

## Signature elements (Home)

- **Ring** (`ringSvg` / `Ring`):
  - White fills it as the month's budget is spent.
  - A notch in the deeper shade marks the plan for today: bills paid plus an even share of the
    everyday budget.
  - White past the notch means ahead of plan.
  - The centre shows the days to go.
- **This week:** seven flat tiles, Monday first. Each fills from the bottom with that day's
  spending against a day's share of the weekly limit (or the monthly one). Today is outlined;
  days still to come are fainter.
- **Where it went:** one flat band, one stripe per category sized by its share, then the list. A
  category over its limit says "over 80 €" in red, a word as well as a colour.
- **State pill:** "On plan", "117,64 € under plan", "29,97 € ahead of plan" or
  "Over: 979,97 € of 900 €", on a black-18% capsule.

## Themes

A theme sets the field's colour when on plan, plus the UI around it. Amber `#a3600a` (deep
`#874f08`) and red `#b4272f` (deep `#901c23`) are the same in every light theme, and white text on
them passes 4.5:1.

| Theme | Field | Deep | Page ground |
|---|---|---|---|
| Verde (default by day) | `#1d6a48` | `#155238` | `#f1f4f2` |
| Azul | `#1f4fa8` | `#173d84` | `#f1f3f8` |
| Mar | `#0f6f70` | `#0a5556` | `#eff5f5` |
| Ciruela | `#6a2f6e` | `#532456` | `#f5f2f5` |
| Teja | `#8a4b2c` | `#6e3b22` | `#f6f2ef` |
| Tinta | `#2a2b30` | `#1a1b1f` | `#f3f3f4` |
| Noche (dark, default at night) | `#15402d` (amber `#6b4109`, red `#6e1a20`) | `#0f3021` | `#0d0e10` |

**Old theme choices** open as their nearest new one, on the server, the web and the iPhone:

| Old | New |
|---|---|
| light | verde |
| dark | noche |
| sand | teja |
| ocean | mar |
| lavender | ciruela |
| rose | ciruela |
| noir | noche |

**Accent:** the theme's field colour, used for selection, focus and the active tab only.
**Primary buttons** are ink: `slate-900` on light themes, which inverts on Noche.

## Type

- **Big amounts:** the platform grotesk at its heaviest weight (SF Pro / Segoe UI Variable, weight
  900), tracking -0.045em, tabular figures, with the `€` at half size and raised (`.display` and
  `bigMoney`).
  - Web size: `clamp(3rem, 17vw, 4.25rem)` on phones, 6rem on desktop.
  - iPhone size: 68 pt scaled with Dynamic Type, shrinking to fit rather than wrapping.
- **Everything else:** the system UI font. Headings are bold, body text medium or regular. Numbers
  in lists are tabular.

## Layout

- **Home:**
  1. The field band.
  2. The sheet: page ground with 28 px top corners, overlapping the field by 28 px.
  3. On the sheet: notices, the month review, then Where it went and Recent (two columns on
     desktop). Trends stay behind "Show trends".
- **Phones:** the ring sits top right, above the number.
- **Cards:** surface colour, radius 22 px, a soft offset shadow and no border.
- **Category marks:** rounded squares (tinted letter avatars in rows, 12 px colour squares in
  lists).

## Checking a change

- **Web screenshots:** run the app on a copy of the data (`BUDGET_DATA_DIR=<copy> run.py --browser
  --port 8765`, with Gmail and phone access off in the copy). Capture at 390×844 (phone emulation)
  and 1280×900.
- **iPhone:** use the simulator, connected to that copy with `-connect http://127.0.0.1:8765
  -password …`.
- **Every pass checks:** the green, amber and red states (change the copy's monthly limit), Verde
  and Noche, and Accessibility XL on the iPhone.
