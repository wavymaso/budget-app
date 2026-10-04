"""Suggest a category for a merchant, trying each layer in order:

1. learned  - a category you chose before for this exact (normalized) merchant
2. fuzzy    - a learned merchant that is nearly identical ("mercadna" ~ "mercadona")
3. rule     - built-in keywords for common Spanish merchants
4. ai       - Claude's guess (only if ANTHROPIC_API_KEY is set)
5. none     - Uncategorized; you pick, and that choice is learned

Your own choices (layers 1-2) always win over rules and AI.
"""
import json
import logging
import sqlite3
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from . import config
from .normalize import normalize_merchant

log = logging.getLogger("budget.categorizer")

FUZZY_CUTOFF = 88          # 0-100; high so only typos/near-duplicates match
MIN_FUZZY_LENGTH = 4       # very short names ("bp", "dia") must match exactly
MIN_PREFIX_KEYWORD = 5     # "glovo" also matches "glovoapp"
AI_MODEL = "claude-opus-5-5"
UNCATEGORIZED = "Uncategorized"


@dataclass
class Suggestion:
    category_id: int | None
    source: str               # learned | fuzzy | rule | ai | none
    normalized: str
    matched: str | None = None


def suggest(conn: sqlite3.Connection, merchant: str, *, use_ai: bool = False) -> Suggestion:
    norm = normalize_merchant(merchant)
    if not norm:
        return Suggestion(None, "none", norm)

    row = conn.execute(
        "SELECT category_id FROM merchant_rules WHERE merchant_norm = ?", (norm,)
    ).fetchone()
    if row:
        return Suggestion(row[0], "learned", norm, norm)

    found = _fuzzy_learned(conn, norm) or _keyword_rule(conn, norm)
    if found:
        return found

    cached = conn.execute(
        "SELECT category_id FROM ai_cache WHERE merchant_norm = ?", (norm,)
    ).fetchone()
    if cached:
        return Suggestion(cached[0], "ai" if cached[0] else "none", norm)

    if use_ai and config.anthropic_api_key():
        try:
            category_id = ask_claude(conn, merchant)
        except AIUnavailable as exc:
            log.warning("AI categorization skipped: %s", exc)
        else:
            # Cache "don't know" too, so the same merchant isn't sent again.
            conn.execute(
                "INSERT OR REPLACE INTO ai_cache (merchant_norm, category_id) VALUES (?, ?)",
                (norm, category_id),
            )
            conn.commit()
            return Suggestion(category_id, "ai" if category_id else "none", norm)

    return Suggestion(None, "none", norm)


def _fuzzy_learned(conn: sqlite3.Connection, norm: str) -> Suggestion | None:
    if len(norm) < MIN_FUZZY_LENGTH:
        return None
    learned = {
        r[0]: r[1]
        for r in conn.execute("SELECT merchant_norm, category_id FROM merchant_rules")
        if len(r[0]) >= MIN_FUZZY_LENGTH
    }
    if not learned:
        return None
    best = process.extractOne(norm, learned.keys(), scorer=fuzz.token_sort_ratio,
                              score_cutoff=FUZZY_CUTOFF)
    if best is None:
        return None
    return Suggestion(learned[best[0]], "fuzzy", norm, best[0])


def _keyword_rule(conn: sqlite3.Connection, norm: str) -> Suggestion | None:
    """Whole-word keyword match. Exact words beat prefixes; longer keywords win."""
    padded = f" {norm} "
    tokens = norm.split()
    best, best_rank = None, None
    for keyword, category_id in conn.execute("SELECT keyword, category_id FROM keyword_rules"):
        if f" {keyword} " in padded or (" " in keyword and keyword.replace(" ", "") in tokens):
            rank = (1, len(keyword))
        elif " " not in keyword and len(keyword) >= MIN_PREFIX_KEYWORD and any(
            t.startswith(keyword) for t in tokens
        ):
            rank = (0, len(keyword))
        else:
            continue
        if best_rank is None or rank > best_rank:
            best, best_rank = (keyword, category_id), rank
    if best is None:
        return _fuzzy_keyword(conn, tokens)
    return Suggestion(best[1], "rule", norm, best[0])


def _fuzzy_keyword(conn: sqlite3.Connection, tokens: list[str]) -> Suggestion | None:
    """Typos in well-known names: "carrefur" -> carrefour, "mercadna" -> mercadona."""
    words = [t for t in tokens if len(t) >= MIN_PREFIX_KEYWORD]
    keywords = {
        kw: cid for kw, cid in conn.execute("SELECT keyword, category_id FROM keyword_rules")
        if " " not in kw and len(kw) >= MIN_PREFIX_KEYWORD
    }
    best = None
    for word in words:
        hit = process.extractOne(word, keywords.keys(), scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF)
        if hit and (best is None or hit[1] > best[1]):
            best = hit
    if best is None:
        return None
    return Suggestion(keywords[best[0]], "rule", " ".join(tokens), best[0])


def learn(conn: sqlite3.Connection, merchant: str, category_id: int | None) -> None:
    """Remember that this merchant belongs to this category (your choice wins next time)."""
    norm = normalize_merchant(merchant)
    if not norm or category_id is None:
        return
    conn.execute(
        """INSERT INTO merchant_rules (merchant_norm, category_id) VALUES (?, ?)
           ON CONFLICT(merchant_norm) DO UPDATE SET
               category_id = excluded.category_id,
               hit_count = hit_count + 1,
               updated_at = datetime('now')""",
        (norm, category_id),
    )


# --- Claude fallback ---------------------------------------------------------

class AIUnavailable(Exception):
    pass


SYSTEM_PROMPT = (
    "You categorize card payments for a university student living in Madrid, Spain. "
    "You get the merchant text exactly as it appears on a bank or Apple Pay statement. "
    "Pick the single category that best fits what kind of business it is. "
    f"If you can't tell what the business is, answer \"{UNCATEGORIZED}\" rather than guessing."
)


def ask_claude(conn: sqlite3.Connection, merchant: str) -> int | None:
    """Return a category id, None if Claude isn't sure, or raise AIUnavailable."""
    import anthropic

    categories = conn.execute("SELECT id, name FROM categories ORDER BY sort_order, name").fetchall()
    ids_by_name = {r["name"]: r["id"] for r in categories}
    if not ids_by_name:
        return None

    client = anthropic.Anthropic(api_key=config.anthropic_api_key(), timeout=20.0, max_retries=1)
    try:
        response = client.beta.messages.create(
            model=AI_MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": "low",
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string", "enum": [*ids_by_name, UNCATEGORIZED]},
                        },
                        "required": ["category"],
                        "additionalProperties": False,
                    },
                },
            },
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Merchant: {merchant}"}],
        )
    except anthropic.AuthenticationError:
        raise AIUnavailable("ANTHROPIC_API_KEY was rejected; check the key in .env")
    except anthropic.RateLimitError:
        raise AIUnavailable("rate limited by the Claude API")
    except anthropic.APIStatusError as exc:
        raise AIUnavailable(f"Claude API error {exc.status_code}: {exc.message}")
    except anthropic.APIConnectionError:
        raise AIUnavailable("couldn't reach the Claude API (offline?)")

    if response.stop_reason != "end_turn":
        raise AIUnavailable(f"no answer (stop_reason={response.stop_reason})")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        name = json.loads(text)["category"]
    except (ValueError, KeyError, TypeError):
        raise AIUnavailable(f"unexpected reply: {text[:100]!r}")
    return ids_by_name.get(name)
