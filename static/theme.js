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

  // Each theme: label, dark?, display font for the big numbers ("serif" or "sans"),
  // card surface, accent and the text on it, and neutrals 50..950 (page background first).
  const SERIF = 'ui-serif, "New York", "Iowan Old Style", Georgia, serif';
  const SANS = 'ui-sans-serif, system-ui, -apple-system, "SF Pro Display", "Segoe UI", sans-serif';
  const THEMES = {
    light: {
      label: "Light", dark: false, display: "sans", surface: "ffffff", accent: "18181b", onAccent: "ffffff",
      neutral: ["f7f7f8", "f0f0f2", "e4e4e7", "d4d4d8", "a1a1aa", "71717a", "52525b", "3f3f46", "27272a", "18181b", "09090b"],
    },
    dark: {
      label: "Dark", dark: true, display: "sans", surface: "17191f", accent: "b7c4ff", onAccent: "0d0e12",
      neutral: ["0d0e12", "20232b", "2b2f39", "3c414d", "697084", "8f96a8", "b1b7c6", "cdd2dd", "e3e6ed", "f3f4f8", "ffffff"],
    },
    sand: {
      label: "Sand", dark: false, display: "serif", surface: "fffdf8", accent: "9a4a2c", onAccent: "fffaf3",
      neutral: ["f4eee4", "efe7da", "e4d9c8", "d3c4ae", "a69680", "7a6b58", "5a4e40", "463c31", "2d261f", "1f1a15", "110e0b"],
    },
    ocean: {
      label: "Ocean", dark: false, display: "sans", surface: "ffffff", accent: "1d5a7d", onAccent: "ffffff",
      neutral: ["edf2f5", "e3eaef", "d2dde5", "b5c6d2", "8399a8", "5c7282", "425664", "324350", "1f2c36", "121d25", "080f14"],
    },
    lavender: {
      label: "Lavender", dark: false, display: "sans", surface: "ffffff", accent: "6a4c9c", onAccent: "ffffff",
      neutral: ["f4f2f8", "edeaf4", "e0dbeb", "cbc4da", "9d94b1", "726a86", "554e66", "413b4f", "2a2634", "1b1822", "0e0c12"],
    },
    rose: {
      label: "Rose", dark: false, display: "serif", surface: "fffbfa", accent: "8e2c48", onAccent: "fff7f8",
      neutral: ["f8efee", "f3e6e5", "eadad8", "dbc5c3", "b09897", "84706f", "634f50", "4d3c3d", "322627", "211819", "120c0d"],
    },
    noir: {
      label: "Noir", dark: true, display: "serif", surface: "121212", accent: "d8b46a", onAccent: "141008",
      neutral: ["050505", "1c1c1c", "262626", "363636", "5e5e5e", "8a8a8a", "ababab", "c8c8c8", "e0e0e0", "f2f2f2", "ffffff"],
    },
  };

  function vars(t) {
    const out = [`--surface:${rgb(t.surface)}`, `--accent:${rgb(t.accent)}`, `--on-accent:${rgb(t.onAccent)}`,
                 `--shadow:${t.dark ? "0 0 0" : rgb(t.neutral[9])}`, `--font-display:${t.display === "serif" ? SERIF : SANS}`];
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
    root.dataset.mode = THEMES[name].dark ? "dark" : "light";
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
