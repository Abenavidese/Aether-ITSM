"""
Text handling for keyword search (Fase 14.2). Pure functions, no I/O.

Why normalize in Python instead of Postgres' unaccent/stemming: one code
path for Postgres and the SQLite fallback, no extension to install, and
ES/EN mixed in one corpus — a language-specific stemmer would mangle the
other language. Accents and case are folded; suffix variation
("contraseña"/"contraseñas") is covered by prefix matching of longer terms.

Entities are the tokens a support question hinges on and an embedding
blurs: error codes (ERR_VPN_809, PAY-4012, E-12), env vars
(VITE_API_URL), package ids (pkg_docker), IPs and file paths. A passage
containing one exactly is a strong, precise signal.
"""
import re
import unicodedata

_STOPWORDS = frozenset("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada como con contra cual cuales cuando
cuanto cuanta cuantos cuantas de del desde donde dos el ella ellas ello ellos en entre era eres es esa esas ese
eso esos esta estan estar estas este esto estos fue fueron ha hace hacer hay he la las le les lo los mas me mi
mis mucho muy nada ni no nos nuestra nuestro o os otra otro para pero poco por porque pue puede pueden puedo que
quien se sea ser si sin sobre son su sus tambien tan te tengo tiene tienen todo todos tu tus un una unas uno
unos usted ya yo debo debe tengo necesito quiero hago dice sale aparece esta estoy
the a an and are as at be been but by can could did do does for from had has have how i if in into is it its me
my no not of on or our should so than that the their them then there these they this to was we were what when
where which who why will with would you your am any please need want get got
""".split())

_TERM = re.compile(r"[a-z0-9]+")
_ENTITY_PATTERNS = [
    re.compile(r"\b[A-Za-z]{1,10}(?:[_-][A-Za-z0-9]+)*[_-]\d{1,6}\b"),       # ERR_VPN_809, PAY-4012, E-12, KUBE-7731
    re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"),                         # VITE_API_URL, PAYGATE_API_SECRET
    re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b"),                             # pkg_docker, pg_stat_activity
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),                               # 10.20.3.15
    re.compile(r"\b[\w.-]+/[\w./-]+\.\w{1,5}\b"),                             # src/auth/controller.js
]
# Prefix matching only for terms long enough that a prefix still means the
# same word ("contrasena" -> "contrasenas"), never for short ones ("pay").
PREFIX_MIN_LEN = 6


def fold(text: str) -> str:
    """Lowercase, accents removed ("Contraseña" -> "contrasena")."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def search_text(text: str) -> str:
    """What gets indexed for full-text search: folded, one space between terms."""
    return " ".join(_TERM.findall(fold(text)))


def query_terms(text: str, limit: int = 24) -> list[str]:
    """Distinct content terms of a query, in order — stopwords and 1-char tokens dropped."""
    seen: dict[str, None] = {}
    for term in _TERM.findall(fold(text)):
        if len(term) > 1 and term not in _STOPWORDS:
            seen.setdefault(term, None)
    return list(seen)[:limit]


def to_tsquery(terms: list[str]) -> str:
    """
    OR-query for Postgres' to_tsquery('simple', ...). Terms come from
    query_terms() — [a-z0-9]+ only — so no user text can inject tsquery
    syntax.
    """
    return " | ".join(f"{t}:*" if len(t) >= PREFIX_MIN_LEN else t for t in terms if _TERM.fullmatch(t))


def extract_entities(text: str) -> list[str]:
    """Exact identifiers in `text`, folded, longest first (so "err_vpn_809" wins over "vpn_809")."""
    found: dict[str, None] = {}
    for pattern in _ENTITY_PATTERNS:
        for match in pattern.findall(text or ""):
            value = fold(match).strip(".-_")
            if len(value) >= 3 and (any(c.isdigit() for c in value) or "_" in value or "/" in value):
                found.setdefault(value, None)
    return sorted(found, key=len, reverse=True)


def entity_in(entity: str, folded_text: str) -> bool:
    """Whole-token containment, so "e-12" doesn't match inside "e-125"."""
    return re.search(rf"(?<![\w-]){re.escape(entity)}(?![\w-])", folded_text) is not None
