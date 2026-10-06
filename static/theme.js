"use strict";
/* Colour themes.

   Every neutral (Tailwind's `slate-*`), the card colour (`surface`), the accent
   and the status tints (amber, emerald, red, sky, violet) are CSS variables, so
   one theme switch recolours the whole app. Loaded right after Tailwind on every
   page; the last choice is cached in this browser so pages open in the right
   colours before the server answers. */

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

  // name, swatch label, neutrals 50..950, card surface, accent, text on accent, dark?
  const THEMES = {
    light: {
      label: "Light", dark: false, surface: "ffffff", accent: "0f172a", onAccent: "ffffff",
      neutral: ["f8fafc", "f1f5f9", "e2e8f0", "cbd5e1", "94a3b8", "64748b", "475569", "334155", "1e293b", "0f172a", "020617"],
    },
    dark: {
      label: "Dark", dark: true, surface: "161c28", accent: "8ab4f8", onAccent: "0b0f19",
      neutral: ["0b0f19", "1f2635", "2c3548", "404b60", "6f7b92", "939eb4", "b0bbcc", "cbd5e1", "e2e8f0", "f1f5f9", "ffffff"],
    },
    sand: {
      label: "Sand", dark: false, surface: "fffdf9", accent: "b4532a", onAccent: "ffffff",
      neutral: ["f8f4ed", "f1ebe1", "e6ddcf", "d5c9b7", "a89d8c", "786f61", "575045", "443e36", "2a2520", "1c1916", "0f0d0b"],
    },
    ocean: {
      label: "Ocean", dark: false, surface: "ffffff", accent: "0e63a8", onAccent: "ffffff",
      neutral: ["eff5fb", "e5eef7", "d3e1ee", "b6cade", "829ab4", "5a718c", "40556e", "2e4058", "1b2a3e", "0e1c2e", "06101c"],
    },
    lavender: {
      label: "Lavender", dark: false, surface: "ffffff", accent: "6d4bd8", onAccent: "ffffff",
      neutral: ["f6f4fb", "efecf8", "e2ddf1", "cdc6e4", "9b93b8", "6e668c", "504a6c", "3c3656", "26213a", "181428", "0d0a17"],
    },
  };

  function vars(t) {
    const out = [`--surface:${rgb(t.surface)}`, `--accent:${rgb(t.accent)}`, `--on-accent:${rgb(t.onAccent)}`];
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
        },
      },
    },
  };

  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let choice = "auto";
  try { choice = localStorage.getItem("budget-theme") || "auto"; } catch { /* storage blocked */ }

  const resolved = () => (choice === "auto" ? (media.matches ? "dark" : "light") : choice);

  function apply() {
    const name = THEMES[resolved()] ? resolved() : "light";
    const root = document.documentElement;
    root.classList.add("theme-switching");
    root.dataset.theme = name;
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("theme-switching")));
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) { meta = document.createElement("meta"); meta.name = "theme-color"; document.head.append(meta); }
    meta.content = `#${THEMES[name].neutral[0]}`;
    window.dispatchEvent(new CustomEvent("themechange", { detail: name }));
  }
  media.addEventListener("change", () => { if (choice === "auto") apply(); });

  window.Theme = {
    THEMES,
    get choice() { return choice; },
    get current() { return resolved(); },
    set(name) {
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
