"use strict";

/* ===========================================================================
   Helpers
   ======================================================================== */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  categories: [],
  charts: [],
  renderToken: 0,
  txFilters: { q: "", category_id: "", date_from: "", date_to: "", sort: "date:desc" },
};

const eurFormat = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });
const fmtMoney = (cents) => eurFormat.format((cents || 0) / 100);

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

async function api(path, { method = "GET", body } = {}) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
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

function toast(msg, kind = "ok") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = el.className.replace(/bg-\S+/g, "") + (kind === "error" ? " bg-red-600" : " bg-slate-900");
  el.classList.remove("hidden");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.add("hidden"), kind === "error" ? 5000 : 2500);
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

function categoryBadge(e) {
  if (!e.category_id) {
    return `<span class="inline-flex items-center gap-1 text-xs text-amber-700 bg-amber-50 rounded px-1.5 py-0.5">Uncategorized</span>`;
  }
  return `<span class="inline-flex items-center gap-1.5 text-xs text-slate-500">
    <span class="w-2 h-2 rounded-full" style="background:${esc(e.category_color)}"></span>${esc(e.category_name)}</span>`;
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

function expenseForm({ expense = null, onSaved }) {
  const isEdit = !!expense;
  const id = uid();
  const f = {
    categoryId: expense ? expense.category_id : null,
    source: expense?.category_id ? (expense.category_source || "manual") : null,
    // Once you tap a category yourself, suggestions stop overriding it.
    userPicked: isEdit && expense.category_id != null,
    seq: 0,
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
      <label class="mt-2 inline-flex items-center gap-2 text-xs text-slate-500 cursor-pointer">
        <input type="checkbox" name="refund" class="rounded border-slate-300" ${expense?.amount_cents < 0 ? "checked" : ""}>
        This is a refund (money back)
      </label>
    </div>
    <div>
      <label class="label" for="${id}-merchant">Merchant / description</label>
      <input id="${id}-merchant" name="merchant" class="input" autocomplete="off" autocapitalize="words"
             placeholder="e.g. Mercadona" value="${esc(expense?.merchant || "")}">
    </div>
    <div>
      <div class="flex items-center gap-2 mb-1.5 min-h-[20px]">
        <span class="label !mb-0">Category</span><span data-tag></span>
        <span data-thinking class="hidden text-[11px] text-slate-400">asking AI…</span>
      </div>
      <div data-chips class="flex flex-wrap gap-2"></div>
      <p data-hint class="hidden text-xs text-amber-700 mt-2"></p>
    </div>
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div>
        <label class="label">Date</label>
        ${dateField("date", expense?.date || todayISO())}
        <div class="flex gap-2 mt-2">
          <button type="button" data-day="0" class="text-xs text-slate-500 hover:text-slate-900 underline-offset-2 hover:underline">Today</button>
          <button type="button" data-day="-1" class="text-xs text-slate-500 hover:text-slate-900 underline-offset-2 hover:underline">Yesterday</button>
        </div>
      </div>
      <div>
        <label class="label" for="${id}-note">Note <span class="font-normal text-slate-400">(optional)</span></label>
        <input id="${id}-note" name="note" class="input" autocomplete="off" value="${esc(expense?.note || "")}">
      </div>
    </div>
    <p data-error class="hidden text-sm text-red-600"></p>
    <div data-actions class="flex flex-wrap items-center gap-2">
      <button type="submit" class="btn btn-primary py-3 sm:py-2 flex-1 sm:flex-none">${isEdit ? "Save changes" : "Add expense"}</button>
    </div>`;
  wireDateFields(el);

  const chips = $("[data-chips]", el);
  function renderChips() {
    chips.innerHTML = state.categories.map((c) => {
      const on = c.id === f.categoryId;
      return `<button type="button" data-cat="${c.id}" class="chip ${on ? "text-white border-transparent shadow-sm" : "bg-white border-slate-200 text-slate-700 hover:border-slate-400"}"
                style="${on ? `background:${esc(c.color)}` : ""}">
          <span class="w-2 h-2 rounded-full ${on ? "bg-white/80" : ""}" style="${on ? "" : `background:${esc(c.color)}`}"></span>${esc(c.name)}
        </button>`;
    }).join("");
    $("[data-tag]", el).innerHTML = f.categoryId && !f.userPicked ? sourceTag(f.source) : "";
  }
  chips.addEventListener("click", (e) => {
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
    };
    const btn = $("button[type=submit]", el);
    btn.disabled = true;
    try {
      const saved = await api(isEdit ? `/api/expenses/${expense.id}` : "/api/expenses",
                              { method: isEdit ? "PUT" : "POST", body });
      onSaved?.(saved);
    } catch (err) {
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
    f.categoryId = null; f.source = null; f.userPicked = false; f.seq++;
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
    toast("Expense deleted");
    onChange?.();
  });
  actions.append(del);
  openModal("Edit expense", form);
}

function expenseRow(e) {
  const refund = e.amount_cents < 0;
  return `<button type="button" data-expense="${e.id}" class="w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-slate-50 focus:bg-slate-50 focus:outline-none">
    <div class="min-w-0 flex-1">
      <div class="font-medium text-slate-900 truncate">${esc(e.merchant)}</div>
      <div class="flex items-center gap-2 mt-0.5 min-w-0">
        ${categoryBadge(e)}
        ${e.note ? `<span class="text-xs text-slate-400 truncate">· ${esc(e.note)}</span>` : ""}
      </div>
    </div>
    <div class="text-right shrink-0">
      <div class="font-semibold tabular ${refund ? "text-emerald-600" : "text-slate-900"}">${refund ? "+" : ""}${fmtMoney(Math.abs(e.amount_cents))}</div>
      <div class="text-xs text-slate-400 tabular">${fmtDate(e.date)}</div>
    </div>
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

async function viewAdd(root) {
  root.innerHTML = `
    <div class="grid lg:grid-cols-5 gap-6">
      <section class="lg:col-span-3">
        <h1 class="text-xl font-semibold mb-4">Add expense</h1>
        <div class="card p-5" data-form></div>
      </section>
      <section class="lg:col-span-2">
        <div class="flex items-baseline justify-between mb-4 lg:mt-1">
          <h2 class="font-semibold">Recent</h2>
          <a href="#/transactions" class="text-sm text-slate-500 hover:text-slate-900">See all →</a>
        </div>
        <div class="card divide-y divide-slate-100 overflow-hidden" data-recent></div>
      </section>
    </div>`;
  const recent = $("[data-recent]", root);
  let items = [];
  async function loadRecent() {
    const data = await api("/api/expenses?limit=6&sort=date&order=desc");
    items = data.items;
    recent.innerHTML = items.length
      ? items.map(expenseRow).join("")
      : `<p class="p-5 text-sm text-slate-400">Nothing yet. Your expenses will show up here.</p>`;
  }
  wireExpenseRows(recent, { find: (fn) => items.find(fn) }, loadRecent);

  const form = expenseForm({
    onSaved: (saved) => {
      toast(`Added ${fmtMoney(Math.abs(saved.amount_cents))} · ${saved.merchant}`);
      form.clearForm();
      loadRecent();
    },
  });
  $("[data-form]", root).append(form);
  await loadRecent();
  setTimeout(() => form.amount.focus(), 0);
}

async function viewTransactions(root, params) {
  const F = state.txFilters;
  // Links from the dashboard can pre-set filters: #/transactions?category_id=3&date_from=...
  if ([...params.keys()].length) {
    Object.assign(F, { q: "", category_id: "", date_from: "", date_to: "" });
    for (const k of ["q", "category_id", "date_from", "date_to"]) if (params.has(k)) F[k] = params.get(k);
  }
  root.innerHTML = `
    <div class="flex items-center justify-between mb-4">
      <h1 class="text-xl font-semibold">Transactions</h1>
      <a href="/api/export.csv" data-export class="btn btn-secondary">Export CSV</a>
    </div>
    <div class="card p-4 mb-4">
      <div class="grid grid-cols-2 md:grid-cols-12 gap-3">
        <div class="col-span-2 md:col-span-4">
          <label class="label">Search</label>
          <input name="q" class="input" placeholder="Merchant, note, category…" value="${esc(F.q)}">
        </div>
        <div class="col-span-2 md:col-span-3">
          <label class="label">Category</label>
          <select name="category_id" class="input">${categoryOptions(F.category_id)}</select>
        </div>
        <div class="md:col-span-2"><label class="label">From</label>${dateField("date_from", F.date_from)}</div>
        <div class="md:col-span-2"><label class="label">To</label>${dateField("date_to", F.date_to)}</div>
        <div class="col-span-2 md:col-span-1 flex items-end">
          <button type="button" data-clear class="btn btn-ghost w-full">Clear</button>
        </div>
      </div>
    </div>
    <div class="flex flex-wrap items-center justify-between gap-2 mb-2 px-1">
      <p data-summary class="text-sm text-slate-500"></p>
      <select name="sort" class="input !w-auto !py-1.5 text-sm">
        <option value="date:desc">Newest first</option>
        <option value="date:asc">Oldest first</option>
        <option value="amount:desc">Amount: high to low</option>
        <option value="amount:asc">Amount: low to high</option>
        <option value="merchant:asc">Merchant A–Z</option>
        <option value="category:asc">Category A–Z</option>
      </select>
    </div>
    <div class="card divide-y divide-slate-100 overflow-hidden" data-list></div>
    <div class="text-center mt-4"><button data-more class="btn btn-secondary hidden">Load more</button></div>`;
  wireDateFields(root);
  $("[name=sort]", root).value = F.sort;

  const list = $("[data-list]", root);
  const more = $("[data-more]", root);
  let items = [];
  const PAGE = 100;

  async function load(append = false) {
    const [sort, order] = F.sort.split(":");
    const qs = new URLSearchParams({ sort, order, limit: PAGE, offset: append ? items.length : 0 });
    for (const k of ["q", "category_id", "date_from", "date_to"]) if (F[k]) qs.set(k, F[k]);
    const data = await api(`/api/expenses?${qs}`);
    items = append ? items.concat(data.items) : data.items;
    $("[data-summary]", root).textContent =
      `${data.count} transaction${data.count === 1 ? "" : "s"} · ${fmtMoney(data.total_cents)}`;
    list.innerHTML = items.length
      ? items.map(expenseRow).join("")
      : `<p class="p-6 text-sm text-slate-400 text-center">No transactions match.</p>`;
    more.classList.toggle("hidden", items.length >= data.count);
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
    Object.assign(F, { q: "", category_id: "", date_from: "", date_to: "" });
    if (location.hash.includes("?")) location.hash = "#/transactions";
    else render();
  });
  more.addEventListener("click", () => load(true));
  await load();
}

/* ---------------------------------------------------------------------------
   Settings
   ------------------------------------------------------------------------ */

async function viewSettings(root) {
  root.innerHTML = `
    <h1 class="text-xl font-semibold mb-4">Settings</h1>
    <div class="space-y-6">
      <section data-budgets></section>
      <section class="card p-5">
        <div class="flex items-baseline justify-between mb-1">
          <h2 class="font-semibold">Categories</h2>
          <span class="text-xs text-slate-400">Changes save automatically</span>
        </div>
        <p class="text-sm text-slate-500 mb-4">Rename, recolor, reorder (the order is used in the add form), or delete.</p>
        <div data-cats class="divide-y divide-slate-100"></div>
        <form data-add-cat class="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-slate-100">
          <input type="color" name="color" value="#64748b" class="h-9 w-10 rounded border border-slate-300 cursor-pointer">
          <input name="name" class="input flex-1 min-w-[10rem]" placeholder="New category name" maxlength="40">
          <button class="btn btn-primary">Add</button>
        </form>
      </section>
      <section class="card p-5">
        <h2 class="font-semibold mb-1">Learned merchants</h2>
        <p class="text-sm text-slate-500 mb-4">Every time you confirm or correct a category, the app remembers it here. These always win over built-in rules and AI.</p>
        <input data-rule-q class="input mb-3" placeholder="Filter merchants…">
        <div data-rules class="divide-y divide-slate-100 max-h-[28rem] overflow-y-auto"></div>
      </section>
      <section data-data></section>
      <section class="card p-5">
        <h2 class="font-semibold mb-3">Integrations</h2>
        <div data-status class="text-sm text-slate-600 space-y-2"></div>
      </section>
    </div>`;

  const status = await api("/api/status");
  const dot = (on) => `<span class="inline-block w-2 h-2 rounded-full mr-2 ${on ? "bg-emerald-500" : "bg-slate-300"}"></span>`;
  $("[data-status]", root).innerHTML = `
    <p>${dot(status.ai_enabled)}AI categorization: <b>${status.ai_enabled ? "on" : "off"}</b>
      <span class="text-slate-400">${status.ai_enabled ? "(unknown merchants are sent to Claude)" : "(set ANTHROPIC_API_KEY)"}</span></p>
    <p>${dot(status.quickadd_enabled)}Quick-add API for iPhone Shortcuts: <b>${status.quickadd_enabled ? "on" : "off"}</b>
      <span class="text-slate-400">${status.quickadd_enabled ? "" : "(set QUICKADD_TOKEN)"}</span></p>
    <p>${dot(status.lan_enabled)}Reachable from your phone on Wi-Fi: <b>${status.lan_enabled ? "yes" : "no"}</b>
      <span class="text-slate-400">${status.lan_enabled ? "(quick-add only)" : "(set BUDGET_LAN=1)"}</span></p>
    <p class="text-xs text-slate-400 pt-1">Settings go in a <code class="bg-slate-100 rounded px-1">.env</code> file in
      <code class="bg-slate-100 rounded px-1 break-all">${esc(status.data_dir.replace(/^\/Users\/[^/]+/, "~"))}</code>.
      Quit and reopen Budget after changing it. See the README for details.</p>`;

  // --- categories ---------------------------------------------------------
  const catsEl = $("[data-cats]", root);
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
  }
  async function patchCat(id, body) {
    try {
      await api(`/api/categories/${id}`, { method: "PATCH", body });
      toast("Saved");
      await refreshCats();
      renderBudgets?.();
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
        renderBudgets?.();
      } catch (err) { toast(err.message, "error"); }
    }
  });
  $("[data-add-cat]", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const name = form.name.value.trim();
    if (!name) return;
    try {
      await api("/api/categories", { method: "POST", body: { name, color: form.color.value } });
      form.name.value = "";
      toast(`Added ${name}`);
      await refreshCats();
      renderBudgets?.();
    } catch (err) { toast(err.message, "error"); }
  });
  renderCats();

  // --- learned merchants ------------------------------------------------
  const rulesEl = $("[data-rules]", root);
  let rules = [];
  function renderRules() {
    const q = $("[data-rule-q]", root).value.trim().toLowerCase();
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
  $("[data-rule-q]", root).addEventListener("input", renderRules);
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

  // Filled in by later phases.
  var renderBudgets = await settingsBudgets($("[data-budgets]", root));
  await settingsData($("[data-data]", root));
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

function levelBadge(level) {
  const l = LEVELS[level];
  if (!l) return "";
  return `<span class="inline-flex items-center gap-1 text-[11px] font-medium text-slate-600">
    <span class="inline-flex w-3.5 h-3.5 rounded-full items-center justify-center text-[9px] text-white" style="background:${l.color}">${l.icon}</span>${l.label}</span>`;
}

function progressBar(s, { thick = false } = {}) {
  if (s.limit_cents == null) return "";
  const pct = s.limit_cents > 0 ? Math.max(0, Math.min(100, (s.spent_cents / s.limit_cents) * 100)) : (s.spent_cents > 0 ? 100 : 0);
  const pctLabel = s.pct == null ? "" : `${Math.round(s.pct)}%`;
  return `<div class="flex items-center gap-2">
    <div class="flex-1 ${thick ? "h-3" : "h-2"} rounded-full bg-slate-100 overflow-hidden" role="progressbar"
         aria-valuenow="${Math.round(s.pct ?? 0)}" aria-valuemin="0" aria-valuemax="100">
      <div class="h-full rounded-full transition-all" style="width:${pct}%;background:${LEVELS[s.level]?.color || "#94a3b8"}"></div>
    </div>
    <span class="text-xs text-slate-500 tabular w-10 text-right">${pctLabel}</span>
  </div>`;
}

function leftLine(s, periodWord, isCurrent) {
  if (s.limit_cents == null) return "";
  if (s.left_cents < 0) return `<b class="text-slate-900">${fmtMoney(-s.left_cents)}</b> over the limit`;
  const perDay = isCurrent && s.per_day_cents != null
    ? ` · <b class="text-slate-900">${fmtMoney(s.per_day_cents)}</b> per day` : "";
  return `<b class="text-slate-900">${fmtMoney(s.left_cents)}</b> left ${periodWord}${perDay}`;
}

async function settingsBudgets(el) {
  el.className = "card p-5";
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
    el.innerHTML = `
      <div class="flex items-baseline justify-between mb-1">
        <h2 class="font-semibold">Budgets &amp; limits</h2>
        <span class="text-xs text-slate-400">Saves as soon as you leave a box</span>
      </div>
      <p class="text-sm text-slate-500 mb-3">Leave a box empty for no limit.</p>
      <div class="grid grid-cols-[1fr_6.5rem_6.5rem] sm:grid-cols-[1fr_9rem_9rem] gap-2 text-xs font-medium text-slate-500 pb-1 border-b border-slate-100">
        <span></span><span class="text-right pr-2">Weekly</span><span class="text-right pr-2">Monthly</span>
      </div>
      ${row("all", "Overall", null, true)}
      <div class="divide-y divide-slate-50">
        ${state.categories.map((c) => row(c.id, c.name, c.color, false)).join("")}
      </div>
      <p data-sums class="text-xs text-slate-500 mt-3 space-x-2">${sumLine("week")} ${sumLine("month")}</p>`;
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

const CHART_INK = { text: "#64748b", grid: "#eef0f3", series: "#2a78d6", seriesSoft: "#9ec5f4", reference: "#334155" };
const monthName = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });
const monthShort = new Intl.DateTimeFormat("en-GB", { month: "short" });
const weekdayShort = new Intl.DateTimeFormat("en-GB", { weekday: "short" });
const dateObj = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };

function periodLabel(d) {
  if (d.period === "month") return monthName.format(dateObj(d.start));
  return `${fmtDate(d.start).slice(0, 5)} – ${fmtDate(d.end)}`;
}

function makeChart(canvas, config) {
  Chart.defaults.font.family = "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif";
  Chart.defaults.color = CHART_INK.text;
  const chart = new Chart(canvas, config);
  state.charts.push(chart);
  return chart;
}

const moneyTooltip = (ctx) => ` ${ctx.dataset.label ? ctx.dataset.label + ": " : ""}${fmtMoney(ctx.parsed.y ?? ctx.parsed)}`;
// Axis ticks in whole euros; fractional ticks are left unlabelled.
const axisMoney = (v) => (Number.isInteger(v / 100) ? `${v / 100} €` : "");

function glanceCard(title, s, d) {
  const word = d.period === "week" ? "this week" : "this month";
  return `<a href="#/transactions?date_from=${d.start}&date_to=${d.end}" class="card p-5 block hover:border-slate-300 transition">
    <div class="flex items-baseline justify-between">
      <h2 class="text-sm font-medium text-slate-500">${title}</h2>
      <span class="text-xs text-slate-400 tabular">${d.days_left} day${d.days_left === 1 ? "" : "s"} left</span>
    </div>
    <div class="mt-2 flex items-baseline gap-2 flex-wrap">
      <span class="text-3xl font-semibold tabular text-slate-900">${fmtMoney(s.spent_cents)}</span>
      ${s.limit_cents != null ? `<span class="text-sm text-slate-400 tabular">of ${fmtMoney(s.limit_cents)}</span>` : ""}
    </div>
    ${s.limit_cents != null ? `
      <div class="mt-3">${progressBar(s, { thick: true })}</div>
      <div class="mt-2 flex items-center justify-between gap-2 flex-wrap text-sm text-slate-600">
        <span>${leftLine(s, word, true)}</span>${levelBadge(s.level)}
      </div>`
      : `<p class="mt-3 text-sm text-slate-400">No ${d.period}ly limit. <span class="underline" data-goto-settings>Set one in Settings</span></p>`}
  </a>`;
}

async function viewDashboard(root, params) {
  const period = params.get("period") === "week" ? "week" : "month";
  const date = params.get("date") || "";
  const [glance, d] = await Promise.all([
    api("/api/budgets/status"),
    api(`/api/dashboard?period=${period}${date ? `&date=${date}` : ""}`),
  ]);
  const go = (p, dt) => `#/dashboard?period=${p}${dt ? `&date=${dt}` : ""}`;
  const periodWord = period === "week" ? "week" : "month";
  const total = d.overall.spent_cents;
  const change = d.prev_total_cents ? Math.round(((total - d.prev_total_cents) / Math.abs(d.prev_total_cents)) * 100) : null;
  const withLimit = d.categories.filter((c) => c.limit_cents != null);
  const spentCats = d.categories.filter((c) => c.spent_cents > 0).sort((a, b) => b.spent_cents - a.spent_cents);
  const positiveTotal = spentCats.reduce((a, c) => a + c.spent_cents, 0);
  const txLink = (extra = "") => `#/transactions?date_from=${d.start}&date_to=${d.end}${extra}`;

  root.innerHTML = `
    <div class="grid sm:grid-cols-2 gap-4">
      ${glanceCard("This week", glance.week.overall, glance.week)}
      ${glanceCard("This month", glance.month.overall, glance.month)}
    </div>

    <div class="flex flex-wrap items-center gap-3 mt-8 mb-4">
      <div class="inline-flex rounded-lg bg-slate-200/70 p-0.5 text-sm">
        ${["week", "month"].map((p) => `<a href="${go(p, date)}" class="px-3 py-1 rounded-md ${p === period ? "bg-white shadow-sm font-medium text-slate-900" : "text-slate-500 hover:text-slate-800"}">${p === "week" ? "Week" : "Month"}</a>`).join("")}
      </div>
      <div class="flex items-center gap-1">
        <a href="${go(period, d.prev_date)}" class="btn btn-ghost !px-2" aria-label="Previous ${periodWord}">‹</a>
        <span class="font-semibold text-slate-900 tabular min-w-[9rem] text-center">${periodLabel(d)}</span>
        <a href="${go(period, d.next_date)}" class="btn btn-ghost !px-2" aria-label="Next ${periodWord}">›</a>
      </div>
      ${d.is_current ? "" : `<a href="${go(period, "")}" class="text-sm text-slate-500 hover:text-slate-900 underline">Back to now</a>`}
      <span class="sm:ml-auto text-sm text-slate-500">
        Spent <b class="text-slate-900 tabular">${fmtMoney(total)}</b>
        ${change != null ? `· ${change >= 0 ? "+" : ""}${change}% vs previous ${periodWord}` : ""}
      </span>
    </div>

    <div class="grid lg:grid-cols-2 gap-4">
      <section class="card p-5">
        <h3 class="font-semibold mb-4">By category</h3>
        ${spentCats.length ? `
          <div class="flex flex-col sm:flex-row items-center gap-6">
            <div class="relative w-44 h-44 shrink-0">
              <canvas data-donut aria-label="Spending by category"></canvas>
              <div class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span class="text-xs text-slate-400">Total</span>
                <span class="font-semibold tabular text-slate-900">${fmtMoney(total)}</span>
              </div>
            </div>
            <ul class="flex-1 w-full space-y-1.5 text-sm">
              ${spentCats.map((c) => `<li>
                <a href="${txLink(`&category_id=${c.category_id ?? "none"}`)}" class="flex items-center gap-2 rounded px-1 -mx-1 hover:bg-slate-50">
                  <span class="w-2.5 h-2.5 rounded-sm shrink-0" style="background:${esc(c.color)}"></span>
                  <span class="flex-1 truncate text-slate-700">${esc(c.name)}</span>
                  <span class="text-slate-400 tabular text-xs">${Math.round((c.spent_cents / positiveTotal) * 100)}%</span>
                  <span class="tabular font-medium text-slate-900 w-20 text-right">${fmtMoney(c.spent_cents)}</span>
                </a></li>`).join("")}
            </ul>
          </div>` : `<p class="text-sm text-slate-400 py-10 text-center">No spending in this ${periodWord}.</p>`}
      </section>

      <section class="card p-5">
        <div class="flex items-baseline justify-between mb-4">
          <h3 class="font-semibold">Limits this ${periodWord}</h3>
          <a href="#/settings" class="text-xs text-slate-500 hover:text-slate-900">Edit limits</a>
        </div>
        ${d.overall.limit_cents != null ? `
          <div class="mb-4 pb-4 border-b border-slate-100">
            <div class="flex items-baseline justify-between text-sm mb-1.5">
              <span class="font-medium text-slate-900">Overall</span>
              <span class="tabular text-slate-500">${fmtMoney(d.overall.spent_cents)} / ${fmtMoney(d.overall.limit_cents)}</span>
            </div>
            ${progressBar(d.overall)}
            <p class="text-xs text-slate-500 mt-1">${leftLine(d.overall, "", d.is_current)}</p>
          </div>` : ""}
        ${withLimit.length ? `<div class="space-y-4">${withLimit.map((c) => `
          <div>
            <div class="flex items-baseline justify-between text-sm mb-1.5 gap-2">
              <span class="flex items-center gap-2 min-w-0 text-slate-700">
                <span class="w-2.5 h-2.5 rounded-sm shrink-0" style="background:${esc(c.color)}"></span>
                <span class="truncate">${esc(c.name)}</span></span>
              <span class="tabular text-slate-500 shrink-0">${fmtMoney(c.spent_cents)} / ${fmtMoney(c.limit_cents)}</span>
            </div>
            ${progressBar(c)}
            <p class="text-xs text-slate-500 mt-1">${leftLine(c, "", d.is_current)}</p>
          </div>`).join("")}</div>`
        : d.overall.limit_cents == null
          ? `<p class="text-sm text-slate-400 py-6 text-center">No limits yet. <a href="#/settings" class="underline">Set weekly or monthly limits</a> to see progress here.</p>`
          : `<p class="text-sm text-slate-400">No per-category limits for this ${periodWord}.</p>`}
      </section>

      <section class="card p-5 lg:col-span-2">
        <div class="flex items-baseline justify-between mb-3 gap-2 flex-wrap">
          <h3 class="font-semibold">Daily spending</h3>
          <span data-daily-note class="text-xs text-slate-500"></span>
        </div>
        <div class="h-56"><canvas data-daily aria-label="Spending per day"></canvas></div>
      </section>

      <section class="card p-5">
        <div class="flex items-baseline justify-between mb-3 gap-2 flex-wrap">
          <h3 class="font-semibold">Month by month</h3>
          ${d.monthly_limit_cents != null ? `<span class="text-xs text-slate-500 flex items-center gap-1.5"><span class="inline-block w-4 border-t-2 border-dashed" style="border-color:${CHART_INK.reference}"></span>Monthly limit</span>` : ""}
        </div>
        <div class="h-56"><canvas data-trend aria-label="Spending per month"></canvas></div>
      </section>

      <section class="card p-5">
        <h3 class="font-semibold mb-3">Top merchants</h3>
        ${d.top_merchants.length ? `<ol class="space-y-2.5">${d.top_merchants.map((m, i) => `
          <li><a href="${txLink(`&q=${encodeURIComponent(m.merchant)}`)}" class="block rounded px-1 -mx-1 hover:bg-slate-50">
            <div class="flex items-baseline gap-2 text-sm">
              <span class="text-slate-400 tabular w-4">${i + 1}</span>
              <span class="flex-1 truncate text-slate-800">${esc(m.merchant)}</span>
              <span class="text-xs text-slate-400">${m.count}×</span>
              <span class="tabular font-medium text-slate-900 w-20 text-right">${fmtMoney(m.cents)}</span>
            </div>
            <div class="ml-6 mt-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div class="h-full rounded-full" style="width:${Math.max(2, (m.cents / d.top_merchants[0].cents) * 100)}%;background:${esc(m.category_color || "#cbd5e1")}"></div>
            </div></a></li>`).join("")}</ol>`
        : `<p class="text-sm text-slate-400 py-6 text-center">Nothing yet.</p>`}
      </section>
    </div>`;

  $$("[data-goto-settings]", root).forEach((s) => s.addEventListener("click", (e) => { e.preventDefault(); location.hash = "#/settings"; }));

  // Donut: category colors follow the category, with a 2px surface gap between slices.
  if (spentCats.length) {
    makeChart($("[data-donut]", root), {
      type: "doughnut",
      data: {
        labels: spentCats.map((c) => c.name),
        datasets: [{ data: spentCats.map((c) => c.spent_cents), backgroundColor: spentCats.map((c) => c.color),
                     borderColor: "#ffffff", borderWidth: 2, hoverOffset: 4 }],
      },
      options: {
        cutout: "70%", maintainAspectRatio: false,
        plugins: { legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${fmtMoney(ctx.parsed)} (${Math.round(ctx.parsed / positiveTotal * 100)}%)` } } },
        onClick: (_, els) => {
          if (!els.length) return;
          const c = spentCats[els[0].index];
          location.hash = txLink(`&category_id=${c.category_id ?? "none"}`);
        },
      },
    });
  }

  // Daily bars, with the daily allowance as a reference line when there's an overall limit.
  const allowance = d.overall.limit_cents != null ? Math.round(d.overall.limit_cents / d.days_total) : null;
  if (allowance != null) $("[data-daily-note]", root).innerHTML =
    `<span class="inline-flex items-center gap-1.5"><span class="inline-block w-4 border-t-2 border-dashed" style="border-color:${CHART_INK.reference}"></span>Even pace: ${fmtMoney(allowance)} / day</span>`;
  const dailyLabels = d.daily.map((x) => period === "week"
    ? `${weekdayShort.format(dateObj(x.date))} ${Number(x.date.slice(8))}` : String(Number(x.date.slice(8))));
  makeChart($("[data-daily]", root), {
    data: {
      labels: dailyLabels,
      datasets: [
        { type: "bar", label: "Spent", data: d.daily.map((x) => x.cents),
          backgroundColor: d.daily.map((x) => x.date === d.today ? CHART_INK.series : (x.date > d.today ? CHART_INK.seriesSoft : CHART_INK.series)),
          borderRadius: 4, borderSkipped: "start", maxBarThickness: 28 },
        ...(allowance != null ? [{ type: "line", label: "Even pace", data: d.daily.map(() => allowance),
          borderColor: CHART_INK.reference, borderWidth: 2, borderDash: [5, 4], pointRadius: 0, pointHoverRadius: 0 }] : []),
      ],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false },
        tooltip: { callbacks: { title: (items) => fmtDate(d.daily[items[0].dataIndex].date), label: moneyTooltip } } },
      scales: {
        x: { grid: { display: false }, ticks: { autoSkip: true, maxRotation: 0 } },
        y: { beginAtZero: true, suggestedMax: 2000, grid: { color: CHART_INK.grid }, border: { display: false }, ticks: { callback: axisMoney, maxTicksLimit: 5 } },
      },
      onClick: (_, els) => {
        if (!els.length) return;
        const day = d.daily[els[0].index].date;
        location.hash = `#/transactions?date_from=${day}&date_to=${day}`;
      },
    },
  });

  // Month-by-month: the selected month in full color, the rest softer.
  const selectedMonth = d.start.slice(0, 7);
  makeChart($("[data-trend]", root), {
    data: {
      labels: d.trend.map((t) => monthShort.format(dateObj(t.month + "-01"))),
      datasets: [
        { type: "bar", label: "Spent", data: d.trend.map((t) => t.cents),
          backgroundColor: d.trend.map((t) => t.month === selectedMonth ? CHART_INK.series : CHART_INK.seriesSoft),
          borderRadius: 4, borderSkipped: "start", maxBarThickness: 28 },
        ...(d.monthly_limit_cents != null ? [{ type: "line", label: "Monthly limit", data: d.trend.map(() => d.monthly_limit_cents),
          borderColor: CHART_INK.reference, borderWidth: 2, borderDash: [5, 4], pointRadius: 0, pointHoverRadius: 0 }] : []),
      ],
    },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false },
        tooltip: { callbacks: { title: (items) => monthName.format(dateObj(d.trend[items[0].dataIndex].month + "-01")), label: moneyTooltip } } },
      scales: {
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true, suggestedMax: 10000, grid: { color: CHART_INK.grid }, border: { display: false }, ticks: { callback: axisMoney, maxTicksLimit: 5 } },
      },
      onClick: (_, els) => {
        if (!els.length) return;
        location.hash = go("month", d.trend[els[0].index].month + "-01");
      },
    },
  });
}

/* ===========================================================================
   Import (CSV) and the Data section of Settings
   ======================================================================== */

async function viewImport(root) {
  const S = { text: "", parsed: null, rows: [] };
  root.innerHTML = `
    <h1 class="text-xl font-semibold mb-1">Import a bank statement</h1>
    <p class="text-sm text-slate-500 mb-5">Download a CSV from your bank, drop it here, check the preview, then import.</p>
    <label data-drop class="card p-8 flex flex-col items-center justify-center text-center border-2 border-dashed border-slate-300 cursor-pointer hover:border-slate-400 transition">
      <svg class="w-8 h-8 text-slate-400 mb-2" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M4 20h16"/></svg>
      <span class="font-medium text-slate-700">Choose a CSV file</span>
      <span class="text-xs text-slate-400 mt-1" data-filename>or drag it here</span>
      <input type="file" accept=".csv,text/csv,.txt" class="hidden" data-file>
    </label>
    <section data-map class="hidden card p-5 mt-5"></section>
    <section data-preview class="hidden mt-5"></section>`;

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
  el.className = "card p-5";
  el.innerHTML = `
    <h2 class="font-semibold mb-1">Your data</h2>
    <p class="text-sm text-slate-500 mb-4">Everything is stored on this computer in
      <code data-db-path class="text-xs bg-slate-100 rounded px-1 break-all"></code>.
      Rebuilding or updating the app never touches it.</p>
    <div class="flex flex-wrap gap-2">
      <button data-backup class="btn btn-primary">Back up now</button>
      <a href="/api/export.csv" class="btn btn-secondary">Export all to CSV</a>
      <button data-show-folder class="btn btn-ghost hidden">Show in Finder</button>
    </div>
    <div data-backups class="mt-4 text-sm"></div>`;
  async function list() {
    const files = await api("/api/backups");
    $("[data-backups]", el).innerHTML = files.length ? `
      <p class="text-xs text-slate-500 mb-1">Backups (in the <code class="bg-slate-100 rounded px-1">backups</code> folder next to the database):</p>
      <ul class="text-xs text-slate-600 space-y-0.5 max-h-40 overflow-y-auto">${files.slice(0, 20).map((f) =>
        `<li class="tabular">${esc(f.file)} <span class="text-slate-400">· ${(f.size_bytes / 1024).toFixed(0)} KB</span></li>`).join("")}</ul>`
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
   Router and navigation
   ======================================================================== */

const NAV = [
  { route: "dashboard", label: "Dashboard", icon: `<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>` },
  { route: "transactions", label: "Transactions", icon: `<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>` },
  { route: "add", label: "Add", icon: `<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>` },
  { route: "import", label: "Import", icon: `<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>` },
  { route: "settings", label: "Settings", icon: `<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>` },
];

const VIEWS = {
  dashboard: viewDashboard,
  transactions: viewTransactions,
  add: viewAdd,
  import: viewImport,
  settings: viewSettings,
};

function buildNav() {
  $("#top-nav").innerHTML = NAV.filter((n) => n.route !== "add").map((n) =>
    `<a href="#/${n.route}" data-route="${n.route}" class="nav-link rounded-lg px-3 py-1.5 hover:text-slate-900">${n.label}</a>`).join("");
  $("#bottom-nav").innerHTML = NAV.map((n) =>
    `<a href="#/${n.route}" data-route="${n.route}" class="bottom-link flex flex-col items-center gap-0.5 py-2">
      <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24">${n.icon}</svg>
      ${n.label}</a>`).join("");
}

function parseHash() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, qs] = h.split("?");
  return { route: VIEWS[path] ? path : "dashboard", params: new URLSearchParams(qs || "") };
}

async function render() {
  const token = ++state.renderToken;
  const { route, params } = parseHash();
  $$("[data-route]").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
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
(async function start() {
  buildNav();
  try { await loadCategories(); } catch (e) { toast("Can't reach the server: " + e.message, "error"); }
  render();
})();
