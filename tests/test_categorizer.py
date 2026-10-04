import pytest

from app import categorizer
from app.categorizer import suggest
from app.normalize import normalize_merchant


@pytest.mark.parametrize("raw, expected", [
    ("MERCADONA MADRID 4521", "mercadona"),
    ("Mercadona", "mercadona"),
    ("Compra en DIA %ALCALA, S.A.", "dia"),
    ("UBER *EATS", "uber eats"),
    ("McDonald's", "mcdonalds"),
    ("H&M", "hm"),
    ("Café Comercial", "cafe comercial"),
    ("BOLT.EU/O/2301", "bolt"),
    ("PayPal", "paypal"),      # all noise -> falls back instead of returning ""
    ("", ""),
])
def test_normalize(raw, expected):
    assert normalize_merchant(raw) == expected


@pytest.mark.parametrize("merchant, category", [
    ("MERCADONA MADRID 4521", "Groceries"),
    ("Lidl", "Groceries"),
    ("DIA %MADRID 0042", "Groceries"),
    ("UBER *EATS", "Eating Out"),       # longer keyword beats "uber"
    ("UBER *TRIP", "Transport"),
    ("Glovoapp", "Eating Out"),          # prefix match
    ("Metro de Madrid", "Transport"),
    ("Metropolitan Abascal", "Gym & Fitness"),  # not "metro"
    ("Amazon Prime", "Subscriptions"),
    ("AMZN Mktp ES", "Shopping"),
    ("Spotify AB", "Subscriptions"),
    ("Farmacia Lda. Sol", "Health & Personal Care"),
])
def test_keyword_rules(conn, cat, merchant, category):
    s = suggest(conn, merchant)
    assert (s.source, s.category_id) == ("rule", cat(category))


def test_keywords_match_whole_words_only(conn):
    # "dia" must not match inside "media", and "bar" not inside "barcelona".
    assert suggest(conn, "Medianoche Store").category_id is None
    assert suggest(conn, "Barnizados Lopez").category_id is None


def test_typo_in_known_brand(conn, cat):
    s = suggest(conn, "Carrefur Express")
    assert (s.source, s.category_id) == ("rule", cat("Groceries"))


def test_unknown_merchant_without_ai_is_uncategorized(conn):
    s = suggest(conn, "Tienda Random XYZ", use_ai=True)  # no API key in tests
    assert (s.source, s.category_id) == ("none", None)


def test_learned_rule_is_used_next_time(conn, cat):
    categorizer.learn(conn, "Tienda Random XYZ", cat("Other"))
    s = suggest(conn, "TIENDA RANDOM XYZ MADRID 12")
    assert (s.source, s.category_id) == ("learned", cat("Other"))


def test_your_correction_beats_builtin_rule(conn, cat):
    assert suggest(conn, "Mercadona").category_id == cat("Groceries")
    categorizer.learn(conn, "MERCADONA 1234", cat("Other"))
    s = suggest(conn, "Mercadona Madrid")
    assert (s.source, s.category_id) == ("learned", cat("Other"))


def test_latest_correction_wins(conn, cat):
    categorizer.learn(conn, "Cafe Pepe", cat("Eating Out"))
    categorizer.learn(conn, "Cafe Pepe", cat("University"))
    assert suggest(conn, "Cafe Pepe").category_id == cat("University")


def test_fuzzy_match_against_learned(conn, cat):
    categorizer.learn(conn, "La Mallorquina", cat("Eating Out"))
    s = suggest(conn, "LA MALLORQINA")
    assert (s.source, s.category_id) == ("fuzzy", cat("Eating Out"))


def test_fuzzy_does_not_stretch_to_different_merchants(conn, cat):
    categorizer.learn(conn, "Uber", cat("Other"))
    # "uber eats" is a different merchant; the specific keyword should win.
    assert suggest(conn, "Uber Eats").category_id == cat("Eating Out")


def test_ai_used_only_when_enabled_and_result_cached(conn, cat, monkeypatch):
    calls = []
    def fake_claude(c, merchant):
        calls.append(merchant)
        return cat("Entertainment")
    monkeypatch.setattr(categorizer, "ask_claude", fake_claude)

    assert suggest(conn, "Sala Equis", use_ai=True).source == "none"  # no key -> no AI
    assert calls == []

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    s = suggest(conn, "Sala Equis", use_ai=True)
    assert (s.source, s.category_id) == ("ai", cat("Entertainment"))
    suggest(conn, "SALA EQUIS", use_ai=True)
    assert calls == ["Sala Equis"]  # second lookup came from the cache


def test_ai_failure_falls_back_to_uncategorized(conn, monkeypatch):
    def broken(c, merchant):
        raise categorizer.AIUnavailable("offline")
    monkeypatch.setattr(categorizer, "ask_claude", broken)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    s = suggest(conn, "Sala Equis", use_ai=True)
    assert (s.source, s.category_id) == ("none", None)


def test_learned_beats_ai_cache(conn, cat, monkeypatch):
    monkeypatch.setattr(categorizer, "ask_claude", lambda c, m: cat("Entertainment"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    suggest(conn, "Sala Equis", use_ai=True)
    categorizer.learn(conn, "Sala Equis", cat("Other"))
    assert suggest(conn, "Sala Equis", use_ai=True).category_id == cat("Other")
