"""Default data inserted the first time the app runs."""

# Colors are in a fixed order checked for color-blind safety: categories that
# sit next to each other in the charts stay distinguishable. Gray is kept for
# "Other" on purpose.
DEFAULT_CATEGORIES = [
    ("Groceries", "#2a78d6"),
    ("Eating Out", "#eb6834"),
    ("Transport", "#1baf7a"),
    ("Shopping", "#eda100"),
    ("Subscriptions", "#e87ba4"),
    ("Entertainment", "#008300"),
    ("Health & Personal Care", "#4a3aa7"),
    ("Gym & Fitness", "#e34948"),
    ("University", "#184f95"),
    ("Other", "#8a8984"),
]

# Keywords are matched as whole words against the normalized merchant name,
# so "dia" matches "DIA %MADRID" but not "MEDIA MARKT". When several keywords
# match, the longest wins ("uber eats" beats "uber").
KEYWORD_RULES = {
    "Groceries": [
        "mercadona", "carrefour", "lidl", "dia", "alcampo", "aldi", "eroski",
        "hipercor", "supercor", "consum", "ahorramas", "simply", "condis",
        "caprabo", "coviran", "spar", "sanchez romero", "bm supermercados",
        "supermercado", "supermarket", "fruteria", "panaderia", "carniceria",
    ],
    "Eating Out": [
        "glovo", "uber eats", "just eat", "justeat", "deliveroo", "telepizza",
        "mcdonalds", "mc donalds", "burger king", "kfc", "five guys", "taco bell",
        "dominos", "papa johns", "popeyes", "subway", "vips", "goiko", "montaditos",
        "tagliatella", "ginos", "starbucks", "rodilla", "pans company",
        "foster hollywood", "tgb", "tim hortons", "udon", "wok", "sushi",
        "restaurante", "restaurant", "cafeteria", "cafe", "bar", "pizzeria",
        "kebab", "tapas", "cerveceria", "taberna", "churreria", "heladeria",
    ],
    "Transport": [
        "metro", "metro de madrid", "emt", "renfe", "cercanias", "crtm",
        "consorcio transportes", "cabify", "uber", "bolt", "free now", "freenow",
        "taxi", "blablacar", "alsa", "avanza", "iryo", "ouigo", "bicimad",
        "lime", "dott", "repsol", "cepsa", "galp", "bp", "gasolinera",
        "parking", "telpark", "empark", "ryanair", "iberia", "vueling", "easyjet",
    ],
    "Shopping": [
        "zara", "primark", "amazon", "amzn", "hm", "pull bear", "pullbear",
        "bershka", "stradivarius", "mango", "massimo dutti", "uniqlo", "lefties",
        "oysho", "springfield", "decathlon", "el corte ingles", "fnac",
        "mediamarkt", "media markt", "ikea", "aliexpress", "shein", "temu",
        "normal", "tiger", "flying tiger", "action",
    ],
    "Subscriptions": [
        "netflix", "spotify", "icloud", "apple com bill", "hbo", "disney",
        "disney plus", "prime video", "amazon prime", "youtube premium",
        "google one", "google storage", "chatgpt", "openai", "anthropic",
        "dazn", "filmin", "crunchyroll", "audible", "duolingo", "notion",
        "adobe", "microsoft", "movistar", "vodafone", "orange", "digi", "lowi",
        "simyo", "pepephone", "jazztel", "masmovil", "yoigo", "patreon",
    ],
    "Entertainment": [
        "cine", "cines", "cinesa", "yelmo", "kinepolis", "renoir", "golem",
        "ticketmaster", "entradas", "eventbrite", "fever", "atrapalo", "dice",
        "steam", "playstation", "nintendo", "xbox", "epic games", "teatro",
        "museo", "parque warner", "bolera", "karaoke", "escape room",
    ],
    "Health & Personal Care": [
        "farmacia", "parafarmacia", "pharmacy", "druni", "primor", "sephora",
        "rituals", "kiko", "clinica", "dentista", "dental", "optica",
        "multiopticas", "peluqueria", "barberia", "barber", "hospital",
        "sanitas", "adeslas", "fisioterapia", "fisio",
    ],
    "Gym & Fitness": [
        "basic fit", "basicfit", "mcfit", "synergym", "holmes place",
        "anytime fitness", "altafit", "vivagym", "go fit", "gofit",
        "fitness park", "smartfit", "metropolitan", "gimnasio", "gym",
        "crossfit", "myprotein",
    ],
    "University": [
        "universidad", "university", "ucm", "complutense", "uam", "autonoma",
        "upm", "politecnica", "carlos iii", "urjc", "rey juan carlos", "comillas",
        "ceu", "esic", "nebrija", "matricula", "copisteria", "reprografia",
        "libreria", "casa del libro", "biblioteca", "coursera", "udemy",
    ],
}
