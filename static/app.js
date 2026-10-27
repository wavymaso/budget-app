"use strict";

/* ===========================================================================
   Helpers
   ======================================================================== */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  local: true,        // false when opened from a phone over Wi-Fi
  categories: [],
  charts: [],
  renderToken: 0,
  txFilters: { q: "", category_id: "", date_from: "", date_to: "", sort: "date:desc" },
  prefs: {},
};

/** "Mac" or "PC": the computer Budget runs on (the server says which). */
const computer = () => state.prefs.computer || "Mac";
const onPC = () => computer() === "PC";
const fileBrowser = () => onPC() ? "File Explorer" : "Finder";
const passwordStore = () => onPC() ? "Windows Credential Manager" : "your Mac's Keychain";

/** Save one or more preferences (theme, hidden notices) and keep a local copy. */
async function savePrefs(changes) {
  Object.assign(state.prefs, changes);
  try { state.prefs = await api("/api/preferences", { method: "PUT", body: changes }); }
  catch (err) { toast(err.message, "error"); }
}

const eurFormat = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });
const fmtMoney = (cents) => eurFormat.format((cents || 0) / 100);
/** Like fmtMoney, without ",00" on whole euros: "600 €". */
const fmtMoneyShort = (cents) => fmtMoney(cents).replace(/,00(?=\D*$)/, "");

const pad = (n) => String(n).padStart(2, "0");
const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const todayISO = () => isoOf(new Date());
const addDaysISO = (iso, n) => {
  const [y, m, d] = iso.split("-").map(Number);
  return isoOf(new Date(y, m - 1, d + n));
};

/** "2026-10-04" -> "04/10/2026" */
function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

/** "4/10/26", "04-10-2026", "2026-10-04" -> "2026-10-04" (or null if invalid) */
function parseDate(text) {
  const s = (text || "").trim();
  let y, m, d;
  let match = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (match) [, y, m, d] = match.map(Number);
  else {
    match = s.match(/^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2}|\d{4})$/);
    if (!match) return null;
    [, d, m, y] = match.map(Number);
    if (y < 100) y += 2000;
  }
  const dt = new Date(y, m - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return null;
  return isoOf(dt);
}

/** "12,50" / "12.50" / "1.234,56" / "€ 7" -> 12.5 (NaN if invalid) */
function parseAmount(text) {
  let s = String(text || "").replace(/[€\s]/g, "");
  if (s.includes(",") && s.includes(".")) s = s.replace(/\./g, "").replace(",", ".");
  else s = s.replace(",", ".");
  if (!/^-?\d*\.?\d+$/.test(s)) return NaN;
  return Number(s);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

let uidCounter = 0;
const uid = (p = "f") => `${p}${++uidCounter}`;

class OfflineError extends Error {}

async function api(path, { method = "GET", body, timeout = 0 } = {}) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  const ctl = timeout ? new AbortController() : null;
  const timer = ctl && setTimeout(() => ctl.abort(), timeout);
  try { res = await fetch(path, ctl ? { ...opts, signal: ctl.signal } : opts); }
  catch { if (!state.local) Offline.mark(""); throw new OfflineError(`Your ${computer()} can't be reached right now.`); }
  finally { if (timer) clearTimeout(timer); }
  if (!state.local) {
    const off = res.headers.get("X-Budget-Offline");
    if (off != null) Offline.mark(off === "none" ? "" : off);
    else if (res.ok) Offline.clear();
    if (off === "none" || (res.status >= 502 && res.status <= 504)) throw new OfflineError(`Your ${computer()} can't be reached right now.`);
  }
  if (res.status === 401 && !state.local) { location.replace("/login"); throw new Error("Please sign in"); }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") msg = j.detail;
      else if (Array.isArray(j.detail)) msg = j.detail.map((d) => d.msg.replace(/^Value error, /, "")).join("; ");
    } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

/* --- On a phone: offline banner and expenses waiting to be sent ----------------
   When the Mac is asleep or out of reach, the phone shows the last numbers it saw
   (sw.js keeps them) and new expenses wait here until the Mac is back. Each has
   an id, so sending one twice never adds it twice. */

const Offline = {
  since: null,
  mark(savedAt) { this.since = savedAt || this.since || ""; this.draw(); },
  clear() { if (this.since !== null) { this.since = null; this.draw(); } },
  draw() {
    let el = $("#offline");
    const waiting = Outbox.items().length;
    if (this.since === null && !waiting) { el?.remove(); return; }
    if (!el) {
      el = document.createElement("div");
      el.id = "offline";
      el.className = "fixed left-1/2 -translate-x-1/2 z-40 rounded-full text-xs px-3.5 py-1.5 shadow-lg whitespace-nowrap";
      // Fixed colours, not theme ones: it must stand out on every theme, light or dark.
      Object.assign(el.style, { top: "calc(env(safe-area-inset-top) + 64px)", background: "rgba(15,23,42,.92)", color: "#fff" });
      document.body.append(el);
    }
    const at = this.since ? new Date(this.since) : null;
    const when = at && !isNaN(at) ? ` · as of ${at.toDateString() === new Date().toDateString() ? "" : fmtDate(isoOf(at)) + " "}${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}` : "";
    el.textContent = [this.since !== null ? `${computer()} not reachable${when}` : "", waiting ? `${waiting} waiting to send` : ""].filter(Boolean).join(" · ");
  },
};

const Outbox = {
  KEY: "budget-outbox",
  items() { try { return JSON.parse(localStorage.getItem(this.KEY) || "[]"); } catch { return []; } },
  save(list) { try { localStorage.setItem(this.KEY, JSON.stringify(list)); } catch { /* storage full or blocked */ } Offline.draw(); },
  add(body) { this.save([...this.items(), body]); },
  busy: false,
  async flush() {
    if (this.busy || state.local || !this.items().length) return;
    this.busy = true;
    let sent = 0;
    try {
      for (const body of this.items()) {
        try { await api("/api/expenses", { method: "POST", body, timeout: 10000 }); }
        catch (err) {
          if (err instanceof OfflineError || /sign in/i.test(err.message)) break;   // try again later
          toast(`Couldn't add ${body.merchant}: ${err.message}`, "error");          // the Mac refused it: drop it
        }
        this.save(this.items().filter((x) => x.client_id !== body.client_id));
        sent += 1;
      }
    } finally { this.busy = false; }
    if (sent) { toast(`Sent ${sent === 1 ? "1 expense" : `${sent} expenses`} saved on this phone`); render(); }
  },
};

/* --- Desktop app (pywebview) ------------------------------------------- */

const desktop = () => window.pywebview?.api;

// Dropping a file anywhere outside the import box would replace the page.
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

// In the app window there is no browser download bar, so export goes through
// a native Save dialog instead of following the link.
document.addEventListener("click", async (e) => {
  const link = e.target.closest('a[href="/api/export.csv"]');
  if (!link || !desktop()) return;
  e.preventDefault();
  try {
    const path = await desktop().export_csv();
    if (path) toast(`Exported to ${path.split("/").pop()}`);
  } catch (err) { toast(`Export failed: ${err.message || err}`, "error"); }
});

/** A short message at the bottom. `action` adds a button, e.g. { label: "Undo", run }. */
function toast(msg, kind = "ok", ms = null, action = null) {
  const el = $("#toast");
  $("[data-msg]", el).textContent = msg;
  el.classList.remove("hidden", "bg-red-600", "text-white", "bg-slate-900", "text-slate-50");
  el.classList.add(...(kind === "error" ? ["bg-red-600", "text-white"] : ["bg-slate-900", "text-slate-50"]));
  const btn = $("[data-action]", el);
  btn.classList.toggle("hidden", !action);
  btn.textContent = action?.label || "";
  btn.onclick = action ? () => { el.classList.add("hidden"); action.run(); } : null;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.add("hidden"), ms ?? (action ? 6000 : kind === "error" ? 5000 : 2500));
}

function openModal(title, contentEl) {
  $("#modal-title").textContent = title;
  $("#modal-body").replaceChildren(contentEl);
  $("#modal").classList.remove("hidden");
  document.body.style.overflow = "hidden";
}
function closeModal() {
  $("#modal").classList.add("hidden");
  $("#modal-body").replaceChildren();
  document.body.style.overflow = "";
}
$("#modal-close").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

async function loadCategories() {
  state.categories = await api("/api/categories");
}
const categoryById = (id) => state.categories.find((c) => c.id === id);

function categoryOptions(selected, { all = true, uncategorized = true } = {}) {
  return [
    all ? `<option value="">All categories</option>` : "",
    uncategorized ? `<option value="none" ${selected === "none" ? "selected" : ""}>Uncategorized</option>` : "",
    ...state.categories.map((c) =>
      `<option value="${c.id}" ${String(selected) === String(c.id) ? "selected" : ""}>${esc(c.name)}</option>`),
  ].join("");
}

const SOURCE_TAGS = {
  learned: ["learned", "bg-emerald-100 text-emerald-700"],
  fuzzy: ["learned · similar", "bg-emerald-100 text-emerald-700"],
  rule: ["rule", "bg-sky-100 text-sky-700"],
  ai: ["AI", "bg-violet-100 text-violet-700"],
};
function sourceTag(source) {
  const t = SOURCE_TAGS[source];
  return t ? `<span class="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${t[1]}">${t[0]}</span>` : "";
}

/** A round badge in the category's colour with its first letter. */
function categoryAvatar(name, color) {
  if (!name) return `<span class="w-9 h-9 shrink-0 rounded-full bg-amber-100 text-amber-700 inline-flex items-center justify-center text-sm font-semibold">?</span>`;
  return `<span class="cat-avatar w-9 h-9 shrink-0 rounded-full inline-flex items-center justify-center text-sm font-semibold"
    style="--c:${esc(color)}">${esc([...name][0].toUpperCase())}</span>`;
}

const weekdayLong = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
/** "Today", "Yesterday", or "Mon 5 Oct". */
function friendlyDate(iso) {
  if (iso === todayISO()) return "Today";
  if (iso === addDaysISO(todayISO(), -1)) return "Yesterday";
  const [y, m, d] = iso.split("-").map(Number);
  const label = weekdayLong.format(new Date(y, m - 1, d));
  return y === new Date().getFullYear() ? label : `${label} ${y}`;
}

const ICONS = {
  calendar: `<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/></svg>`,
};

/** A DD/MM/YYYY text box with a native date picker behind the calendar button. */
function dateField(name, iso = "", placeholder = "DD/MM/YYYY") {
  return `<div class="relative" data-date-field>
    <input name="${name}" class="input pr-10" inputmode="numeric" autocomplete="off"
           placeholder="${placeholder}" value="${iso ? fmtDate(iso) : ""}">
    <span class="absolute right-0 top-0 bottom-0 w-10 flex items-center justify-center text-slate-400 pointer-events-none">${ICONS.calendar}</span>
    <input type="date" tabindex="-1" aria-hidden="true" data-native
           class="absolute right-0 top-0 bottom-0 w-10 opacity-0 cursor-pointer">
  </div>`;
}
function wireDateFields(root) {
  $$("[data-date-field]", root).forEach((wrap) => {
    const text = $("input[name]", wrap);
    const native = $("[data-native]", wrap);
    const sync = () => { native.value = parseDate(text.value) || ""; };
    sync();
    text.addEventListener("change", sync);
    native.addEventListener("click", () => { sync(); try { native.showPicker(); } catch { /* unsupported */ } });
    native.addEventListener("change", () => {
      text.value = fmtDate(native.value);
      text.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
}

function destroyCharts() {
  state.charts.forEach((c) => c.destroy());
  state.charts = [];
}

/* ===========================================================================
   Expense form (used by "Add" and the edit dialog)
   ======================================================================== */

/** Categories you use most first; the add form shows the top few. */
const categoriesByUse = () => [...state.categories].sort((a, b) => (b.expense_count || 0) - (a.expense_count || 0));
const TOP_CHIPS = 5;

function expenseForm({ expense = null, onSaved, merchants = [] }) {
  const isEdit = !!expense;
  const hasExtras = !!(expense?.note || expense?.amount_cents < 0);
  const id = uid();
  const f = {
    categoryId: expense ? expense.category_id : null,
    source: expense?.category_id ? (expense.category_source || "manual") : null,
    // Once you tap a category yourself, suggestions stop overriding it.
    userPicked: isEdit && expense.category_id != null,
    seq: 0,
    showAll: false,
  };
  const amountValue = expense ? (Math.abs(expense.amount_cents) / 100).toFixed(2).replace(".", ",") : "";

  const el = document.createElement("form");
  el.className = "space-y-5";
  el.noValidate = true;
  el.innerHTML = `
    <div>
      <label class="label" for="${id}-amount">Amount</label>
      <div class="relative">
        <input id="${id}-amount" name="amount" class="input !text-2xl font-semibold tabular py-3 pr-10"
               inputmode="decimal" autocomplete="off" placeholder="0,00" value="${amountValue}">
        <span class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 text-xl">€</span>
      </div>
    </div>
    <div>
      <label class="label" for="${id}-merchant">Where?</label>
      <input id="${id}-merchant" name="merchant" class="input" autocomplete="off" autocapitalize="words"
             placeholder="e.g. Mercadona" value="${esc(expense?.merchant || "")}">
      ${merchants.length ? `<div data-merchants class="flex flex-wrap gap-1.5 mt-2">
        ${merchants.map((m) => `<button type="button" data-merchant="${esc(m)}" class="rounded-full bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs px-2.5 py-1">${esc(m)}</button>`).join("")}
      </div>` : ""}
    </div>
    <div>
      <div class="flex items-center gap-2 mb-1.5 min-h-[20px]">
        <span class="label !mb-0">Category</span><span data-tag></span>
        <span data-thinking class="hidden text-[11px] text-slate-400">asking AI…</span>
      </div>
      <div data-chips class="flex flex-wrap gap-2"></div>
      <p data-hint class="hidden text-xs text-amber-700 mt-2"></p>
    </div>
    <div>
      <label class="label">When?</label>
      <div class="flex items-center gap-2">
        <div class="flex-1 min-w-0 sm:flex-none sm:w-44">${dateField("date", expense?.date || todayISO())}</div>
        <button type="button" data-day="0" class="chip shrink-0 border-slate-200 text-slate-600 hover:border-slate-400 !px-2.5">Today</button>
        <button type="button" data-day="-1" class="chip shrink-0 border-slate-200 text-slate-600 hover:border-slate-400 !px-2.5">Yesterday</button>
      </div>
    </div>
    <details ${hasExtras ? "open" : ""} class="group">
      <summary class="cursor-pointer list-none text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1">
        <span data-chevron class="transition-transform inline-block">›</span> More options
      </summary>
      <div class="mt-3 space-y-3">
        <div>
          <label class="label" for="${id}-note">Note</label>
          <input id="${id}-note" name="note" class="input" autocomplete="off" value="${esc(expense?.note || "")}">
        </div>
        <label class="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
          <input type="checkbox" name="refund" class="rounded border-slate-300" ${expense?.amount_cents < 0 ? "checked" : ""}>
          This is a refund (money back)
        </label>
        ${isEdit ? "" : `<label class="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
          <input type="checkbox" name="repeat" class="rounded border-slate-300">
          Repeat every month <span class="text-slate-400">(a bill like Spotify or the gym)</span>
        </label>`}
      </div>
    </details>
    ${expense?.recurring_id ? `<p class="text-sm text-slate-500 -mt-2">↻ This comes from a monthly bill.
      <a href="#/settings?open=bills" class="underline">Change or stop it</a></p>` : ""}
    <p data-error class="hidden text-sm text-red-600"></p>
    <div data-actions class="flex flex-wrap items-center gap-2">
      <button type="submit" class="btn btn-primary py-3 flex-1 sm:flex-none sm:px-8">${isEdit ? "Save changes" : "Add expense"}</button>
    </div>`;
  wireDateFields(el);

  const chips = $("[data-chips]", el);
  function renderChips() {
    const ordered = categoriesByUse();
    let shown = ordered;
    if (!f.showAll && ordered.length > TOP_CHIPS + 1) {
      shown = ordered.slice(0, TOP_CHIPS);
      const picked = categoryById(f.categoryId);
      if (picked && !shown.includes(picked)) shown.push(picked);
    }
    chips.innerHTML = shown.map((c) => {
      const on = c.id === f.categoryId;
      return `<button type="button" data-cat="${c.id}" class="chip ${on ? "text-white border-transparent shadow-sm" : "bg-surface border-slate-200 text-slate-700 hover:border-slate-400"}"
                style="${on ? `background:${esc(c.color)}` : ""}">
          <span class="w-2 h-2 rounded-full ${on ? "bg-white/80" : ""}" style="${on ? "" : `background:${esc(c.color)}`}"></span>${esc(c.name)}
        </button>`;
    }).join("") + (shown.length < ordered.length
      ? `<button type="button" data-more-cats class="chip border-dashed border-slate-300 text-slate-500 hover:text-slate-900">${ordered.length - shown.length} more…</button>` : "");
    $("[data-tag]", el).innerHTML = f.categoryId && !f.userPicked ? sourceTag(f.source) : "";
  }
  chips.addEventListener("click", (e) => {
    if (e.target.closest("[data-more-cats]")) { f.showAll = true; renderChips(); return; }
    const b = e.target.closest("[data-cat]");
    if (!b) return;
    const cid = Number(b.dataset.cat);
    f.categoryId = f.categoryId === cid ? null : cid;
    f.userPicked = f.categoryId !== null;
    f.source = f.categoryId ? "manual" : null;
    $("[data-hint]", el).classList.add("hidden");
    renderChips();
  });
  renderChips();

  // --- live category suggestion while typing the merchant ---------------
  const hint = (text) => {
    const h = $("[data-hint]", el);
    h.textContent = text || "";
    h.classList.toggle("hidden", !text);
  };
  async function suggest(useAI) {
    const merchant = el.merchant.value.trim();
    const seq = ++f.seq;
    if (f.userPicked) return;
    if (!merchant) { f.categoryId = null; f.source = null; hint(""); renderChips(); return; }
    if (useAI) $("[data-thinking]", el).classList.remove("hidden");
    try {
      const s = await api(`/api/suggest?merchant=${encodeURIComponent(merchant)}&ai=${useAI ? 1 : 0}`);
      if (seq !== f.seq || f.userPicked) return;  // a newer keystroke or a manual pick wins
      f.categoryId = s.category_id;
      f.source = s.source;
      hint(s.category_id ? "" : (useAI && s.ai_enabled
        ? "Couldn't guess this one. Pick a category and it'll be remembered."
        : useAI ? "New merchant. Pick a category and it'll be remembered next time." : ""));
      renderChips();
    } catch { /* suggestions are a nice-to-have */ }
    finally { if (seq === f.seq) $("[data-thinking]", el).classList.add("hidden"); }
  }
  const quickSuggest = debounce(() => suggest(false), 120);
  const slowSuggest = debounce(() => { if (!f.categoryId) suggest(true); }, 900);
  el.merchant.addEventListener("input", () => { quickSuggest(); slowSuggest(); });
  el.merchant.addEventListener("blur", () => { if (!f.categoryId && el.merchant.value.trim()) suggest(true); });
  $("[data-merchants]", el)?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-merchant]");
    if (!b) return;
    el.merchant.value = b.dataset.merchant;
    suggest(false);
    if (!el.amount.value) el.amount.focus();
  });

  $$("[data-day]", el).forEach((b) => b.addEventListener("click", () => {
    el.date.value = fmtDate(addDaysISO(todayISO(), Number(b.dataset.day)));
    el.date.dispatchEvent(new Event("change"));
  }));

  // --- submit ------------------------------------------------------------
  const showError = (msg) => {
    const p = $("[data-error]", el);
    p.textContent = msg || "";
    p.classList.toggle("hidden", !msg);
  };
  el.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    showError("");
    const amount = parseAmount(el.amount.value);
    if (!(amount > 0)) { showError("Enter an amount, like 12,50."); el.amount.focus(); return; }
    const merchant = el.merchant.value.trim();
    if (!merchant) { showError("Enter where you spent it."); el.merchant.focus(); return; }
    const date = parseDate(el.date.value);
    if (!date) { showError("Enter the date as DD/MM/YYYY."); el.date.focus(); return; }
    const body = {
      amount: (el.refund.checked ? -amount : amount).toFixed(2),
      merchant,
      date,
      note: el.note.value.trim() || null,
      category_id: f.categoryId,
      category_source: f.categoryId ? (f.userPicked ? "manual" : f.source) : null,
      ...(!isEdit && el.repeat?.checked ? { repeat_monthly: true } : {}),
      ...(!isEdit ? { client_id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}` } : {}),
    };
    const btn = $("button[type=submit]", el);
    btn.disabled = true;
    try {
      const saved = await api(isEdit ? `/api/expenses/${expense.id}` : "/api/expenses",
                              { method: isEdit ? "PUT" : "POST", body, timeout: state.local ? 0 : 10000 });
      onSaved?.(saved);
    } catch (err) {
      if (err instanceof OfflineError && !isEdit) {
        // Keep it on the phone; it's sent (once) when the Mac is back.
        Outbox.add(body);
        onSaved?.({ ...body, pending: true, amount_cents: Math.round(Number(body.amount) * 100) });
        return;
      }
      showError(err.message);
    } finally {
      btn.disabled = false;
    }
  });

  el.clearForm = () => {
    el.amount.value = "";
    el.merchant.value = "";
    el.note.value = "";
    el.refund.checked = false;
    if (el.repeat) el.repeat.checked = false;
    f.categoryId = null; f.source = null; f.userPicked = false; f.showAll = false; f.seq++;
    hint(""); showError(""); renderChips();
    el.amount.focus();
  };
  return el;
}

function openEditExpense(expense, onChange) {
  const form = expenseForm({
    expense,
    onSaved: () => { closeModal(); toast("Changes saved"); onChange?.(); },
  });
  const actions = $("[data-actions]", form);
  const del = document.createElement("button");
  del.type = "button";
  del.className = "btn btn-ghost text-red-600 hover:bg-red-50 ml-auto";
  del.textContent = "Delete";
  let armed = false;
  del.addEventListener("click", async () => {
    if (!armed) {
      armed = true;
      del.textContent = "Tap again to delete";
      del.className = "btn btn-danger ml-auto";
      setTimeout(() => { if (armed) { armed = false; del.textContent = "Delete"; del.className = "btn btn-ghost text-red-600 hover:bg-red-50 ml-auto"; } }, 4000);
      return;
    }
    await api(`/api/expenses/${expense.id}`, { method: "DELETE" });
    closeModal();
    onChange?.();
    toast("Expense deleted", "ok", null, { label: "Undo", run: async () => {
      await api("/api/expenses", { method: "POST", body: {
        amount: (expense.amount_cents / 100).toFixed(2), merchant: expense.merchant, date: expense.date,
        note: expense.note || null, category_id: expense.category_id,
        category_source: expense.category_id ? (expense.category_source || "manual") : null,
      } });
      toast("Expense restored");
      onChange?.();
    } });
  });
  actions.append(del);
  openModal("Edit expense", form);
}

function expenseRow(e, { showDate = true } = {}) {
  const refund = e.amount_cents < 0;
  // Each part is HTML-safe already.
  const details = [e.category_name ? esc(e.category_name) : `<span class="text-amber-700">Needs a category</span>`];
  if (showDate) details.push(friendlyDate(e.date));
  if (e.recurring_id) details.push("Monthly");
  if (e.note) details.push(esc(e.note));
  return `<button type="button" data-expense="${e.id}" class="w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-slate-50 focus:bg-slate-50 focus:outline-none">
    ${categoryAvatar(e.category_name, e.category_color)}
    <div class="min-w-0 flex-1">
      <div class="font-medium text-slate-900 truncate">${esc(e.merchant)}</div>
      <div class="text-xs text-slate-500 truncate mt-0.5">${details.join(" · ")}</div>
    </div>
    <div class="font-semibold tabular shrink-0 ${refund ? "text-emerald-600" : "text-slate-900"}">${refund ? "+" : ""}${fmtMoney(Math.abs(e.amount_cents))}</div>
  </button>`;
}

function wireExpenseRows(root, items, onChange) {
  root.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-expense]");
    if (!b) return;
    const e = items.find((x) => x.id === Number(b.dataset.expense));
    if (e) openEditExpense(e, onChange);
  });
}

/* ===========================================================================
   Views
   ======================================================================== */

/** Merchants you've used most lately, for one-tap filling. */
async function frequentMerchants(n = 6) {
  try {
    const { items } = await api("/api/expenses?limit=150&sort=date&order=desc");
    const counts = new Map();
    for (const e of items) if (e.amount_cents > 0) counts.set(e.merchant, (counts.get(e.merchant) || 0) + 1);
    return [...counts].filter(([, c]) => c > 1).sort((a, b) => b[1] - a[1]).slice(0, n).map(([m]) => m);
  } catch { return []; }
}

async function viewAdd(root, params) {
  root.innerHTML = `
    <section class="field bleed relative overflow-hidden -mt-5" data-add-field>
      <div class="field-deep disc w-[30rem] -right-52 -top-60" aria-hidden="true"></div>
      <div class="relative max-w-lg mx-auto px-4 pt-6 pb-12">
        <h1 class="text-lg font-bold">New expense</h1>
        <div data-amount class="amount-field mt-4"></div>
        <p data-result class="text-base sm:text-[17px] font-semibold mt-3 min-h-[1.5rem] tabular" aria-live="polite"></p>
        <p data-change class="mt-3 min-h-[2rem]"></p>
      </div>
    </section>
    <div class="sheet bleed"><div class="max-w-lg mx-auto px-4"><div class="card p-5" data-form></div></div></div>`;
  const [merchants, status] = await Promise.all([frequentMerchants(), api("/api/budgets/status").catch(() => null)]);
  const form = expenseForm({
    merchants,
    onSaved: async (saved) => {
      form.clearForm();
      if (saved.pending) {
        toast(`Saved ${fmtMoney(Math.abs(saved.amount_cents))} · ${saved.merchant} on this phone. It'll be sent when your ${computer()} is reachable.`);
        return;
      }
      await loadCategories();   // keeps the "most used" chips up to date
      Object.assign(st, await api("/api/budgets/status").catch(() => st));
      refreshState(st);
      preview();
      toast(`Added ${fmtMoney(Math.abs(saved.amount_cents))} · ${saved.merchant}`, "ok", null, {
        label: "Undo",
        run: async () => { await api(`/api/expenses/${saved.id}`, { method: "DELETE" }); toast("Removed"); refreshState(); },
      });
    },
  });
  $("[data-form]", root).append(form);
  // The amount is typed straight onto the field (still part of the form through its form attribute).
  form.id = form.id || `add-${uid()}`;
  form.amount.setAttribute("form", form.id);
  $("[data-amount]", root).append(form.amount.closest("div").parentElement);
  form.amount.classList.remove("!text-2xl", "font-semibold", "py-3", "pr-10");
  form.amount.setAttribute("aria-label", "Amount in euros");

  const st = status || null;
  // The preview colours the whole top band (header included), so it's set on <body>.
  const field = document.body;
  /** What the month will look like after this expense, and whether the colour changes. */
  function preview() {
    const result = $("[data-result]", root), change = $("[data-change]", root);
    const amount = parseAmount(form.amount.value);
    const date = parseDate(form.date.value);
    const month = st?.month;
    if (!month || month.overall.limit_cents == null || !(amount > 0) || form.refund.checked || !date || date < month.start || date > month.end) {
      field.style.removeProperty("--field"); field.style.removeProperty("--field-deep");
      result.textContent = month && month.overall.limit_cents != null && month.overall.left_cents >= 0
        ? `${fmtMoney(month.overall.left_cents)} left this month` : "";
      change.innerHTML = "";
      return;
    }
    const cents = Math.round(amount * 100);
    const m = month.overall;
    const after = { ...m, spent_cents: m.spent_cents + cents, left_cents: m.left_cents - cents };
    const before = budgetState(m, month), next = budgetState(after, month);
    const upcoming = month.bills?.upcoming_cents || 0;
    const perDay = month.days_left ? Math.max(0, after.left_cents - upcoming) / month.days_left : 0;
    result.innerHTML = after.left_cents < 0
      ? `After this: <b class="font-black">${fmtMoney(-after.left_cents)}</b> over budget`
      : `After this: <b class="font-black">${fmtMoney(after.left_cents)}</b> left, about <b class="font-black">${fmtMoney(Math.floor(perDay))}</b> a day`;
    field.style.setProperty("--field", `var(--field-${next})`);
    field.style.setProperty("--field-deep", `var(--field-${next}-deep)`);
    change.innerHTML = `<span class="state-pill"><i></i>${next === before ? `Still ${STATE_WORD[next]}` : `Turns ${STATE_WORD[next]}`}</span>`;
  }
  form.amount.addEventListener("input", preview);
  form.date.addEventListener("change", preview);
  form.refund.addEventListener("change", preview);
  // Coming from a day in the calendar heatmap: start on that date.
  const day = params?.get("date");
  if (day && parseDate(day)) { form.date.value = fmtDate(day); form.date.dispatchEvent(new Event("change")); }
  preview();
  setTimeout(() => form.amount.focus(), 0);
}

async function viewTransactions(root, params) {
  const F = state.txFilters;
  const FILTER_KEYS = ["q", "category_id", "date_from", "date_to"];
  // Links from Home can pre-set filters: #/transactions?category_id=3&date_from=...
  if ([...params.keys()].length) {
    Object.assign(F, { q: "", category_id: "", date_from: "", date_to: "" });
    for (const k of FILTER_KEYS) if (params.has(k)) F[k] = params.get(k);
  }
  const activeFilters = () => ["category_id", "date_from", "date_to"].filter((k) => F[k]).length + (F.sort !== "date:desc" ? 1 : 0);
  const review = (await api("/api/email/status").catch(() => ({ review_count: 0 }))).review_count;

  root.innerHTML = `
    <div class="flex items-center justify-between gap-2 mb-4">
      <h1 class="text-xl font-semibold text-slate-900">Transactions</h1>
      <a href="#/import" class="btn btn-secondary !py-1.5">Import${review ? ` <span class="rounded-full bg-amber-500 text-white text-[10px] font-semibold px-1.5">${review}</span>` : ""}</a>
    </div>
    ${review ? `<a href="#/import" class="flex items-center gap-3 mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 hover:bg-amber-100">
      <span class="flex-1">${plural(review, "payment from your iPhone needs", "payments from your iPhone need")} a quick check</span>
      <span class="font-medium">Review →</span></a>` : ""}
    <div class="flex gap-2 mb-3">
      <div class="relative flex-1">
        <svg class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input name="q" class="input !pl-9" placeholder="Search" value="${esc(F.q)}" autocomplete="off">
      </div>
      <button type="button" data-toggle-filters class="btn btn-secondary shrink-0">Filters<span data-filter-count></span></button>
    </div>
    <div data-filters class="hidden card p-4 mb-3">
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="col-span-2 sm:col-span-1">
          <label class="label">Category</label>
          <select name="category_id" class="input">${categoryOptions(F.category_id)}</select>
        </div>
        <div><label class="label">From</label>${dateField("date_from", F.date_from)}</div>
        <div><label class="label">To</label>${dateField("date_to", F.date_to)}</div>
        <div class="col-span-2 sm:col-span-1">
          <label class="label">Order</label>
          <select name="sort" class="input">
            <option value="date:desc">Newest first</option>
            <option value="date:asc">Oldest first</option>
            <option value="amount:desc">Biggest first</option>
            <option value="amount:asc">Smallest first</option>
            <option value="merchant:asc">Merchant A–Z</option>
          </select>
        </div>
      </div>
      <button type="button" data-clear class="link mt-3">Clear filters</button>
    </div>
    <p data-summary class="text-sm text-slate-500 mb-2 px-1"></p>
    <div data-list class="space-y-4"></div>
    <div class="text-center mt-4"><button data-more class="btn btn-secondary hidden">Load more</button></div>`;
  wireDateFields(root);
  $("[name=sort]", root).value = F.sort;
  const filters = $("[data-filters]", root);
  const showCount = () => {
    const n = activeFilters();
    $("[data-filter-count]", root).innerHTML = n ? ` <span class="rounded-full bg-accent text-on-accent text-[10px] font-semibold px-1.5">${n}</span>` : "";
  };
  if (activeFilters()) filters.classList.remove("hidden");
  showCount();
  $("[data-toggle-filters]", root).addEventListener("click", () => filters.classList.toggle("hidden"));

  const list = $("[data-list]", root);
  const more = $("[data-more]", root);
  let items = [];
  const PAGE = 100;

  function renderList() {
    if (!items.length) {
      list.innerHTML = `<div class="card p-8 text-center text-sm text-slate-400">
        ${F.q || activeFilters() ? "Nothing matches." : "No expenses yet. Tap + to add your first one."}</div>`;
      return;
    }
    if (!F.sort.startsWith("date")) {
      list.innerHTML = `<div class="card divide-y divide-slate-100 overflow-hidden">${items.map((e) => expenseRow(e)).join("")}</div>`;
      return;
    }
    // Newest/oldest first: one group per day, with the day's total.
    const groups = [];
    for (const e of items) {
      if (groups.at(-1)?.date !== e.date) groups.push({ date: e.date, items: [] });
      groups.at(-1).items.push(e);
    }
    list.innerHTML = groups.map((g) => `
      <section>
        <div class="flex justify-between px-1 mb-1.5 text-xs font-medium text-slate-500">
          <span>${friendlyDate(g.date)}</span>
          <span class="tabular">${fmtMoney(g.items.reduce((a, e) => a + e.amount_cents, 0))}</span>
        </div>
        <div class="card divide-y divide-slate-100 overflow-hidden">${g.items.map((e) => expenseRow(e, { showDate: false })).join("")}</div>
      </section>`).join("");
  }

  async function load(append = false) {
    const [sort, order] = F.sort.split(":");
    const qs = new URLSearchParams({ sort, order, limit: PAGE, offset: append ? items.length : 0 });
    for (const k of FILTER_KEYS) if (F[k]) qs.set(k, F[k]);
    const data = await api(`/api/expenses?${qs}`);
    items = append ? items.concat(data.items) : data.items;
    $("[data-summary]", root).textContent = data.count
      ? `${plural(data.count, "expense", "expenses")} · ${fmtMoney(data.total_cents)}` : "";
    renderList();
    more.classList.toggle("hidden", items.length >= data.count);
    showCount();
  }
  wireExpenseRows(list, { find: (fn) => items.find(fn) }, () => load());

  const reload = () => load().catch((e) => toast(e.message, "error"));
  $("[name=q]", root).addEventListener("input", debounce((e) => { F.q = e.target.value.trim(); reload(); }, 250));
  $("[name=category_id]", root).addEventListener("change", (e) => { F.category_id = e.target.value; reload(); });
  $("[name=sort]", root).addEventListener("change", (e) => { F.sort = e.target.value; reload(); });
  for (const k of ["date_from", "date_to"]) {
    $(`[name=${k}]`, root).addEventListener("change", (e) => {
      const v = e.target.value.trim();
      const iso = parseDate(v);
      if (v && !iso) { toast("Use DD/MM/YYYY for dates", "error"); return; }
      F[k] = iso || "";
      reload();
    });
  }
  $("[data-clear]", root).addEventListener("click", () => {
    Object.assign(F, { q: "", category_id: "", date_from: "", date_to: "", sort: "date:desc" });
    if (location.hash.includes("?")) location.hash = "#/transactions";
    else render();
  });
  more.addEventListener("click", () => load(true));
  await load();
}

/* ---------------------------------------------------------------------------
   Settings
   ------------------------------------------------------------------------ */

const settingsHooks = {};   // lets one section refresh another

const THEME_ORDER = ["auto", "verde", "azul", "mar", "ciruela", "teja", "tinta", "noche"];
const themeLabel = (name) => name === "auto" ? "Automatic" : Theme.THEMES[Theme.canonical(name)]?.label || "Automatic";

/** A theme as a small field: its colour with the deeper disc, and the app's ground below. */
function themeSwatch(name) {
  const tile = (t) => `<span class="relative flex-1 h-full overflow-hidden" style="background:#${t.field.green[0]}">
      <span class="absolute w-16 h-16 rounded-full -right-6 -top-7" style="background:#${t.field.green[1]}"></span>
      <span class="absolute left-0 right-0 bottom-0 h-5 rounded-t-lg" style="background:#${t.neutral[0]}"></span></span>`;
  const preview = name === "auto" ? tile(Theme.THEMES.verde) + tile(Theme.THEMES.noche) : tile(Theme.THEMES[name]);
  const on = Theme.choice === name;
  return `<button type="button" data-theme-pick="${name}" aria-pressed="${on}"
      class="text-left rounded-2xl border-2 p-1 transition ${on ? "border-slate-900" : "border-transparent hover:border-slate-200"}">
    <span class="flex h-20 rounded-xl overflow-hidden">${preview}</span>
    <span class="block text-sm text-center mt-1.5 ${on ? "font-bold text-slate-900" : "font-medium text-slate-600"}">${themeLabel(name)}</span>
  </button>`;
}

async function settingsAppearance(el) {
  const draw = () => {
    el.innerHTML = `
      <p class="text-sm text-slate-500 mb-3">A theme sets the colour when you're on plan; amber and red always mean the same. Automatic follows your ${computer()} or phone: Verde by day, Noche at night.</p>
      <div class="grid grid-cols-4 gap-2">${THEME_ORDER.map(themeSwatch).join("")}</div>`;
  };
  el.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-theme-pick]");
    if (!b) return;
    Theme.set(b.dataset.themePick);
    draw();
    settingsHooks.refreshSummaries?.();
    await savePrefs({ theme: Theme.choice });
  });
  draw();
}

async function settingsCategories(el) {
  el.innerHTML = `
    <p class="text-sm text-slate-500 mb-3">Rename, recolour or reorder your categories. Changes save by themselves.</p>
    <div data-cats class="divide-y divide-slate-100"></div>
    <form data-add-cat class="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-slate-100">
      <input type="color" name="color" value="#64748b" class="h-9 w-10 rounded border border-slate-300 cursor-pointer bg-surface">
      <input name="name" class="input flex-1 min-w-[10rem]" placeholder="New category" maxlength="40">
      <button class="btn btn-primary">Add</button>
    </form>
    <details class="mt-5">
      <summary class="cursor-pointer list-none text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1">
        <span data-chevron class="transition-transform inline-block">›</span> Learned merchants
      </summary>
      <p class="text-sm text-slate-500 my-3">When you pick or correct a category, Budget remembers it for that merchant. These always win.</p>
      <input data-rule-q class="input mb-3" placeholder="Filter merchants…">
      <div data-rules class="divide-y divide-slate-100 max-h-[28rem] overflow-y-auto"></div>
    </details>`;

  // --- categories ---------------------------------------------------------
  const catsEl = $("[data-cats]", el);
  function renderCats() {
    catsEl.innerHTML = state.categories.map((c, i) => `
      <div data-cat-row="${c.id}" class="py-2.5">
        <div class="flex items-center gap-2">
          <input type="color" data-color value="${esc(c.color)}" class="h-9 w-10 shrink-0 rounded border border-slate-300 cursor-pointer" title="Color">
          <input data-name value="${esc(c.name)}" maxlength="40" class="input flex-1 min-w-0">
          <span class="hidden sm:inline text-xs text-slate-400 w-20 text-right tabular">${c.expense_count} expense${c.expense_count === 1 ? "" : "s"}</span>
          <button data-move="-1" class="btn btn-ghost !px-2" ${i === 0 ? "disabled" : ""} title="Move up">↑</button>
          <button data-move="1" class="btn btn-ghost !px-2" ${i === state.categories.length - 1 ? "disabled" : ""} title="Move down">↓</button>
          <button data-del class="btn btn-ghost !px-2 text-slate-400 hover:text-red-600" title="Delete">✕</button>
        </div>
        <div data-del-panel class="hidden mt-2 ml-12 rounded-lg bg-red-50 p-3 text-sm">
          <p class="mb-2 text-red-800">Delete <b>${esc(c.name)}</b>?
            ${c.expense_count ? `Move its ${c.expense_count} expense${c.expense_count === 1 ? "" : "s"} and learned merchants to:` : "Move its learned merchants to:"}</p>
          <div class="flex flex-wrap gap-2">
            <select data-move-to class="input !w-auto">
              ${state.categories.filter((o) => o.id !== c.id).map((o) =>
                `<option value="${o.id}" ${o.name === "Other" ? "selected" : ""}>${esc(o.name)}</option>`).join("")}
              <option value="none">Uncategorized</option>
            </select>
            <button data-del-confirm class="btn btn-danger">Delete category</button>
            <button data-del-cancel class="btn btn-ghost">Cancel</button>
          </div>
        </div>
      </div>`).join("");
  }
  async function refreshCats() {
    await loadCategories();
    renderCats();
    settingsHooks.refreshSummaries?.();
  }
  async function patchCat(id, body) {
    try {
      await api(`/api/categories/${id}`, { method: "PATCH", body });
      toast("Saved");
      await refreshCats();
      settingsHooks.renderBudgets?.();
    } catch (e) {
      toast(e.message, "error");
      await refreshCats();
    }
  }
  catsEl.addEventListener("change", (e) => {
    const row = e.target.closest("[data-cat-row]");
    if (!row) return;
    const id = Number(row.dataset.catRow);
    if (e.target.matches("[data-color]")) patchCat(id, { color: e.target.value });
    if (e.target.matches("[data-name]")) {
      const name = e.target.value.trim();
      if (name && name !== categoryById(id)?.name) patchCat(id, { name });
      else e.target.value = categoryById(id)?.name || "";
    }
  });
  catsEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches("[data-name]")) e.target.blur();
  });
  catsEl.addEventListener("click", async (e) => {
    const row = e.target.closest("[data-cat-row]");
    if (!row) return;
    const id = Number(row.dataset.catRow);
    const panel = $("[data-del-panel]", row);
    if (e.target.closest("[data-move]")) {
      const ids = state.categories.map((c) => c.id);
      const i = ids.indexOf(id);
      const j = i + Number(e.target.closest("[data-move]").dataset.move);
      [ids[i], ids[j]] = [ids[j], ids[i]];
      state.categories = await api("/api/categories/reorder", { method: "POST", body: { ids } });
      renderCats();
    } else if (e.target.closest("[data-del]")) {
      panel.classList.toggle("hidden");
    } else if (e.target.closest("[data-del-cancel]")) {
      panel.classList.add("hidden");
    } else if (e.target.closest("[data-del-confirm]")) {
      const moveTo = $("[data-move-to]", row).value;
      try {
        await api(`/api/categories/${id}?move_to=${moveTo}`, { method: "DELETE" });
        toast("Category deleted");
        await refreshCats();
        loadRules();
        settingsHooks.renderBudgets?.();
      } catch (err) { toast(err.message, "error"); }
    }
  });
  $("[data-add-cat]", el).addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const name = form.name.value.trim();
    if (!name) return;
    try {
      await api("/api/categories", { method: "POST", body: { name, color: form.color.value } });
      form.name.value = "";
      toast(`Added ${name}`);
      await refreshCats();
      settingsHooks.renderBudgets?.();
    } catch (err) { toast(err.message, "error"); }
  });
  renderCats();

  // --- learned merchants ------------------------------------------------
  const rulesEl = $("[data-rules]", el);
  let rules = [];
  function renderRules() {
    const q = $("[data-rule-q]", el).value.trim().toLowerCase();
    const shown = rules.filter((r) => !q || r.merchant_norm.includes(q) || r.category_name.toLowerCase().includes(q));
    rulesEl.innerHTML = shown.length ? shown.map((r) => `
      <div data-rule="${esc(r.merchant_norm)}" class="flex items-center gap-2 py-2">
        <span class="flex-1 min-w-0 truncate font-medium text-slate-800">${esc(r.merchant_norm)}</span>
        <span class="hidden sm:inline text-xs text-slate-400">${r.hit_count}×</span>
        <select data-rule-cat class="input !w-32 sm:!w-48 shrink-0 !py-1 text-sm">${categoryOptions(r.category_id, { all: false, uncategorized: false })}</select>
        <button data-rule-del class="btn btn-ghost !px-2 text-slate-400 hover:text-red-600" title="Forget">✕</button>
      </div>`).join("")
      : `<p class="py-4 text-sm text-slate-400">${rules.length ? "No matches." : "Nothing learned yet. Add a few expenses and confirm their categories."}</p>`;
  }
  async function loadRules() {
    rules = await api("/api/rules");
    renderRules();
  }
  $("[data-rule-q]", el).addEventListener("input", renderRules);
  rulesEl.addEventListener("change", async (e) => {
    const row = e.target.closest("[data-rule]");
    if (!row || !e.target.matches("[data-rule-cat]")) return;
    await api(`/api/rules/${encodeURIComponent(row.dataset.rule)}`, { method: "PUT", body: { category_id: Number(e.target.value) } });
    toast("Saved");
    loadRules();
  });
  rulesEl.addEventListener("click", async (e) => {
    const row = e.target.closest("[data-rule]");
    if (!row || !e.target.closest("[data-rule-del]")) return;
    await api(`/api/rules/${encodeURIComponent(row.dataset.rule)}`, { method: "DELETE" });
    toast(`Forgot ${row.dataset.rule}`);
    loadRules();
  });
  await loadRules();

}

async function settingsBills(el) {
  async function draw() {
    const bills = await api("/api/recurring");
    el.innerHTML = `
      <p class="text-sm text-slate-500 mb-3">Bills are added by themselves on their day each month. Home counts them separately,
        so they don't make it look like you're overspending early in the month. To add one, tick
        <b>Repeat every month</b> under More options when you add the expense.</p>
      ${bills.length ? `<div class="divide-y divide-slate-100">${bills.map((b) => `
        <div data-bill="${b.id}" class="flex items-center gap-3 py-2.5">
          ${categoryAvatar(b.category_name, b.category_color)}
          <div class="flex-1 min-w-0">
            <div class="font-medium text-slate-900 truncate">${esc(b.merchant)}</div>
            <div class="text-xs text-slate-500">Every month on the ${ordinal(b.day)} · next ${friendlyDate(b.next_date)}</div>
          </div>
          <div class="relative w-24 shrink-0">
            <input data-bill-amount value="${(b.amount_cents / 100).toFixed(2).replace(".", ",")}" inputmode="decimal"
                   class="input !pr-6 text-right tabular" aria-label="Amount">
            <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">€</span>
          </div>
          <button data-bill-stop class="btn btn-ghost !px-2 text-slate-400 hover:text-red-600" title="Stop repeating">✕</button>
        </div>`).join("")}</div>`
      : `<p class="text-sm text-slate-400">No monthly bills yet.</p>`}`;
  }
  el.addEventListener("change", async (e) => {
    const row = e.target.closest("[data-bill]");
    if (!row || !e.target.matches("[data-bill-amount]")) return;
    const amount = parseAmount(e.target.value);
    if (!(amount > 0)) { toast("Enter an amount like 10,99", "error"); return draw(); }
    try {
      await api(`/api/recurring/${row.dataset.bill}`, { method: "PATCH", body: { amount: amount.toFixed(2) } });
      toast("New amount saved. It applies from the next bill.");
      settingsHooks.refreshSummaries?.();
    } catch (err) { toast(err.message, "error"); }
  });
  el.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches("[data-bill-amount]")) e.target.blur(); });
  el.addEventListener("click", async (e) => {
    const row = e.target.closest("[data-bill]");
    if (!row || !e.target.closest("[data-bill-stop]")) return;
    await api(`/api/recurring/${row.dataset.bill}`, { method: "DELETE" });
    toast("Stopped. Expenses it already added stay.");
    await draw();
    settingsHooks.refreshSummaries?.();
  });
  await draw();
}

const monthLong = (key) => monthName.format(dateObj(key + "-01"));

async function settingsSavings(el) {
  let sv = await api("/api/savings");
  const goalPct = () => sv.goal_cents ? Math.max(0, Math.min(100, (sv.total_cents / sv.goal_cents) * 100)) : 0;
  const money = (c) => (c / 100).toFixed(2).replace(".", ",").replace(/,00$/, "");

  function draw() {
    if (!sv.enabled) {
      el.innerHTML = `
        <p class="text-sm text-slate-500 mb-3">On the 1st of each month, whatever was left of last month's budget goes into savings
          (and if you overspent, it comes off). Add a goal, like a trip, to see how close you are.</p>
        <div class="flex flex-wrap items-end gap-2">
          <div class="w-40"><label class="label">Already saved <span class="font-normal text-slate-400">(optional)</span></label>
            <div class="relative"><input data-start inputmode="decimal" class="input !pr-7 text-right tabular" placeholder="0">
              <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">€</span></div></div>
          <button data-enable class="btn btn-primary">Turn on savings</button>
        </div>`;
      return;
    }
    const history = [
      ...sv.months.map((m) => ({ sort: m.month + "-99", label: monthLong(m.month),
        sub: m.limit_cents == null ? "No monthly budget was set"
          : `Spent ${fmtMoney(m.spent_cents)} of ${fmtMoneyShort(m.limit_cents)}`, cents: m.saved_cents })),
      ...sv.moves.map((m) => ({ sort: m.date, id: m.id, label: m.note || (m.amount_cents > 0 ? "Added" : "Taken out"),
        sub: friendlyDate(m.date), cents: m.amount_cents })),
    ].sort((a, b) => b.sort.localeCompare(a.sort));
    el.innerHTML = `
      <div class="flex items-baseline justify-between gap-3">
        <p class="display text-4xl font-semibold text-slate-900">${fmtMoney(sv.total_cents)}</p>
        <span class="text-xs text-slate-400">counting since ${monthLong(sv.start_month)}</span>
      </div>
      ${sv.goal_cents ? `<div class="mt-3">${bar(goalPct(), "rgb(var(--accent))", { thick: true })}
        <p class="text-sm text-slate-500 mt-1.5">${Math.round(goalPct())}% of ${esc(sv.goal_name || "your goal")} (${fmtMoneyShort(sv.goal_cents)})
          ${sv.total_cents < sv.goal_cents ? ` · ${fmtMoney(sv.goal_cents - sv.total_cents)} to go` : " · reached!"}</p></div>` : ""}
      <p class="text-sm text-slate-500 mt-3">On the 1st of each month, what's left of last month's budget is added here.</p>

      <h3 class="text-sm font-medium text-slate-700 mt-5 mb-2">Goal</h3>
      <form data-goal class="flex flex-wrap gap-2">
        <input name="goal_name" class="input flex-1 min-w-[9rem]" maxlength="60" placeholder="e.g. Lisbon trip" value="${esc(sv.goal_name || "")}">
        <div class="relative w-28"><input name="goal" inputmode="decimal" class="input !pr-7 text-right tabular" placeholder="Amount"
          value="${sv.goal_cents ? money(sv.goal_cents) : ""}"><span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">€</span></div>
        <button class="btn btn-secondary">Save goal</button>
        ${sv.goal_cents ? `<button type="button" data-clear-goal class="btn btn-ghost">Remove</button>` : ""}
      </form>

      <h3 class="text-sm font-medium text-slate-700 mt-5 mb-2">Add or take out money</h3>
      <form data-move class="flex flex-wrap gap-2">
        <div class="relative w-28"><input name="amount" inputmode="decimal" class="input !pr-7 text-right tabular" placeholder="0,00">
          <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">€</span></div>
        <input name="note" class="input flex-1 min-w-[9rem]" maxlength="200" placeholder="What for? (optional)">
        <button data-dir="1" class="btn btn-secondary">Add</button>
        <button data-dir="-1" class="btn btn-secondary">Take out</button>
      </form>

      ${history.length ? `<h3 class="text-sm font-medium text-slate-700 mt-5 mb-1">History</h3>
      <div class="divide-y divide-slate-100">${history.map((h) => `
        <div class="flex items-center gap-3 py-2 text-sm">
          <div class="flex-1 min-w-0"><div class="text-slate-800 truncate">${esc(h.label)}</div><div class="text-xs text-slate-500">${esc(h.sub)}</div></div>
          <span class="tabular font-medium ${h.cents < 0 ? "text-red-600" : "text-emerald-600"}">${h.cents > 0 ? "+" : ""}${fmtMoney(h.cents)}</span>
          ${h.id ? `<button data-del-move="${h.id}" class="btn btn-ghost !px-2 text-slate-400 hover:text-red-600" title="Remove">✕</button>` : `<span class="w-8"></span>`}
        </div>`).join("")}</div>` : ""}
      <button data-disable class="link mt-5">Turn off savings</button>`;
  }

  const update = async (fn) => {
    try { sv = await fn(); draw(); settingsHooks.refreshSummaries?.(); }
    catch (err) { toast(err.message, "error"); }
  };
  el.addEventListener("click", async (e) => {
    if (e.target.closest("[data-enable]")) {
      const start = $("[data-start]", el).value.trim();
      const amount = start ? parseAmount(start) : 0;
      if (start && !(amount >= 0)) return toast("Enter an amount like 200", "error");
      await update(async () => {
        await api("/api/savings", { method: "PUT", body: { enabled: true } });
        return amount > 0
          ? api("/api/savings/moves", { method: "POST", body: { amount: amount.toFixed(2), note: "Already saved" } })
          : api("/api/savings");
      });
      toast("Savings is on");
    } else if (e.target.closest("[data-disable]")) {
      await update(() => api("/api/savings", { method: "PUT", body: { enabled: false } }));
      toast("Savings is off. Turn it on again any time; nothing is lost.");
    } else if (e.target.closest("[data-clear-goal]")) {
      await update(() => api("/api/savings", { method: "PUT", body: { clear_goal: true } }));
    } else if (e.target.closest("[data-del-move]")) {
      await api(`/api/savings/moves/${e.target.closest("[data-del-move]").dataset.delMove}`, { method: "DELETE" });
      await update(() => api("/api/savings"));
    }
  });
  el.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    if (f.matches("[data-goal]")) {
      const goal = parseAmount(f.goal.value);
      if (!(goal > 0)) return toast("Enter the goal amount, like 500", "error");
      await update(() => api("/api/savings", { method: "PUT", body: { goal_name: f.goal_name.value.trim(), goal: goal.toFixed(2) } }));
      toast("Goal saved");
    } else if (f.matches("[data-move]")) {
      const amount = parseAmount(f.amount.value);
      if (!(amount > 0)) return toast("Enter an amount, like 50", "error");
      const dir = Number(e.submitter?.dataset.dir || 1);
      await update(() => api("/api/savings/moves", { method: "POST", body: { amount: (dir * amount).toFixed(2), note: f.note.value.trim() || null } }));
      toast(dir > 0 ? "Added to savings" : "Taken out of savings");
    }
  });
  draw();
}

const ordinal = (n) => `${n}${[11, 12, 13].includes(n % 100) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" })[n % 10] || "th"}`;

async function settingsAbout(el) {
  const status = await api("/api/status");
  const dot = (on) => `<span class="inline-block w-2 h-2 rounded-full mr-2 ${on ? "bg-emerald-500" : "bg-slate-300"}"></span>`;
  el.innerHTML = `
    <div class="text-sm text-slate-600 space-y-2">
      <p>${dot(status.ai_enabled)}AI category suggestions: <b>${status.ai_enabled ? "on" : "off"}</b>
        <span class="text-slate-400">${status.ai_enabled ? "(only merchant names are sent to Claude)" : "(set ANTHROPIC_API_KEY)"}</span></p>
      <p>${dot(status.quickadd_enabled)}Quick-add for iPhone Shortcuts: <b>${status.quickadd_enabled ? "on" : "off"}</b>
        <span class="text-slate-400">${status.quickadd_enabled ? "" : "(set QUICKADD_TOKEN)"}</span></p>
      <p class="text-xs text-slate-400 pt-1">These go in a <code class="bg-slate-100 rounded px-1">.env</code> file in
        <code class="bg-slate-100 rounded px-1 break-all">${esc(status.data_dir.replace(/^\/Users\/[^/]+/, "~"))}</code>.
        Quit and reopen Budget after changing it. The README explains each one.</p>
    </div>`;
}

async function viewSettings(root, params) {
  const local = state.local;
  settingsHooks.renderBudgets = null;
  const sections = [
    { id: "appearance", title: "Appearance", init: settingsAppearance },
    { id: "budget", title: "Budget", init: async (el) => { settingsHooks.renderBudgets = await settingsBudgets(el); } },
    { id: "savings", title: "Savings", init: settingsSavings },
    { id: "bills", title: "Monthly bills", init: settingsBills },
    { id: "categories", title: "Categories", init: settingsCategories },
    local && { id: "gmail", title: "Apple Pay via Gmail", init: settingsGmail },
    local && { id: "phone", title: "Use on your phone", init: settingsPhone },
    !local && { id: "device", title: "This device", init: settingsThisPhone },
    { id: "data", title: "Your data", init: settingsData },
    { id: "about", title: "About", init: settingsAbout },
  ].filter(Boolean);

  root.innerHTML = `
    <div class="max-w-2xl mx-auto">
      <h1 class="text-xl font-semibold text-slate-900 mb-4">Settings</h1>
      <div class="card divide-y divide-slate-100 overflow-hidden">
        ${sections.map((sec) => `
          <details data-section="${sec.id}">
            <summary class="flex items-center gap-3 px-5 py-4 cursor-pointer list-none hover:bg-slate-50">
              <span class="flex-1 min-w-0">
                <span class="block font-medium text-slate-900">${sec.title}</span>
                <span data-summary class="block text-sm text-slate-500 truncate"></span>
              </span>
              <span data-chevron class="inline-block text-slate-400 text-xl leading-none transition-transform">›</span>
            </summary>
            <div data-body class="px-5 pb-5 pt-1"></div>
          </details>`).join("")}
      </div>
    </div>`;

  for (const sec of sections) {
    const details = $(`[data-section="${sec.id}"]`, root);
    details.addEventListener("toggle", async () => {
      if (!details.open || details.dataset.ready) return;
      details.dataset.ready = "1";
      try { await sec.init($("[data-body]", details)); }
      catch (err) { $("[data-body]", details).innerHTML = `<p class="text-sm text-red-600">${esc(err.message)}</p>`; }
    });
  }

  const summary = (id, text) => { const el = $(`[data-section="${id}"] [data-summary]`, root); if (el) el.textContent = text; };
  settingsHooks.refreshSummaries = async () => {
    summary("appearance", themeLabel(Theme.choice));
    summary("categories", plural(state.categories.length, "category", "categories"));
    summary("data", "Backed up automatically every day");
    summary("device", "Signed in over Wi-Fi");
    summary("about", "Optional extras");
    const [limits, gmail, phone, bills, sv] = await Promise.all([
      api("/api/budgets").catch(() => []),
      local ? api("/api/email/settings").catch(() => null) : null,
      local ? api("/api/phone").catch(() => null) : null,
      api("/api/recurring").catch(() => []),
      api("/api/savings").catch(() => null),
    ]);
    if (sv) summary("savings", !sv.enabled ? "Off" : [`${fmtMoney(sv.total_cents)} saved`,
      sv.goal_cents && `${Math.round(Math.max(0, Math.min(100, sv.total_cents / sv.goal_cents * 100)))}% of ${sv.goal_name || "your goal"}`].filter(Boolean).join(" · "));
    summary("bills", bills.length
      ? `${plural(bills.length, "bill", "bills")} · ${fmtMoney(bills.reduce((a, b) => a + b.amount_cents, 0))} a month` : "None yet");
    const overall = (p) => limits.find((l) => l.category_id == null && l.period === p);
    const parts = [overall("month") && `${fmtMoneyShort(overall("month").limit_cents)} a month`,
                   overall("week") && `${fmtMoneyShort(overall("week").limit_cents)} a week`].filter(Boolean);
    summary("budget", parts.length ? parts.join(" · ") : "No budget set yet");
    if (gmail) summary("gmail", gmail.enabled && gmail.address ? `On · ${gmail.address}` : "Off");
    if (phone) summary("phone", phone.running ? "On" : "Off");
  };
  const open = params?.get("open");
  if (open) $(`[data-section="${open}"]`, root)?.setAttribute("open", "");
  await settingsHooks.refreshSummaries();
}

/* ===========================================================================
   Budgets: progress bars and the Settings section
   ======================================================================== */

// Status colors are reserved for budget state and always come with a text label.
const LEVELS = {
  green: { color: "#0ca30c", label: "On track", icon: "✓" },
  amber: { color: "#fab219", label: "Close to limit", icon: "!" },
  red: { color: "#d03b3b", label: "Over limit", icon: "▲" },
};

async function settingsBudgets(el) {
  let limits = {};
  async function load() {
    limits = {};
    for (const l of await api("/api/budgets")) limits[`${l.category_id ?? "all"}:${l.period}`] = l.limit_cents;
  }
  const value = (key) => limits[key] != null ? (limits[key] / 100).toFixed(2).replace(".", ",").replace(/,00$/, "") : "";
  function sumLine(period) {
    const total = state.categories.reduce((a, c) => a + (limits[`${c.id}:${period}`] || 0), 0);
    const overall = limits[`all:${period}`];
    if (!total) return "";
    const warn = overall != null && total > overall;
    return `<span class="${warn ? "text-amber-700" : ""}">Category ${period}ly limits add up to ${fmtMoney(total)}${warn ? ", more than the overall limit" : ""}.</span>`;
  }
  function row(key, name, color, bold) {
    return `<div class="grid grid-cols-[1fr_6.5rem_6.5rem] sm:grid-cols-[1fr_9rem_9rem] items-center gap-2 py-2">
      <span class="flex items-center gap-2 min-w-0 ${bold ? "font-semibold text-slate-900" : "text-slate-700"}">
        ${color ? `<span class="w-2.5 h-2.5 rounded-full shrink-0" style="background:${esc(color)}"></span>` : ""}
        <span class="truncate">${esc(name)}</span></span>
      ${["week", "month"].map((p) => `
        <div class="relative">
          <input data-limit="${key}:${p}" value="${value(`${key}:${p}`)}" inputmode="decimal" autocomplete="off"
                 placeholder="No limit" class="input !pr-7 text-right tabular">
          <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 text-sm">€</span>
        </div>`).join("")}
    </div>`;
  }
  function render() {
    const anyCategoryLimit = Object.keys(limits).some((k) => !k.startsWith("all:"));
    el.innerHTML = `
      <p class="text-sm text-slate-500 mb-3">How much you want to spend. Leave a box empty for no limit. Changes save by themselves.</p>
      <div class="grid grid-cols-[1fr_6.5rem_6.5rem] sm:grid-cols-[1fr_9rem_9rem] gap-2 text-xs font-medium text-slate-500 pb-1 border-b border-slate-100">
        <span></span><span class="text-right pr-2">Weekly</span><span class="text-right pr-2">Monthly</span>
      </div>
      ${row("all", "Everything", null, true)}
      <details ${anyCategoryLimit ? "open" : ""} class="mt-2">
        <summary class="cursor-pointer list-none text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1 py-1">
          <span data-chevron class="transition-transform inline-block">›</span> Limits per category <span class="text-slate-400">(optional)</span>
        </summary>
        <div class="divide-y divide-slate-100">
          ${state.categories.map((c) => row(c.id, c.name, c.color, false)).join("")}
        </div>
        <p data-sums class="text-xs text-slate-500 mt-3 space-x-2">${sumLine("week")} ${sumLine("month")}</p>
      </details>`;
  }
  el.addEventListener("change", async (e) => {
    const input = e.target.closest("[data-limit]");
    if (!input) return;
    const [key, period] = input.dataset.limit.split(":");
    const raw = input.value.trim();
    const amount = raw ? parseAmount(raw) : null;
    if (raw && !(amount >= 0)) { toast("Enter a number like 150 or 150,50", "error"); input.value = value(input.dataset.limit); return; }
    try {
      await api("/api/budgets", { method: "PUT", body: {
        category_id: key === "all" ? null : Number(key), period, limit: amount == null ? null : amount.toFixed(2),
      } });
      if (amount == null) delete limits[input.dataset.limit]; else limits[input.dataset.limit] = Math.round(amount * 100);
      input.value = value(input.dataset.limit);
      $("[data-sums]", el).innerHTML = `${sumLine("week")} ${sumLine("month")}`;
      toast(amount == null ? "Limit removed" : "Limit saved");
      settingsHooks.refreshSummaries?.();
    } catch (err) { toast(err.message, "error"); }
  });
  el.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches("[data-limit]")) e.target.blur(); });
  await load();
  render();
  return async () => { await load(); render(); };
}

/* ===========================================================================
   Dashboard
   ======================================================================== */

/** Chart colours from the current theme. */
const chartInk = () => ({
  text: Theme.color("slate-500"), grid: Theme.color("slate-200", 0.6), surface: Theme.color("surface"),
  series: Theme.color("accent"), seriesSoft: Theme.color("accent", 0.35), reference: Theme.color("slate-700"),
});
const monthName = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });
const monthOnly = new Intl.DateTimeFormat("en-GB", { month: "long" });
const monthShort = new Intl.DateTimeFormat("en-GB", { month: "short" });
const dateObj = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };

function makeChart(canvas, config) {
  const ink = chartInk();
  Chart.defaults.font.family = "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif";
  Chart.defaults.color = ink.text;
  const chart = new Chart(canvas, config);
  state.charts.push(chart);
  return chart;
}

const moneyTooltip = (ctx) => ` ${ctx.dataset.label ? ctx.dataset.label + ": " : ""}${fmtMoney(ctx.parsed.y ?? ctx.parsed)}`;
// Axis ticks in whole euros; fractional ticks are left unlabelled.
const axisMoney = (v) => (Number.isInteger(v / 100) ? `${v / 100} €` : "");

/** Everyday spending against an even pace through the month. Monthly bills are left out:
    they land on one day and would skew it. Null when there's no monthly limit. */
function pace(s, d) {
  if (s.limit_cents == null || !d.is_current || s.limit_cents <= 0) return null;
  const bills = d.bills || { paid_cents: 0, upcoming_cents: 0 };
  const everydayBudget = s.limit_cents - bills.paid_cents - bills.upcoming_cents;
  if (everydayBudget <= 0) return null;
  const elapsed = d.days_total - d.days_left + 1;
  const expected = Math.round(everydayBudget * elapsed / d.days_total);
  // diff > 0: spent less than planned so far; < 0: more.
  return { diff: expected - (s.spent_cents - bills.paid_cents), everydayBudget, plan: bills.paid_cents + expected };
}

/** One plain sentence on the pace. */
function paceLine(s, d) {
  const p = pace(s, d);
  if (!p) return "";
  if (Math.abs(p.diff) < p.everydayBudget * 0.03) return "right on plan so far";
  return p.diff > 0 ? `${fmtMoney(p.diff)} less than planned so far` : `${fmtMoney(-p.diff)} more than planned so far`;
}

/** The field's colour: red when over the monthly budget, amber when spending runs ahead of plan
    (by more than 3%), green otherwise; null without a monthly budget. */
function budgetState(m, month) {
  if (m.limit_cents == null || m.limit_cents <= 0) return null;
  if (m.left_cents < 0) return "red";
  const p = pace(m, month);
  return p && -p.diff >= p.everydayBudget * 0.03 ? "amber" : "green";
}
const STATE_WORD = { green: "green", amber: "amber", red: "red" };

/** Keep the field (header, mark, phone status bar) in the colour of this month's state. */
async function refreshState(status) {
  try {
    const st = status || await api("/api/budgets/status");
    Theme.setState(budgetState(st.month.overall, st.month));
  } catch { /* keep the last colour */ }
}

function bar(pct, color, { thick = false } = {}) {
  return `<div class="${thick ? "h-2.5" : "h-1.5"} rounded-full bg-slate-100 overflow-hidden">
    <div class="h-full rounded-full transition-all" style="width:${Math.max(0, Math.min(100, pct))}%;background:${color}"></div></div>`;
}
/** Bar colour: calm when on track, amber/red only as a warning. */
const levelColor = (level, calm = "rgb(var(--accent))") => level === "green" ? calm : LEVELS[level]?.color || calm;
const limitPct = (s) => s.limit_cents > 0 ? (s.spent_cents / s.limit_cents) * 100 : (s.spent_cents > 0 ? 100 : 0);

/** Money as a big number, the euro sign smaller and raised: "414,59 €". */
const bigMoney = (cents) => {
  const t = fmtMoney(cents).replace(/\s?€$/, "");
  return `${t}<span class="cur">€</span>`;
};

/** The ring: white fills it as you spend; the dark notch is where the plan says you'd be by today. */
function ringSvg(m, month) {
  const R = 72, C = 2 * Math.PI * R;
  const spent = Math.max(0, Math.min(1, m.spent_cents / m.limit_cents));
  const p = pace(m, month);
  const planFrac = p ? Math.max(0, Math.min(1, p.plan / m.limit_cents)) : null;
  const notch = planFrac == null ? "" :
    `<line x1="88" y1="4" x2="88" y2="30" stroke="rgb(var(--field-deep))" stroke-width="6" stroke-linecap="round" transform="rotate(${planFrac * 360} 88 88)"/>`;
  const days = month.days_left;
  const label = `Spent ${Math.round(spent * 100)}% of the budget${planFrac != null ? `; the plan for today is ${Math.round(planFrac * 100)}%` : ""}. ${plural(days, "day", "days")} to go.`;
  return `<div class="relative w-28 h-28 sm:w-44 sm:h-44 shrink-0" role="img" aria-label="${label}">
    <svg viewBox="0 0 176 176" class="w-full h-full block">
      <circle cx="88" cy="88" r="${R}" fill="none" stroke="rgb(255 255 255 / .22)" stroke-width="22"/>
      <circle class="ring-spent" cx="88" cy="88" r="${R}" fill="none" stroke="#fff" stroke-width="22" stroke-dasharray="${(spent * C).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 88 88)"/>
      ${notch}
    </svg>
    <div class="absolute inset-0 grid place-items-center text-center">
      <div><b class="display block text-3xl sm:text-5xl leading-none">${days}</b>
        <span class="block text-[11px] sm:text-[13px] font-semibold on-field mt-1">${days === 1 ? "day to go" : "days to go"}</span></div>
    </div>
  </div>`;
}

/** This week as seven flat tiles: each fills with that day's spending against a day's share. */
function weekTiles(week, daily, perDayCents) {
  const byDay = Object.fromEntries((daily || []).map((x) => [x.date, x.cents]));
  const today = todayISO();
  const names = ["M", "T", "W", "T", "F", "S", "S"];
  return `<div class="grid grid-cols-7 gap-1.5 sm:gap-2">${names.map((n, i) => {
    const day = addDaysISO(week.start, i);
    const cents = byDay[day];
    const future = day > today;
    const frac = future || !cents || !perDayCents ? 0 : Math.min(1, cents / perDayCents);
    const label = `${dayLong.format(dateObj(day))}: ${future ? "still to come" : cents ? fmtMoney(cents) : "nothing spent"}`;
    return `<div><div class="week-tile ${day === today ? "today" : ""} ${future ? "future" : ""}" role="img" aria-label="${esc(label)}" title="${esc(label)}">
        <b style="height:${(frac * 100).toFixed(0)}%"></b></div>
      <span class="block text-center text-[11px] font-semibold on-field mt-1.5" aria-hidden="true">${n}</span></div>`;
  }).join("")}</div>`;
}

/** Home's field: what's left this month (or how far over), the ring, this week as tiles. */
function fieldHero(month, week, d, sv) {
  const m = month.overall, w = week.overall;
  const name = monthOnly.format(dateObj(month.start));
  const st = budgetState(m, month);
  let left;
  if (m.limit_cents == null) {
    left = `
      <p class="text-[15px] font-semibold on-field">Spent in ${name}</p>
      <p class="display whitespace-nowrap text-[clamp(3rem,17vw,4.25rem)] sm:text-[5.5rem] leading-[.95] mt-2">${bigMoney(m.spent_cents)}</p>
      <a href="#/settings?open=budget" class="btn mt-5 bg-white text-slate-900 hover:bg-white/90" style="color:rgb(var(--field))">Set a monthly budget</a>`;
  } else {
    const over = m.left_cents < 0;
    const upcoming = month.bills?.upcoming_cents || 0;
    // What you can spend a day once the bills still to come are paid.
    const perDay = month.days_left ? Math.max(0, m.left_cents - upcoming) / month.days_left : 0;
    const p = pace(m, month);
    const pill = over ? `Over: ${fmtMoney(m.spent_cents)} of ${fmtMoneyShort(m.limit_cents)}`
      : st === "amber" ? `${fmtMoney(-p.diff)} ahead of plan`
      : p && p.diff >= p.everydayBudget * 0.03 ? `${fmtMoney(p.diff)} under plan` : "On plan";
    left = `
      <p class="text-[15px] font-semibold on-field">${over ? `Over budget in ${name} by` : `Left to spend in ${name}`}</p>
      <p class="display whitespace-nowrap text-[clamp(3rem,17vw,4.25rem)] sm:text-[6rem] leading-[.95] mt-2">${bigMoney(Math.abs(m.left_cents))}</p>
      <p class="text-base sm:text-[17px] font-medium on-field mt-3">${over
        ? `${plural(month.days_left, "day", "days")} to go.`
        : `About <b class="text-white tabular">${fmtMoney(Math.floor(perDay))}</b> a day for ${plural(month.days_left, "day", "days")}${upcoming ? `, after ${fmtMoneyShort(upcoming)} in bills to come` : ""}`}</p>
      <p class="mt-4"><span class="state-pill tabular"><i></i>${pill}</span></p>`;
  }
  const perDayWeek = w.limit_cents ? w.limit_cents / 7 : (m.limit_cents ? m.limit_cents / month.days_total : 0);
  const weekText = w.limit_cents == null ? `${fmtMoney(w.spent_cents)} spent`
    : w.left_cents < 0 ? `${fmtMoney(-w.left_cents)} over` : `${fmtMoney(w.left_cents)} left`;
  const savings = sv?.enabled && (sv.total_cents || sv.goal_cents) ? `<a href="#/settings?open=savings" class="flex items-center justify-between text-sm font-semibold on-field hover:text-white mt-4">
      <span>Savings${sv.goal_name ? ` · ${esc(sv.goal_name)}` : ""}</span>
      <span class="tabular text-white">${fmtMoney(sv.total_cents)}${sv.goal_cents ? ` <span class="on-field font-medium">of ${fmtMoneyShort(sv.goal_cents)}</span>` : ""}</span></a>` : "";
  return `<section class="field bleed relative overflow-hidden -mt-5" data-field>
    <div class="field-deep disc w-[34rem] sm:w-[44rem] -right-56 sm:-right-40 -top-64 sm:-top-80" aria-hidden="true"></div>
    <div class="relative max-w-4xl mx-auto px-4 pt-5 sm:pt-8 pb-12 sm:pb-14">
      <div class="flex flex-col sm:flex-row-reverse sm:items-start sm:justify-between gap-2 sm:gap-6">
        ${m.limit_cents != null ? `<div class="self-end sm:self-auto -mb-6 sm:mb-0">${ringSvg(m, month)}</div>` : ""}
        <div class="min-w-0">${left}</div>
      </div>
      <a href="#/transactions?date_from=${week.start}&date_to=${week.end}" class="block mt-8 group">
        <div class="flex justify-between items-baseline text-sm font-semibold on-field group-hover:text-white mb-2">
          <span>This week</span><span class="tabular text-white">${weekText}</span></div>
        ${weekTiles(week, d.is_current ? d.daily : [], perDayWeek)}
      </a>
      ${savings}
    </div>
  </section>`;
}

/** Where it went: one flat band (a stripe per category, sized by its share), then the list. */
function whereItWent(d, txLink) {
  const cats = d.categories.filter((c) => c.spent_cents > 0).sort((a, b) => b.spent_cents - a.spent_cents);
  if (!cats.length) return `<p class="text-sm text-slate-400 py-8 text-center">Nothing spent in ${monthOnly.format(dateObj(d.start))}${d.is_current ? " yet" : ""}.</p>`;
  const total = cats.reduce((a, c) => a + c.spent_cents, 0);
  const SHOW = 6;
  const flag = `<div class="flag mb-3" role="img" aria-label="${esc(cats.map((c) => `${c.name} ${Math.round(c.spent_cents / total * 100)}%`).join(", "))}">
    ${cats.map((c) => `<i style="flex:${c.spent_cents};background:${esc(c.color)}" title="${esc(c.name)}: ${fmtMoney(c.spent_cents)}"></i>`).join("")}</div>`;
  const limitNote = (c) => {
    if (c.limit_cents == null) return "";
    const over = c.spent_cents > c.limit_cents;
    return `<span class="tabular text-xs w-20 text-right ${over ? "text-red-600 font-semibold" : c.level === "amber" ? "text-amber-700" : "text-slate-400"}">${over ? `over ${fmtMoneyShort(c.limit_cents)}` : `of ${fmtMoneyShort(c.limit_cents)}`}</span>`;
  };
  const row = (c, i) => `
    <li ${i >= SHOW ? "data-extra hidden" : ""}>
      <a href="${txLink(`&category_id=${c.category_id ?? "none"}`)}" class="flex items-center gap-3 rounded-lg -mx-2 px-2 py-2 hover:bg-slate-100 text-[15px]">
        <span class="w-3 h-3 rounded-[4px] shrink-0" style="background:${esc(c.color)}"></span>
        <span class="flex-1 truncate text-slate-800">${esc(c.name)}</span>
        <span class="tabular font-semibold text-slate-900">${fmtMoney(c.spent_cents)}</span>
        ${limitNote(c)}
      </a>
    </li>`;
  return `${flag}<ul>${cats.map(row).join("")}</ul>
    ${cats.length > SHOW ? `<button data-show-extra class="link mt-2">Show ${cats.length - SHOW} more</button>` : ""}`;
}

/** Parse SQLite UTC ("2026-10-05 14:43:00") or ISO with an offset. */
const parseWhen = (s) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s.replace(" ", "T") : s.replace(" ", "T") + "Z");
const daysSince = (s) => Math.floor((Date.now() - parseWhen(s).getTime()) / 86400000);

/** Quiet warnings about the iPhone Shortcut and Gmail, shown on Home only when something's off. */
function homeNotices(email) {
  const out = [];
  const box = (text, actions) => `<div class="flex flex-wrap items-center gap-x-3 gap-y-1 mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <span class="flex-1 min-w-[12rem]">${text}</span>${actions}</div>`;
  if (email.review_count) {
    out.push(`<a href="#/import" class="flex items-center gap-3 mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 hover:bg-amber-100">
      <span class="flex-1">${plural(email.review_count, "payment from your iPhone needs", "payments from your iPhone need")} a quick check</span>
      <span class="font-medium">Review →</span></a>`);
  }
  if (!email.enabled) return out.join("");
  if (email.last_sync?.error) {
    out.push(box(`Couldn't check Gmail for Apple Pay payments: ${esc(email.last_sync.error)}`,
      state.local ? `<a href="#/settings?open=gmail" class="font-medium">Fix →</a>` : ""));
  } else if (email.last_email_at) {
    const days = daysSince(email.last_email_at);
    const snoozed = state.prefs.shortcut_snoozed_until && state.prefs.shortcut_snoozed_until >= todayISO();
    if (days >= 5 && !snoozed) {
      out.push(box(`No Apple Pay emails for ${days} days. Is your iPhone Shortcut still on?`,
        `<button data-snooze-shortcut class="font-medium hover:underline">Hide for a week</button>`));
    }
  }
  return out.join("");
}

/** For the first week of a month: a short look back at the one before. Closable. */
async function monthSummary(sv) {
  const today = new Date();
  if (today.getDate() > 7) return "";
  const prev = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const key = isoOf(prev).slice(0, 7);
  if (state.prefs.summary_dismissed === key) return "";
  let d;
  try { d = await api(`/api/dashboard?period=month&date=${isoOf(prev)}`); } catch { return ""; }
  const o = d.overall;
  if (!(o.spent_cents > 0)) return "";
  const top = d.categories.filter((c) => c.spent_cents > 0).sort((a, b) => b.spent_cents - a.spent_cents)[0];
  const name = monthOnly.format(prev);
  let verdict = `You spent <b class="text-slate-900">${fmtMoney(o.spent_cents)}</b>.`;
  if (o.limit_cents != null) {
    verdict = o.left_cents >= 0
      ? `You spent <b class="text-slate-900">${fmtMoney(o.spent_cents)}</b> of ${fmtMoneyShort(o.limit_cents)}, <b class="text-slate-900">${fmtMoney(o.left_cents)}</b> under budget.`
      : `You spent <b class="text-slate-900">${fmtMoney(o.spent_cents)}</b>, ${fmtMoney(-o.left_cents)} over your ${fmtMoneyShort(o.limit_cents)} budget.`;
  }
  const saved = sv?.enabled ? sv.months.find((m) => m.month === key) : null;
  const savedLine = !saved || !saved.saved_cents ? ""
    : saved.saved_cents > 0 ? ` <b class="text-slate-900">${fmtMoney(saved.saved_cents)}</b> went into your savings.`
    : ` ${fmtMoney(-saved.saved_cents)} came out of your savings.`;
  const change = d.prev_total_cents > 0 ? Math.round(((o.spent_cents - d.prev_total_cents) / d.prev_total_cents) * 100) : null;
  return `<section data-summary-card="${key}" class="card p-5 sm:p-6 mb-4">
    <div class="flex items-start gap-3">
      <div class="flex-1">
        <h2 class="text-xl font-bold text-slate-900">${name}, looking back</h2>
      </div>
      <button data-close-summary class="text-slate-400 hover:text-slate-700 text-2xl leading-none px-1" aria-label="Close">&times;</button>
    </div>
    <p class="text-sm text-slate-600 mt-2">${verdict}
      ${top ? ` Most went to ${esc(top.name)} (${fmtMoney(top.spent_cents)}).` : ""}
      ${change != null && Math.abs(change) >= 1 ? ` That's ${Math.abs(change)}% ${change < 0 ? "less" : "more"} than the month before.` : ""}${savedLine}</p>
    <a href="#/home?date=${isoOf(prev)}" class="link inline-block mt-3">See ${name} →</a>
  </section>`;
}

/* --- Calendar heatmap: one cell per day, darker = more spent ------------- */

// One blue ramp, light -> dark (the default sequential hue). Dark themes flip it,
// so the biggest days are the brightest. Text colours were checked for contrast.
const HEAT = {
  light: { fill: ["#cde2fb", "#86b6ef", "#256abf", "#104281"], ink: ["#18181b", "#18181b", "#ffffff", "#ffffff"] },
  dark: { fill: ["#104281", "#256abf", "#86b6ef", "#cde2fb"], ink: ["#ffffff", "#ffffff", "#18181b", "#18181b"] },
};
const dayLong = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });

/** Quartiles of the month's spending days, so one big day (rent) doesn't wash out the rest. */
function heatLevels(days) {
  const v = days.map((d) => d.cents).filter((c) => c > 0).sort((a, b) => a - b);
  const q = (p) => v.length ? v[Math.min(v.length - 1, Math.floor(p * v.length))] : 0;
  const cuts = [q(0.25), q(0.5), q(0.75)];
  return (cents) => cents <= 0 ? -1 : cents <= cuts[0] ? 0 : cents <= cuts[1] ? 1 : cents <= cuts[2] ? 2 : 3;
}

function heatmapCard(d) {
  const mode = document.documentElement.dataset.mode === "dark" ? "dark" : "light";
  const ramp = HEAT[mode];
  const level = heatLevels(d.daily.filter((x) => x.date <= d.today));
  const first = dateObj(d.daily[0].date);
  const lead = (first.getDay() + 6) % 7;            // Monday-first grid
  const spent = d.daily.filter((x) => x.cents > 0);
  const top = spent.length ? spent.reduce((a, b) => (b.cents > a.cents ? b : a)) : null;
  const cells = d.daily.map((x) => {
    const future = x.date > d.today;
    const lv = future ? -1 : level(x.cents);
    const day = Number(x.date.slice(8));
    const style = lv >= 0 ? `background:${ramp.fill[lv]};color:${ramp.ink[lv]}` : "";
    const label = `${dayLong.format(dateObj(x.date))}: ${future ? "not yet" : x.cents ? `${fmtMoney(x.cents)}, ${plural(x.count, "expense", "expenses")}` : "nothing spent"}`;
    return `<button type="button" data-heat-day="${x.date}" ${future ? "disabled" : ""} aria-label="${esc(label)}"
        data-tip="${esc(label)}"
        class="relative h-12 sm:h-16 rounded-lg text-left p-1.5 sm:p-2 transition
          ${lv < 0 ? (future ? "border border-dashed border-slate-200 text-slate-300" : "bg-slate-100 text-slate-400 hover:bg-slate-200") : "hover:brightness-110"}
          ${x.date === d.today ? "ring-2 ring-accent ring-offset-2 ring-offset-surface" : ""}"
        style="${style}">
        <span class="block text-[11px] sm:text-xs font-medium leading-none tabular">${day}</span>
        ${x.cents > 0 && !future ? `<span class="hidden sm:block absolute bottom-1.5 right-2 text-[11px] tabular opacity-90">${fmtMoneyShort(Math.round(x.cents / 100) * 100).replace(/\s?€/, "")}€</span>` : ""}
      </button>`;
  });
  return `<section class="card p-5 lg:col-span-2">
    <div class="flex flex-wrap items-baseline justify-between gap-2 mb-1">
      <h3 class="font-semibold text-slate-900">Spending by day in ${monthOnly.format(dateObj(d.start))}</h3>
      <span class="flex items-center gap-1.5 text-xs text-slate-500" aria-hidden="true">Less
        ${ramp.fill.map((c) => `<span class="w-3.5 h-3.5 rounded" style="background:${c}"></span>`).join("")} More</span>
    </div>
    <p class="text-sm text-slate-500 mb-4">${top ? `Biggest day: <b class="text-slate-900">${esc(dayLong.format(dateObj(top.date)))}</b>, ${fmtMoney(top.cents)}. ` : ""}Tap a day to see what you bought.</p>
    <div class="grid grid-cols-7 gap-1.5 sm:gap-2">
      ${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((w) => `<span class="text-[11px] text-slate-400 text-center">${w}</span>`).join("")}
      ${"<span></span>".repeat(lead)}${cells.join("")}
    </div>
  </section>`;
}

/** Hover tooltip for heatmap cells (keyboard users get the same text as the button's label). */
function wireHeatmap(root) {
  let tip = $("#heat-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "heat-tip";
    tip.className = "hidden fixed z-40 pointer-events-none rounded-lg bg-slate-900 text-slate-50 text-xs px-2.5 py-1.5 shadow-lg";
    document.body.append(tip);
  }
  root.addEventListener("pointerover", (e) => {
    const c = e.target.closest("[data-tip]");
    if (!c) return;
    tip.textContent = c.dataset.tip;
    const r = c.getBoundingClientRect();
    tip.classList.remove("hidden");
    const w = tip.offsetWidth;
    tip.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2))}px`;
    tip.style.top = `${r.top - tip.offsetHeight - 8}px`;
  });
  root.addEventListener("pointerout", (e) => { if (e.target.closest("[data-tip]")) tip.classList.add("hidden"); });
  root.addEventListener("click", (e) => {
    const c = e.target.closest("[data-heat-day]");
    if (!c) return;
    tip.classList.add("hidden");
    openDay(c.dataset.heatDay);
  });
}

/** A panel with one day's expenses; tap one to edit it. */
async function openDay(iso) {
  const body = document.createElement("div");
  async function load() {
    const data = await api(`/api/expenses?date_from=${iso}&date_to=${iso}&limit=200&sort=amount&order=desc`);
    body.innerHTML = `
      <p class="text-sm text-slate-500 -mt-2 mb-4">${data.count ? `<b class="text-slate-900 tabular">${fmtMoney(data.total_cents)}</b> · ${plural(data.count, "expense", "expenses")}` : "Nothing spent this day."}</p>
      ${data.count ? `<div data-list class="-mx-5 divide-y divide-slate-100 border-y border-slate-100">${data.items.map((e) => expenseRow(e, { showDate: false })).join("")}</div>` : ""}
      <div class="flex justify-between items-center mt-4">
        <a href="#/transactions?date_from=${iso}&date_to=${iso}" class="link">Open in Transactions</a>
        <a href="#/add?date=${iso}" class="btn btn-secondary !py-1.5">+ Add for this day</a>
      </div>`;
    const list = $("[data-list]", body);
    // Editing opens its own dialog; come back to this day afterwards.
    if (list) wireExpenseRows(list, { find: (fn) => data.items.find(fn) }, () => { render(); setTimeout(() => openDay(iso), 50); });
  }
  await load();
  openModal(dayLong.format(dateObj(iso)), body);
}

let trendsOpen = false;   // remembered while the app is open

async function viewDashboard(root, params) {
  const date = params.get("date") || "";
  const [glance, d, recent, emailStatus, sv] = await Promise.all([
    api("/api/budgets/status"),
    api(`/api/dashboard?period=month${date ? `&date=${date}` : ""}`),
    api("/api/expenses?limit=5&sort=date&order=desc"),
    api("/api/email/status").catch(() => ({ review_count: 0 })),
    api("/api/savings").catch(() => null),
  ]);
  const go = (dt) => `#/home${dt ? `?date=${dt}` : ""}`;
  const txLink = (extra = "") => `#/transactions?date_from=${d.start}&date_to=${d.end}${extra}`;

  if (!recent.count && !d.overall.spent_cents) {
    root.innerHTML = `
      <section class="card p-8 text-center max-w-lg mx-auto mt-6">
        <span class="inline-flex w-14 h-14 rounded-full field items-center justify-center text-2xl font-black mb-4" aria-hidden="true">€</span>
        <h1 class="text-xl font-semibold text-slate-900">Welcome to Budget</h1>
        <p class="text-sm text-slate-500 mt-2 mb-6">Add what you spend and see at a glance how much is left this month.</p>
        <div class="flex flex-col sm:flex-row gap-2 justify-center">
          <a href="#/add" class="btn btn-primary">Add your first expense</a>
          <a href="#/settings?open=budget" class="btn btn-secondary">Set a monthly budget</a>
        </div>
        <a href="#/import" class="link inline-block mt-4">or import a bank statement</a>
      </section>`;
    return;
  }

  const summary = d.is_current ? await monthSummary(sv) : "";
  refreshState(glance);
  // The field needs this month's days for the week tiles, whichever month the list shows.
  const now = d.is_current ? d : await api("/api/dashboard?period=month").catch(() => d);
  root.innerHTML = `
    ${fieldHero(glance.month, glance.week, now, sv)}
    <div class="sheet bleed"><div class="max-w-4xl mx-auto px-4">
    ${homeNotices(emailStatus)}
    ${summary}

    <div class="grid lg:grid-cols-2 gap-4">
      <section class="card p-5">
        <div class="flex items-center justify-between mb-2">
          <h2 class="font-bold text-lg text-slate-900">Where it went</h2>
          <div class="flex items-center text-sm text-slate-500">
            <a href="${go(d.prev_date)}" class="px-2 py-0.5 rounded hover:bg-slate-100" aria-label="Previous month">‹</a>
            <span class="tabular">${d.is_current ? monthOnly.format(dateObj(d.start)) : monthName.format(dateObj(d.start))}</span>
            ${d.is_current ? `<span class="px-2 py-0.5 opacity-0">›</span>` : `<a href="${go(d.next_date)}" class="px-2 py-0.5 rounded hover:bg-slate-100" aria-label="Next month">›</a>`}
          </div>
        </div>
        ${!d.is_current ? `<p class="text-xs text-slate-500 mb-2">${fmtMoney(d.overall.spent_cents)} in total · <a href="${go("")}" class="underline">back to this month</a></p>` : ""}
        ${whereItWent(d, txLink)}
      </section>

      <section class="card overflow-hidden">
        <div class="flex items-center justify-between px-5 pt-5 pb-2">
          <h2 class="font-bold text-lg text-slate-900">Recent</h2>
          <a href="#/transactions" class="link">See all</a>
        </div>
        <div data-recent class="divide-y divide-slate-100">${recent.items.map((e) => expenseRow(e)).join("")}</div>
      </section>
    </div>

    <div class="mt-6 text-center">
      <button data-toggle-trends class="btn btn-ghost">${trendsOpen ? "Hide trends" : "Show trends"}</button>
    </div>
    <div data-trends class="${trendsOpen ? "" : "hidden"} grid lg:grid-cols-2 gap-4 mt-2">
      ${heatmapCard(d)}
      <section class="card p-5">
        <h3 class="font-bold text-slate-900 mb-3">Month by month</h3>
        <div class="h-52"><canvas data-trend aria-label="Spending per month"></canvas></div>
      </section>
      <section class="card p-5">
        <h3 class="font-bold text-slate-900 mb-3">Where you spend most</h3>
        ${d.top_merchants.length ? `<ol class="space-y-1">${d.top_merchants.map((m) => `
          <li><a href="${txLink(`&q=${encodeURIComponent(m.merchant)}`)}" class="flex items-center gap-3 rounded-lg -mx-2 px-2 py-1.5 hover:bg-slate-50 text-sm">
            ${categoryAvatar(m.category_name, m.category_color)}
            <span class="flex-1 min-w-0"><span class="block truncate text-slate-800">${esc(m.merchant)}</span>
              <span class="text-xs text-slate-400">${plural(m.count, "time", "times")}</span></span>
            <span class="tabular font-medium text-slate-900">${fmtMoney(m.cents)}</span></a></li>`).join("")}</ol>`
        : `<p class="text-sm text-slate-400 py-4 text-center">Nothing yet.</p>`}
      </section>
    </div>
    </div></div>`;

  wireExpenseRows($("[data-recent]", root), { find: (fn) => recent.items.find(fn) }, render);
  wireHeatmap($("[data-trends]", root));
  $("[data-snooze-shortcut]", root)?.addEventListener("click", async (e) => {
    e.target.closest(".rounded-xl").remove();
    await savePrefs({ shortcut_snoozed_until: addDaysISO(todayISO(), 7) });
  });
  $("[data-close-summary]", root)?.addEventListener("click", async (e) => {
    const card = e.target.closest("[data-summary-card]");
    card.remove();
    await savePrefs({ summary_dismissed: card.dataset.summaryCard });
  });
  $("[data-show-extra]", root)?.addEventListener("click", (e) => {
    $$("[data-extra]", root).forEach((li) => li.removeAttribute("hidden"));
    e.target.remove();
  });

  let drawn = false;
  function drawCharts() {
    if (drawn) return;
    drawn = true;
    const ink = chartInk();
    const axes = (suggestedMax) => ({
      x: { grid: { display: false }, ticks: { autoSkip: true, maxRotation: 0 } },
      y: { beginAtZero: true, suggestedMax, grid: { color: ink.grid }, border: { display: false }, ticks: { callback: axisMoney, maxTicksLimit: 4 } },
    });
    const selectedMonth = d.start.slice(0, 7);
    makeChart($("[data-trend]", root), {
      type: "bar",
      data: {
        labels: d.trend.map((t) => monthShort.format(dateObj(t.month + "-01"))),
        datasets: [{ label: "Spent", data: d.trend.map((t) => t.cents), borderRadius: 6, borderSkipped: "start", maxBarThickness: 26,
          backgroundColor: d.trend.map((t) => t.month === selectedMonth ? ink.series : ink.seriesSoft) }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false },
          tooltip: { callbacks: { title: (items) => monthName.format(dateObj(d.trend[items[0].dataIndex].month + "-01")), label: moneyTooltip } } },
        scales: axes(10000),
        onClick: (_, els) => { if (els.length) location.hash = go(d.trend[els[0].index].month + "-01"); },
      },
    });
  }
  $("[data-toggle-trends]", root).addEventListener("click", (e) => {
    trendsOpen = !trendsOpen;
    $("[data-trends]", root).classList.toggle("hidden", !trendsOpen);
    e.target.textContent = trendsOpen ? "Hide trends" : "Show trends";
    if (trendsOpen) drawCharts();
  });
  if (trendsOpen) drawCharts();
}

/* ===========================================================================
   Import (CSV) and the Data section of Settings
   ======================================================================== */

async function viewImport(root) {
  const S = { text: "", parsed: null, rows: [] };
  root.innerHTML = `
    <a href="#/transactions" class="link inline-block mb-3">‹ Transactions</a>
    <section data-review class="hidden mb-8"></section>
    <h1 class="text-xl font-semibold text-slate-900 mb-1">Import a bank statement</h1>
    <p class="text-sm text-slate-500 mb-5">Download a CSV from your bank, drop it here, check the preview, then import.</p>
    <label data-drop class="card p-8 flex flex-col items-center justify-center text-center border-2 border-dashed border-slate-300 cursor-pointer hover:border-slate-400 transition">
      <svg class="w-8 h-8 text-slate-400 mb-2" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M4 20h16"/></svg>
      <span class="font-medium text-slate-700">Choose a CSV file</span>
      <span class="text-xs text-slate-400 mt-1" data-filename>or drag it here</span>
      <input type="file" accept=".csv,text/csv,.txt" class="hidden" data-file>
    </label>
    <section data-map class="hidden card p-5 mt-5"></section>
    <section data-preview class="hidden mt-5"></section>`;

  await reviewSection($("[data-review]", root));

  const drop = $("[data-drop]", root);
  async function useFile(file) {
    if (!file) return;
    $("[data-filename]", root).textContent = file.name;
    const buf = await file.arrayBuffer();
    // Spanish banks often export Windows-1252; try UTF-8 first.
    try { S.text = new TextDecoder("utf-8", { fatal: true }).decode(buf); }
    catch { S.text = new TextDecoder("windows-1252").decode(buf); }
    try {
      S.parsed = await api("/api/import/parse", { method: "POST", body: { text: S.text } });
      renderMapping();
    } catch (e) { toast(e.message, "error"); }
  }
  $("[data-file]", root).addEventListener("change", (e) => useFile(e.target.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("border-slate-500"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("border-slate-500"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("border-slate-500"); useFile(e.dataTransfer.files[0]); });

  function renderMapping() {
    const p = S.parsed, m = p.mapping;
    const colSelect = (field) => `<select data-field="${field}" class="input">
      <option value="">Choose a column…</option>
      ${p.headers.map((h, i) => `<option value="${i}" ${m[field] === i ? "selected" : ""}>${esc(h)}</option>`).join("")}</select>`;
    const el = $("[data-map]", root);
    el.classList.remove("hidden");
    el.innerHTML = `
      <div class="flex items-baseline justify-between gap-2 flex-wrap mb-4">
        <h2 class="font-semibold">Columns</h2>
        <span class="text-xs ${p.remembered ? "text-emerald-700" : "text-slate-400"}">${p.remembered ? "Using the mapping you saved last time" : `${p.row_count} rows found · your choices are remembered for next time`}</span>
      </div>
      <div class="grid sm:grid-cols-3 gap-3">
        <div><label class="label">Date</label>${colSelect("date")}</div>
        <div><label class="label">Description / merchant</label>${colSelect("description")}</div>
        <div><label class="label">Amount</label>${colSelect("amount")}</div>
        <div><label class="label">Date format</label>
          <select data-field="date_format" class="input">${p.date_formats.map((f) => `<option ${m.date_format === f ? "selected" : ""}>${f}</option>`).join("")}</select></div>
        <div class="sm:col-span-2"><label class="label">In this file, spending is shown as…</label>
          <select data-field="sign" class="input">
            <option value="negative" ${m.sign === "negative" ? "selected" : ""}>Negative numbers (-12,50), money back is positive</option>
            <option value="positive" ${m.sign === "positive" ? "selected" : ""}>Positive numbers (12,50), money back is negative</option>
          </select></div>
      </div>
      <div class="mt-4 overflow-x-auto rounded-lg border border-slate-200">
        <table class="min-w-full text-xs">
          <thead class="bg-slate-50 text-slate-500"><tr>${p.headers.map((h) => `<th class="px-2 py-1.5 text-left font-medium whitespace-nowrap">${esc(h)}</th>`).join("")}</tr></thead>
          <tbody>${p.sample.map((r) => `<tr class="border-t border-slate-100">${r.map((c) => `<td class="px-2 py-1.5 whitespace-nowrap text-slate-600">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody>
        </table>
      </div>
      <div class="mt-4 flex justify-end"><button data-go class="btn btn-primary">Preview import</button></div>`;
    $("[data-go]", el).addEventListener("click", buildPreview);
  }

  async function buildPreview() {
    const el = $("[data-map]", root);
    const val = (f) => $(`[data-field=${f}]`, el).value;
    const mapping = { date: val("date"), description: val("description"), amount: val("amount"), date_format: val("date_format"), sign: val("sign") };
    if (["date", "description", "amount"].some((f) => mapping[f] === "")) { toast("Pick the date, description and amount columns", "error"); return; }
    for (const f of ["date", "description", "amount"]) mapping[f] = Number(mapping[f]);
    const btn = $("[data-go]", el);
    btn.disabled = true; btn.textContent = "Categorizing…";
    try {
      const res = await api("/api/import/preview", { method: "POST", body: { text: S.text, mapping } });
      S.rows = res.rows.map((r) => ({ ...r, include: !r.error && !r.duplicate }));
      renderPreview();
    } catch (e) { toast(e.message, "error"); }
    finally { btn.disabled = false; btn.textContent = "Preview import"; }
  }

  function renderPreview() {
    const el = $("[data-preview]", root);
    el.classList.remove("hidden");
    const ok = S.rows.filter((r) => !r.error);
    const dups = ok.filter((r) => r.duplicate).length;
    const errors = S.rows.length - ok.length;
    const uncategorized = ok.filter((r) => r.include && !r.category_id).length;
    const chosen = ok.filter((r) => r.include);
    el.innerHTML = `
      <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div class="text-sm text-slate-600">
          <b class="text-slate-900">${chosen.length}</b> to import · ${fmtMoney(chosen.reduce((a, r) => a + r.amount_cents, 0))}
          ${dups ? ` · <span class="text-amber-700">${dups} likely duplicate${dups === 1 ? "" : "s"} (unticked)</span>` : ""}
          ${errors ? ` · <span class="text-red-600">${errors} unreadable row${errors === 1 ? "" : "s"}</span>` : ""}
          ${uncategorized ? ` · ${uncategorized} need${uncategorized === 1 ? "s" : ""} a category` : ""}
        </div>
        <button data-commit class="btn btn-primary" ${chosen.length ? "" : "disabled"}>Import ${chosen.length} expense${chosen.length === 1 ? "" : "s"}</button>
      </div>
      <div class="card overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead class="text-xs text-slate-500 bg-slate-50"><tr>
            <th class="p-2 w-8"><input type="checkbox" data-all ${chosen.length === ok.length && ok.length ? "checked" : ""} aria-label="Select all"></th>
            <th class="p-2 text-left font-medium">Date</th><th class="p-2 text-left font-medium">Merchant</th>
            <th class="p-2 text-right font-medium">Amount</th><th class="p-2 text-left font-medium">Category</th>
          </tr></thead>
          <tbody>${S.rows.map((r, i) => r.error ? `
            <tr class="border-t border-slate-100 text-slate-400"><td></td>
              <td class="p-2 whitespace-nowrap">${esc(r.raw.date)}</td>
              <td class="p-2">${esc(r.raw.description)}<div class="text-xs text-red-600">Skipped: ${esc(r.error)}</div></td>
              <td class="p-2 text-right whitespace-nowrap">${esc(r.raw.amount)}</td><td></td></tr>` : `
            <tr class="border-t border-slate-100 ${r.include ? "" : "opacity-50"}" data-i="${i}">
              <td class="p-2 text-center"><input type="checkbox" data-inc ${r.include ? "checked" : ""}></td>
              <td class="p-2 whitespace-nowrap tabular">${fmtDate(r.date)}</td>
              <td class="p-2 min-w-[12rem]"><div class="truncate max-w-xs">${esc(r.merchant)}</div>
                ${r.duplicate ? `<div class="text-xs text-amber-700">Possible duplicate: ${esc(r.duplicate.reason)} (${esc(r.duplicate.merchant)}, ${fmtDate(r.duplicate.date)})</div>` : ""}</td>
              <td class="p-2 text-right whitespace-nowrap tabular ${r.amount_cents < 0 ? "text-emerald-600" : ""}">${r.amount_cents < 0 ? "+" : ""}${fmtMoney(Math.abs(r.amount_cents))}</td>
              <td class="p-2"><div class="flex items-center gap-2">
                <select data-cat class="input !py-1 !w-44 ${r.category_id ? "" : "!border-amber-400"}">${categoryOptions(r.category_id ?? "none", { all: false })}</select>
                ${sourceTag(r.category_source)}</div></td>
            </tr>`).join("")}</tbody>
        </table>
      </div>`;
    el.addEventListener("change", onChange, { once: true });
    $("[data-commit]", el).addEventListener("click", commit);
  }
  function onChange(e) {
    const tr = e.target.closest("[data-i]");
    if (e.target.matches("[data-all]")) S.rows.forEach((r) => { if (!r.error) r.include = e.target.checked; });
    else if (tr && e.target.matches("[data-inc]")) S.rows[tr.dataset.i].include = e.target.checked;
    else if (tr && e.target.matches("[data-cat]")) {
      const r = S.rows[tr.dataset.i];
      r.category_id = e.target.value === "none" ? null : Number(e.target.value);
      r.category_source = r.category_id ? "manual" : "none";
    }
    renderPreview();
  }
  async function commit() {
    const rows = S.rows.filter((r) => r.include && !r.error).map((r) => ({
      date: r.date, merchant: r.merchant, amount_cents: r.amount_cents,
      category_id: r.category_id, category_source: r.category_source, import_hash: r.import_hash,
    }));
    try {
      const res = await api("/api/import/commit", { method: "POST", body: { rows } });
      toast(`Imported ${res.added} expense${res.added === 1 ? "" : "s"}`);
      location.hash = "#/transactions";
    } catch (e) { toast(e.message, "error"); }
  }
}

async function settingsData(el) {
  el.innerHTML = `
    <p class="text-sm text-slate-500 mb-2">Budget makes a backup by itself once a day when it opens and keeps the last 14.</p>
    <p class="text-sm text-slate-500 mb-4">Everything is stored on your ${computer()} in
      <code data-db-path class="text-xs bg-slate-100 rounded px-1 break-all"></code>.
      Rebuilding or updating the app never touches it.</p>
    <div class="flex flex-wrap gap-2">
      <button data-backup class="btn btn-primary">Back up now</button>
      <a href="/api/export.csv" class="btn btn-secondary">Export all to CSV</a>
      <a href="#/import" class="btn btn-secondary">Import a bank statement</a>
      <button data-show-folder class="btn btn-ghost hidden">Show in ${fileBrowser()}</button>
    </div>
    <div data-backups class="mt-4 text-sm"></div>`;
  async function list() {
    const files = await api("/api/backups");
    $("[data-backups]", el).innerHTML = files.length ? `
      <p class="text-xs text-slate-500 mb-1">Backups (in the <code class="bg-slate-100 rounded px-1">backups</code> folder next to the database):</p>
      <ul class="text-xs text-slate-600 space-y-0.5 max-h-40 overflow-y-auto">${files.slice(0, 20).map((f) =>
        `<li class="tabular">${esc(f.file)} <span class="text-slate-400">· ${f.automatic ? "automatic · " : ""}${(f.size_bytes / 1024).toFixed(0)} KB</span></li>`).join("")}</ul>`
      : `<p class="text-xs text-slate-400">No backups yet.</p>`;
  }
  const status = await api("/api/status");
  $("[data-db-path]", el).textContent = status.db_path.replace(/^\/Users\/[^/]+/, "~");
  const showFolder = $("[data-show-folder]", el);
  if (desktop()) showFolder.classList.remove("hidden");
  showFolder.addEventListener("click", () => desktop()?.show_data_folder());
  $("[data-backup]", el).addEventListener("click", async (e) => {
    e.target.disabled = true;
    try { const r = await api("/api/backup", { method: "POST" }); toast(`Saved ${r.file}`); list(); }
    catch (err) { toast(err.message, "error"); }
    finally { e.target.disabled = false; }
  });
  await list();
}


/* ===========================================================================
   Gmail import: settings, "Needs review", and the "new transactions" notice
   ======================================================================== */

const fmtDateTime = (iso) => iso ? `${fmtDate(iso.slice(0, 10))} ${iso.slice(11, 16)}` : "";
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function syncSummary(s, prefix = null) {
  if (!s) return "Not checked yet.";
  prefix = prefix ?? `Last check ${fmtDateTime(s.finished_at)}`;
  if (s.error) return `${prefix}: ${s.error}`;
  const parts = [`${s.imported} imported`];
  if (s.review) parts.push(`${s.review} need${s.review === 1 ? "s" : ""} review`);
  if (s.refused) parts.push(`${s.refused} refused (not from you)`);
  return `${prefix}: ${parts.join(" · ")}.`;
}

async function settingsGmail(el) {
  let cfg = await api("/api/email/settings");
  el.innerHTML = `
    <p class="text-sm text-slate-500 mb-4">Adds your Apple Pay payments automatically from the emails your iPhone Shortcut sends
      (subject <b>BUDGET</b>). Gmail is opened read-only, and the password stays in ${passwordStore()}.</p>
    <form data-gmail class="space-y-3" autocomplete="off">
      <label class="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
        <input type="checkbox" name="enabled" class="rounded border-slate-300" ${cfg.enabled ? "checked" : ""}>
        Check automatically when Budget opens and every ${cfg.check_every_minutes} minutes
      </label>
      <div class="grid sm:grid-cols-3 gap-3">
        <div><label class="label">Gmail address</label>
          <input name="address" type="email" class="input" placeholder="you@gmail.com" value="${esc(cfg.address)}"></div>
        <div><label class="label">App password</label>
          <input name="password" type="password" class="input" autocomplete="new-password"
                 placeholder="${cfg.has_password ? "Saved — type to replace" : "16-letter app password"}">
          ${cfg.has_password ? `<button type="button" data-forget class="text-xs text-slate-500 hover:text-red-600 mt-1">Forget saved password</button>` : ""}</div>
        <div><label class="label">Gmail label</label>
          <input name="label" class="input" value="${esc(cfg.label)}"></div>
      </div>
      <div class="flex flex-wrap gap-2">
        <button class="btn btn-primary">Save</button>
        <button type="button" data-test class="btn btn-secondary">Test connection</button>
        <button type="button" data-check class="btn btn-ghost">Check now</button>
      </div>
      <div data-result class="hidden rounded-lg px-3 py-2 text-sm"></div>
      <p data-last class="text-xs text-slate-500">${esc(syncSummary(cfg.last_sync))}</p>
    </form>`;
  const form = $("[data-gmail]", el);
  const result = $("[data-result]", el);
  const show = (ok, msg) => {
    result.className = `rounded-lg px-3 py-2 text-sm ${ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`;
    result.textContent = `${ok ? "✓" : "✕"} ${msg}`;
  };
  const values = () => ({ address: form.address.value.trim(), label: form.label.value.trim() || "Budget",
                          enabled: form.enabled.checked, password: form.password.value || null });
  async function save(extra = {}) {
    cfg = await api("/api/email/settings", { method: "PUT", body: { ...values(), ...extra } });
    form.password.value = "";
    form.password.placeholder = cfg.has_password ? "Saved — type to replace" : "16-letter app password";
    return cfg;
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await save(); toast("Gmail settings saved"); } catch (err) { show(false, err.message); }
  });
  form.addEventListener("change", (e) => { if (e.target.name === "enabled") save().then(() => toast("Saved")).catch((err) => show(false, err.message)); });
  $("[data-forget]", el)?.addEventListener("click", async () => {
    await save({ forget_password: true, password: null });
    toast("Password removed");
    settingsGmail(el);
  });
  $("[data-test]", el).addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Testing…";
    try {
      const v = values();
      const r = await api("/api/email/test", { method: "POST", body: { address: v.address, label: v.label, password: v.password } });
      show(r.ok, r.message);
    } catch (err) { show(false, err.message); }
    finally { e.target.disabled = false; e.target.textContent = "Test connection"; }
  });
  $("[data-check]", el).addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Checking…";
    try {
      if (form.password.value || form.address.value.trim() !== cfg.address) await save();
      const r = await api("/api/email/sync", { method: "POST" });
      $("[data-last]", el).textContent = syncSummary(r);
      if (r.error) show(false, r.error);
      else { show(true, syncSummary(r, "Checked just now")); emailWatch.lastRun = r.run; refreshReviewBadge(); }
    } catch (err) { show(false, err.message); }
    finally { e.target.disabled = false; e.target.textContent = "Check now"; }
  });
}

/** The "Needs review" list: emails that couldn't be imported on their own. */
async function reviewSection(el, { onChange } = {}) {
  const items = await api("/api/email/review");
  if (!items.length) { el.innerHTML = ""; el.classList.add("hidden"); return 0; }
  el.classList.remove("hidden");
  el.innerHTML = `
    <div class="flex items-baseline justify-between mb-2">
      <h2 class="font-semibold">Needs review <span class="ml-1 rounded-full bg-amber-100 text-amber-800 text-xs px-2 py-0.5">${items.length}</span></h2>
      <span class="text-xs text-slate-400">From your iPhone's Apple Pay emails</span>
    </div>
    <div class="space-y-3">${items.map((it) => `
      <form data-item="${it.id}" class="card p-4 space-y-3">
        <div class="flex items-start justify-between gap-2">
          <p class="text-sm text-amber-800"><b>${esc(it.reason[0].toUpperCase() + it.reason.slice(1))}</b></p>
          <span class="text-xs text-slate-400 shrink-0">${it.received_at ? fmtDateTime(it.received_at) : ""}</span>
        </div>
        ${it.line ? `<code class="block text-xs bg-slate-50 rounded px-2 py-1 text-slate-600 break-all">${esc(it.line)}</code>` : ""}
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div><label class="label">Date</label>${dateField("date", it.date || todayISO())}</div>
          <div><label class="label">Merchant</label><input name="merchant" class="input" value="${esc(it.merchant || "")}" placeholder="Where?"></div>
          <div><label class="label">Amount (€)</label><input name="amount" class="input tabular" inputmode="decimal"
               value="${it.amount_cents ? (it.amount_cents / 100).toFixed(2).replace(".", ",") : ""}" placeholder="0,00"></div>
          <div><label class="label">Category</label><select name="category" class="input">
               <option value="">Auto</option>${categoryOptions(it.category_id ?? "", { all: false, uncategorized: false })}</select></div>
        </div>
        <div class="flex gap-2">
          <button class="btn btn-primary">Add expense</button>
          <button type="button" data-dismiss class="btn btn-ghost">${it.duplicate_of ? "It's a duplicate, skip" : "Dismiss"}</button>
        </div>
      </form>`).join("")}</div>`;
  wireDateFields(el);
  el.onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target.closest("[data-item]");
    const date = parseDate(f.date.value), amount = parseAmount(f.amount.value);
    if (!f.merchant.value.trim()) return toast("Enter the merchant", "error");
    if (!(amount > 0)) return toast("Enter an amount above 0", "error");
    if (!date) return toast("Enter the date as DD/MM/YYYY", "error");
    try {
      await api(`/api/email/review/${f.dataset.item}/accept`, { method: "POST", body: {
        merchant: f.merchant.value.trim(), amount: amount.toFixed(2), date,
        category_id: f.category.value ? Number(f.category.value) : null } });
      toast("Expense added");
      await reviewSection(el, { onChange }); refreshReviewBadge(); onChange?.();
    } catch (err) { toast(err.message, "error"); }
  };
  el.onclick = async (e) => {
    if (!e.target.closest("[data-dismiss]")) return;
    const f = e.target.closest("[data-item]");
    await api(`/api/email/review/${f.dataset.item}/dismiss`, { method: "POST" });
    toast("Dismissed");
    await reviewSection(el, { onChange }); refreshReviewBadge(); onChange?.();
  };
  return items.length;
}

// --- watch for new imports while the app is open -------------------------

const emailWatch = { lastRun: null };

function setReviewBadge(n) {
  $$('[data-route="transactions"]').forEach((a) => {
    let b = $("[data-badge]", a);
    if (!n) { b?.remove(); return; }
    if (!b) {
      b = document.createElement("span");
      b.dataset.badge = "";
      b.className = "ml-1 inline-flex min-w-[1.1rem] h-[1.1rem] items-center justify-center rounded-full bg-amber-500 text-white text-[10px] font-semibold px-1";
      a.append(b);
    }
    b.textContent = n;
  });
}
async function refreshReviewBadge() {
  try { setReviewBadge((await api("/api/email/status")).review_count); } catch { /* offline */ }
}

async function pollEmail() {
  let s;
  try { s = await api("/api/email/status"); } catch { return; }
  setReviewBadge(s.review_count);
  const last = s.last_sync;
  if (!last || last.run == null) return;
  if (emailWatch.lastRun === null) {
    emailWatch.lastRun = last.run;
    // The check that runs at launch usually finishes just after the page loads.
    const ageSeconds = (Date.now() - new Date(last.finished_at).getTime()) / 1000;
    if (ageSeconds > 90) return;
  } else if (last.run === emailWatch.lastRun) {
    return;
  }
  emailWatch.lastRun = last.run;
  if (last.error || !(last.imported || last.review)) return;
  const msg = [last.imported ? plural(last.imported, "new transaction imported", "new transactions imported") : "",
               last.review ? plural(last.review, "needs review", "need review") : ""].filter(Boolean).join(" · ");
  toast(msg, "ok", 6000);
  const { route } = parseHash();
  if (["home", "transactions"].includes(route) && $("#modal").classList.contains("hidden")) render();
}

/* ===========================================================================
   Phone access (Settings, Mac only) and signing out on a phone
   ======================================================================== */

/** SQLite's datetime('now') is UTC ("2026-10-05 14:43:00"); show it in local time. */
function fmtUtc(sqliteUtc) {
  const d = new Date(sqliteUtc.replace(" ", "T") + "Z");
  return `${fmtDate(isoOf(d))} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function deviceName(ua) {
  ua = ua || "";
  const kind = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android phone"
    : /Macintosh/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows PC" : "Device";
  const browser = /CriOS|Chrome/.test(ua) ? "Chrome" : /FxiOS|Firefox/.test(ua) ? "Firefox" : /Safari/.test(ua) ? "Safari" : "";
  return browser ? `${kind} · ${browser}` : kind;
}

async function settingsPhone(el) {
  let st = await api("/api/phone");
  function render() {
    const ts = st.tailscale || {};
    const home = st.urls.filter((u) => u.startsWith("http://"));
    const anywhere = st.urls.find((u) => u.startsWith("https://"));
    const ext = (url, label) => `<a href="${esc(url)}" data-ext class="underline font-medium">${label}</a>`;
    el.innerHTML = `
      <p class="text-sm text-slate-500 mb-4">Use Budget on your phone, at home or anywhere. Phones sign in with a password and can use everything except these ${computer()}-only settings.</p>
      ${st.available ? "" : `<p class="text-sm text-amber-700 mb-3">Not available in browser mode. Open the Budget app (or <code>python3 run.py</code>) to use it.</p>`}
      <form data-phone class="space-y-3" autocomplete="off">
        <div class="grid sm:grid-cols-3 gap-3">
          <div class="sm:col-span-2"><label class="label">${st.has_password ? "Change password" : "Password for your phone"}</label>
            <input name="password" type="password" autocomplete="new-password" class="input"
                   placeholder="${st.has_password ? "Saved — type to change (signs phones out)" : `At least ${st.min_password_length} characters`}"></div>
          <div><label class="label">Port</label><input name="port" class="input tabular" inputmode="numeric" value="${st.port}"></div>
        </div>
        <label class="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
          <input type="checkbox" name="enabled" class="rounded border-slate-300" ${st.enabled ? "checked" : ""} ${st.available ? "" : "disabled"}>
          Let my phone open Budget
        </label>
        ${st.mac ? `<label class="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
          <input type="checkbox" name="keep_awake" class="rounded border-slate-300 mt-0.5" ${st.keep_awake ? "checked" : ""}>
          <span>Keep the Mac awake while it's plugged in and Budget is open<span class="block text-xs text-slate-400">So your phone can reach it. A closed lid still puts it to sleep; your phone then saves expenses until it's back.</span></span>
        </label>` : ""}
        <button class="btn btn-primary">Save</button>
      </form>
      ${st.error ? `<div class="mt-3 rounded-lg bg-red-50 text-red-800 px-3 py-2 text-sm">✕ ${esc(st.error)}</div>` : ""}
      ${st.running ? `
        ${anywhere ? `
          <div class="mt-4 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
            <p class="font-medium">Anywhere: Wi-Fi or 4G</p>
            <p class="font-mono text-base font-semibold select-all break-all my-1">${esc(anywhere)}</p>
            <ol class="list-decimal ml-4 space-y-0.5 text-emerald-900/90">
              <li>On your iPhone, install <b>Tailscale</b> and sign in with the same account as this ${computer()}.</li>
              <li>Open this address in Safari and sign in with the password above.</li>
              <li>Tap Share → <b>Add to Home Screen</b>.</li></ol>
            <p class="text-xs text-emerald-800 mt-2">Budget then opens like an app, even when your ${computer()} is asleep: it shows your last numbers, and expenses you add wait on the phone until the ${computer()} is back.</p>
          </div>` : ts.pending ? `
          <p class="mt-4 text-sm text-slate-500">Setting up your anywhere address…</p>` : ts.enable_url ? `
          <div class="mt-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <p>${esc(ts.error || "")}</p>
            <p class="mt-1">${ext(ts.enable_url, "Turn on HTTPS in Tailscale")}, then untick and tick <b>Let my phone open Budget</b> and Save.</p>
          </div>` : ts.installed && ts.error ? `
          <div class="mt-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">${esc(ts.error)}</div>` : !ts.installed ? `
          <div class="mt-4 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-700">
            <p class="font-medium text-slate-900">Use it away from home too</p>
            <p class="mt-1">Install ${ext("https://tailscale.com/download", "Tailscale")} (free) on this ${computer()} and your iPhone, and sign in to both with the same account.
              Then untick and tick <b>Let my phone open Budget</b> and Save: a private, encrypted address appears here.</p>
          </div>` : ""}
        ${home.length ? `
          <div class="mt-3 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-700">
            <p class="mb-1">${anywhere ? "Or at home, on the same Wi-Fi:" : "At home, on the same Wi-Fi, open the browser (Safari on iPhone) and go to:"}</p>
            ${home.map((u) => `<p class="font-mono font-semibold select-all break-all">${esc(u)}</p>`).join("")}
            <p class="text-xs text-slate-500 mt-1">${onPC() ? "If your PC's IP address changes, come back here for the new one." : "The <b>.local</b> address keeps working when your Mac's IP changes."}</p>
          </div>` : ""}` : ""}
      <div class="mt-4">
        <div class="flex items-baseline justify-between">
          <h3 class="text-sm font-medium text-slate-700">Signed-in devices</h3>
          ${st.sessions.length ? `<button data-signout-all class="text-xs text-slate-500 hover:text-red-600">Sign out all</button>` : ""}
        </div>
        ${st.sessions.length ? `<ul class="mt-1 text-sm divide-y divide-slate-100">${st.sessions.map((x) => `
          <li class="py-1.5 flex justify-between gap-2"><span>${esc(deviceName(x.user_agent))} <span class="text-slate-400">${esc(x.ip || "")}</span></span>
            <span class="text-xs text-slate-400">last used ${fmtUtc(x.last_seen)}</span></li>`).join("")}</ul>`
        : `<p class="text-xs text-slate-400 mt-1">None.</p>`}
      </div>
      <p class="text-xs text-slate-400 mt-4">The home Wi-Fi addresses aren't encrypted (plain http), so only use them on Wi-Fi you trust.
        The Tailscale address is encrypted, and only your own devices can reach it.</p>`;
    const form = $("[data-phone]", el);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const port = Number(form.port.value);
      if (!(port >= 1024 && port <= 65535)) return toast("Port must be between 1024 and 65535", "error");
      try {
        st = await api("/api/phone", { method: "PUT", body: { enabled: form.enabled.checked, port, password: form.password.value || null,
                                                              ...(form.keep_awake ? { keep_awake: form.keep_awake.checked } : {}) } });
        render();
        toast(st.error ? "Saved, but phone access couldn't start" : st.running ? "Phone access is on" : "Saved", st.error ? "error" : "ok");
        settingsHooks.refreshSummaries?.();
      } catch (err) { toast(err.message, "error"); }
    });
    el.querySelectorAll("[data-ext]").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      if (desktop()?.open_url) desktop().open_url(a.href); else window.open(a.href, "_blank");
    }));
    // Tailscale takes a few seconds to publish the address: check back.
    if (ts.pending && el.isConnected) setTimeout(async () => { if (!el.isConnected) return; st = await api("/api/phone"); render(); }, 2500);
    $("[data-signout-all]", el)?.addEventListener("click", async () => {
      st = await api("/api/phone/sign-out-all", { method: "POST" });
      render();
      toast("All phones signed out");
    });
  }
  render();
}

function settingsThisPhone(el) {
  el.innerHTML = `
    <p class="text-sm text-slate-500 mb-3">You're signed in on this phone. Gmail and phone access settings can only be changed on the ${computer()}.</p>
    <button data-signout class="btn btn-secondary">Sign out</button>`;
  $("[data-signout]", el).addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" });
    navigator.serviceWorker?.controller?.postMessage("forget");   // drop the numbers saved on this phone
    location.replace("/login");
  });
}

/* ===========================================================================
   Router and navigation
   ======================================================================== */

const NAV = [
  { route: "home", label: "Home", icon: `<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h14V10"/>` },
  { route: "transactions", label: "Transactions", icon: `<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>` },
  { route: "add", label: "Add", icon: `<path d="M12 7v10M7 12h10"/>` },
  { route: "settings", label: "Settings", icon: `<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>` },
];

const VIEWS = {
  home: viewDashboard,
  transactions: viewTransactions,
  add: viewAdd,
  import: viewImport,
  settings: viewSettings,
};
const ALIASES = { dashboard: "home" };   // old links

function buildNav() {
  $("#top-nav").innerHTML = NAV.filter((n) => n.route !== "add").map((n) =>
    `<a href="#/${n.route}" data-route="${n.route}" class="nav-link rounded-lg px-3 py-1.5 hover:text-slate-900">${n.label}</a>`).join("");
  const svg = (icon, cls) => `<svg class="${cls}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24">${icon}</svg>`;
  $("#bottom-nav").innerHTML = NAV.map((n) => n.route === "add"
    ? `<a href="#/add" data-route="add" aria-label="Add expense" class="flex items-center justify-center py-1.5">
        <span class="w-[3.25rem] h-[3.25rem] -mt-6 rounded-full bg-slate-900 text-slate-50 shadow-[0_8px_18px_-6px_rgb(0_0_0/.45)] inline-flex items-center justify-center">${svg(n.icon, "w-7 h-7")}</span></a>`
    : `<a href="#/${n.route}" data-route="${n.route}" class="bottom-link flex flex-col items-center gap-0.5 py-2">
        ${svg(n.icon, "w-6 h-6")}${n.label}</a>`).join("");
}

function parseHash() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, qs] = h.split("?");
  const route = ALIASES[path] || path;
  return { route: VIEWS[route] ? route : "home", params: new URLSearchParams(qs || "") };
}

async function render() {
  const token = ++state.renderToken;
  const { route, params } = parseHash();
  $$("[data-route]").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  document.body.dataset.route = route;
  document.body.style.removeProperty("--field"); document.body.style.removeProperty("--field-deep");   // Add's preview
  if (route !== "home") refreshState();
  closeModal();
  destroyCharts();
  const root = $("#view");
  root.innerHTML = "";
  try {
    await VIEWS[route](root, params, () => token === state.renderToken);
  } catch (err) {
    if (token !== state.renderToken) return;
    root.innerHTML = `<div class="card p-6 text-red-600">Something went wrong: ${esc(err.message)}</div>`;
  }
}

window.addEventListener("hashchange", render);

// Charts take their colours when drawn, so redraw Home after a theme change.
window.addEventListener("themechange", () => { if (state.charts.length) render(); });

// "N" adds an expense from anywhere (when you're not typing).
document.addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() !== "n" || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.target.closest("input, textarea, select, [contenteditable]") || !$("#modal").classList.contains("hidden")) return;
  e.preventDefault();
  location.hash = "#/add";
});

(async function start() {
  try { state.local = (await (await fetch("/api/auth/me")).json()).local; } catch { /* assume local */ }
  try { state.prefs = await api("/api/preferences"); if (Theme.canonical(state.prefs.theme) !== Theme.choice) Theme.set(state.prefs.theme); } catch { /* keep the cached theme */ }
  buildNav();
  try { await loadCategories(); } catch (e) { toast("Can't reach the server: " + e.message, "error"); }
  render();
  pollEmail();
  setInterval(pollEmail, 20000);
  if (!state.local) {
    if ("serviceWorker" in navigator && window.isSecureContext) {
      // A new version of Budget took over: reload once so it's used straight away.
      const hadOne = !!navigator.serviceWorker.controller;
      navigator.serviceWorker.addEventListener("controllerchange", () => { if (hadOne && !document.querySelector("#modal:not(.hidden)")) location.reload(); });
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
    Offline.draw();
    Outbox.flush();
    addEventListener("online", () => Outbox.flush());
    document.addEventListener("visibilitychange", () => { if (!document.hidden) Outbox.flush(); });
    setInterval(() => Outbox.flush(), 30000);
  }
})();
