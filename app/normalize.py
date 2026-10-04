"""Turn messy card-statement merchant names into a clean matching key.

    "MERCADONA MADRID 4521"     -> "mercadona"
    "Compra en DIA %ALCALA, S.A." -> "dia"
    "UBER *EATS"                -> "uber eats"
    "McDonald's"                -> "mcdonalds"
"""
import re
import unicodedata

# Words that never help identify a merchant: places, legal suffixes,
# payment-terminal wording.
NOISE_WORDS = {
    # places around Madrid / Spain
    "madrid", "barcelona", "valencia", "sevilla", "alcala", "henares", "getafe",
    "mostoles", "leganes", "alcobendas", "pozuelo", "majadahonda", "fuenlabrada",
    "alcorcon", "torrejon", "boadilla", "rivas", "parla", "aravaca", "chamartin",
    "chamberi", "moncloa", "salamanca", "retiro", "centro", "sol", "atocha",
    "es", "esp", "spain", "espana", "eu", "ue",
    # legal forms
    "sa", "sl", "slu", "sau", "sll", "scoop", "ltd", "inc", "gmbh", "bv", "llc", "srl",
    # payment wording and processors
    "compra", "pago", "en", "tarjeta", "tarj", "card", "purchase", "pos", "tpv",
    "contactless", "paypal", "sumup", "sq", "zettle", "ref", "www",
}

_APOSTROPHES = re.compile(r"['’`´]")
_AMP_IN_WORD = re.compile(r"(?<=\w)&(?=\w)")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_merchant(raw: str) -> str:
    text = _strip_accents(raw or "").lower()
    text = _APOSTROPHES.sub("", text)          # mcdonald's -> mcdonalds
    text = _AMP_IN_WORD.sub("", text)          # h&m -> hm
    text = _NON_ALNUM.sub(" ", text)
    tokens = [
        t for t in text.split()
        if len(t) > 1                          # stray letters from "S.L." etc.
        and not any(ch.isdigit() for ch in t)  # store numbers, references
        and t not in NOISE_WORDS
    ]
    if tokens:
        return " ".join(tokens)
    # Everything was noise (e.g. just "PayPal"): fall back to a plain cleanup.
    return " ".join(_NON_ALNUM.sub(" ", _strip_accents(raw or "").lower()).split())
