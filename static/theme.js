"use strict";
/* Colour themes (Campo, Oct 2026).

   Each theme is a field colour (its own hue when you're on plan, the shared amber and red when
   spending runs ahead or goes over) plus the UI around it: neutrals (Tailwind's `slate-*`), the
   card colour (`surface`), the accent and the status tints, all CSS variables, so one switch
   recolours the whole app. `data-state` on <html> picks the field's colour (Theme.setState).
   Loaded right after Tailwind on every page; the last theme and state are cached in this
   browser so pages open in the right colours before the server answers. */

(function () {
  const rgb = (hex) => hex.match(/\w\w/g).map((h) => parseInt(h, 16)).join(" ");
  const STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];

  // Tailwind's own values, used by the light themes.
  const TINTS = {
    amber:   ["fffbeb", "fef3c7", "fde68a", "fcd34d", "fbbf24", "f59e0b", "d97706", "b45309", "92400e", "78350f", "451a03"],
    emerald: ["ecfdf5", "d1fae5", "a7f3d0", "6ee7b7", "34d399", "10b981", "059669", "047857", "065f46", "064e3b", "022c22"],
    red:     ["fef2f2", "fee2e2", "fecaca", "fca5a5", "f87171", "ef4444", "dc2626", "b91c1c", "991b1b", "7f1d1d", "450a0a"],
    sky:     ["f0f9ff", "e0f2fe", "bae6fd", "7dd3fc", "38bdf8", "0ea5e9", "0284c7", "0369a1", "075985", "0c4a6e", "082f49"],
    violet:  ["f5f3ff", "ede9fe", "ddd6fe", "c4b5fd", "a78bfa", "8b5cf6", "7c3aed", "6d28d9", "5b21b6", "4c1d95", "2e1065"],
  };

  // Each theme: the field's colour when you're on plan (the theme's own hue) with its deeper shade,
  // the UI around it (page ground, card surface, neutrals 50..950, page ground first), and the
  // accent for selection and focus (the theme's hue). Amber and red mean the same in every theme.
  const LIGHT = ["f4f4f5", "ececee", "e2e3e6", "cfd1d6", "a0a3ab", "70737b", "53565d", "3f4147", "27292d", "16171a", "0a0b0c"];
  const AMBER = ["a3600a", "874f08"], RED = ["b4272f", "901c23"];      // white text passes 4.5:1 on both
  const light = (label, ground, field, deep) => ({
    label, dark: false, surface: "ffffff", accent: field, onAccent: "ffffff", neutral: [ground, ...LIGHT.slice(1)],
    field: { green: [field, deep], amber: AMBER, red: RED },
  });
  const THEMES = {
    verde:   light("Verde", "f1f4f2", "1d6a48", "155238"),
    azul:    light("Azul", "f1f3f8", "1f4fa8", "173d84"),
    mar:     light("Mar", "eff5f5", "0f6f70", "0a5556"),
    ciruela: light("Ciruela", "f5f2f5", "6a2f6e", "532456"),
    teja:    light("Teja", "f6f2ef", "8a4b2c", "6e3b22"),
    tinta:   light("Tinta", "f3f3f4", "2a2b30", "1a1b1f"),
    noche: {
      label: "Noche", dark: true, surface: "16171b", accent: "5cc28f", onAccent: "0d0e10",
      neutral: ["0d0e10", "1d1f23", "27292e", "373a40", "5c6068", "868a93", "a9adb5", "c9ccd2", "e1e3e7", "f3f4f6", "ffffff"],
      field: { green: ["15402d", "0f3021"], amber: ["6b4109", "573406"], red: ["6e1a20", "581419"] },
    },
  };
  // Themes from before the Campo look (Oct 2026) open as their nearest new one.
  const OLD = { light: "verde", dark: "noche", sand: "teja", ocean: "mar", lavender: "ciruela", rose: "ciruela", noir: "noche" };
  const canonical = (name) => OLD[name] || name;

  function vars(t) {
    const out = [`--surface:${rgb(t.surface)}`, `--accent:${rgb(t.accent)}`, `--on-accent:${rgb(t.onAccent)}`,
                 `--shadow:${t.dark ? "0 0 0" : rgb(t.neutral[9])}`];
    for (const [st, [base, deep]] of Object.entries(t.field)) out.push(`--field-${st}:${rgb(base)}`, `--field-${st}-deep:${rgb(deep)}`);
    STEPS.forEach((s, i) => out.push(`--slate-${s}:${rgb(t.neutral[i])}`));
    for (const [name, shades] of Object.entries(TINTS)) {
      // Dark themes flip each tint scale, so pale backgrounds become deep ones
      // and dark text becomes light.
      STEPS.forEach((s, i) => out.push(`--${name}-${s}:${rgb(t.dark ? shades[STEPS.length - 1 - i] : shades[i])}`));
    }
    return out.join(";");
  }

  const style = document.createElement("style");
  style.textContent = Object.entries(THEMES)
    .map(([name, t]) => `:root[data-theme="${name}"]{${vars(t)};color-scheme:${t.dark ? "dark" : "light"}}`).join("\n")
    // The field: the budget's state (green on plan, amber when spending runs ahead, red when over).
    + "\n" + ["green", "amber", "red"].map((st) => `:root[data-state="${st}"]{--field:var(--field-${st});--field-deep:var(--field-${st}-deep)}`).join("\n")
    + "\n:root:not([data-state]){--field:var(--field-green);--field-deep:var(--field-green-deep)}"
    // Switch every colour at once instead of letting buttons fade between themes.
    + "\n.theme-switching, .theme-switching * { transition: none !important; }";
  document.head.append(style);

  const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
  const scale = (name) => Object.fromEntries(STEPS.map((s) => [s, v(`${name}-${s}`)]));
  window.tailwind = window.tailwind || {};
  window.tailwind.config = {
    theme: {
      extend: {
        colors: {
          slate: scale("slate"),
          ...Object.fromEntries(Object.keys(TINTS).map((n) => [n, scale(n)])),
          surface: v("surface"),
          accent: v("accent"),
          "on-accent": v("on-accent"),
          field: v("field"),
          "field-deep": v("field-deep"),
        },
      },
    },
  };

  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let choice = "auto";
  try { choice = canonical(localStorage.getItem("budget-theme") || "auto"); } catch { /* storage blocked */ }
  // The last known budget state, so the field opens in the right colour before the server answers.
  try { const st = localStorage.getItem("budget-state"); if (st) document.documentElement.dataset.state = st; } catch { /* storage blocked */ }

  const resolved = () => (choice === "auto" ? (media.matches ? "noche" : "verde") : choice);

  function apply() {
    const name = THEMES[resolved()] ? resolved() : "verde";
    const root = document.documentElement;
    root.classList.add("theme-switching");
    root.dataset.theme = name;
    root.dataset.mode = THEMES[name].dark ? "dark" : "light";
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("theme-switching")));
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) { meta = document.createElement("meta"); meta.name = "theme-color"; document.head.append(meta); }
    meta.content = getComputedStyle(root).getPropertyValue("--field") ? `rgb(${getComputedStyle(root).getPropertyValue("--field").trim()})` : `#${THEMES[name].neutral[0]}`;
    window.dispatchEvent(new CustomEvent("themechange", { detail: name }));
  }
  media.addEventListener("change", () => { if (choice === "auto") apply(); });

  window.Theme = {
    THEMES,
    get choice() { return choice; },
    get current() { return resolved(); },
    canonical,
    /** The budget's state on every page: "green", "amber", "red" (or null: no monthly budget). */
    setState(st) {
      const root = document.documentElement;
      if (st) root.dataset.state = st; else delete root.dataset.state;
      try { st ? localStorage.setItem("budget-state", st) : localStorage.removeItem("budget-state"); } catch { /* storage blocked */ }
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.content = `rgb(${getComputedStyle(root).getPropertyValue("--field").trim()})`;
    },
    set(name) {
      name = canonical(name);
      choice = name === "auto" || THEMES[name] ? name : "auto";
      try { localStorage.setItem("budget-theme", choice); } catch { /* storage blocked */ }
      apply();
    },
    /** A theme colour as a CSS colour string, for charts: Theme.color("slate-500"). */
    color(name, alpha = 1) {
      const val = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
      return `rgb(${val} / ${alpha})`;
    },
  };
  apply();
})();
