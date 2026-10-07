"""
Pure (no I/O) interpretation of a chat message against the real repo tree:
which folder/file/path the user means, the grounded listing the model gets,
and the check that a reply only names things that really exist.
"""
import difflib
import re
from dataclasses import dataclass, field

_CODE_QUESTION_PATTERN = re.compile(
    r"\b(code|repo(sitory)?|function|c[oó]digo|repositorio|funci[oó]n|commit|pull request|\bpr\b|bug in|error de compilaci[oó]n)\b",
    re.IGNORECASE,
)

# Distinct from _CODE_QUESTION_PATTERN: "search code content" vs "enumerate a
# folder" are different GitHub API calls (search_code vs get_repo_tree) and
# need different trigger words — "list the files in X" rarely says "code".
_DIRECTORY_QUESTION_PATTERN = re.compile(
    r"\b(list(a(me)?)?|archivos|files|folder|carpeta|directorio|directory|estructura|structure"
    r"|contenido|contents|hay en|inside|dentro de)\b",
    re.IGNORECASE,
)

# An explicit path ("/src/agents", "backend/src/", "src/agent") is the most
# precise thing a user can give us — and one the keyword heuristic alone used
# to throw away ("src" is a stopword), so "qué hay en /src/agents" never even
# fetched the tree and the model answered with no data at all.
_PATH_PATTERN = re.compile(r"(?<![\w.:/])/?([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+|(?<=/)[A-Za-z0-9_.-]+)/?")

_STOPWORDS = {
    "el", "la", "los", "las", "en", "de", "que", "hay", "todos", "todas", "un", "una",
    "list", "lista", "listame", "archivos", "files", "todo", "the", "and", "for",
    "project", "proyecto", "backend", "frontend", "source", "src", "carpeta",
    "folder", "directorio", "directory", "estructura", "structure", "hola", "por",
    # Chat filler that used to leak into folder matching — "repo" substring-
    # matched "repositories/" and the Concierge confidently listed the wrong
    # folder.
    "repo", "repositorio", "repository", "revisa", "dime", "muestra", "muestrame",
    "show", "what", "whats", "inside", "dentro", "contenido", "contents", "code", "codigo",
}


def _extract_keywords(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _extract_paths(text: str) -> list[str]:
    # Windows-style "\src\agent" is the same request as "/src/agent" — a user
    # copying a path from their own machine types backslashes.
    text = text.replace("\\", "/")
    # rstrip("."): a path ending a sentence ("no existe /src/agent.") must not
    # carry the period.
    paths = (m.rstrip(".").strip("/") for m in _PATH_PATTERN.findall(text))
    return [p for p in paths if p]


# File names the model might state as facts ("agent.service.js"). Limited to
# code/config extensions so prose like "S.A.S." or "e.g." isn't checked.
_FILENAME_PATTERN = re.compile(
    r"\b[\w-]+(?:\.[\w-]+)*\.(?:js|jsx|ts|tsx|py|java|go|rb|php|cs|json|ya?ml|md|txt|sql|sh|css|html|toml|ini|env)\b",
    re.IGNORECASE,
)


def _ungrounded_repo_names(response: str, tree: list[dict], grounding_text: str) -> set[str]:
    """
    File names / paths the response states that exist neither in the real
    repo tree nor in the text the model was given (context + the user's own
    messages — so "there is no /src/agent" when the user asked about it is
    fine). The prompt already forbids inventing these, but a local 8B model
    still did ("backend/src/agents contains agent.service.js ..." for a folder
    that doesn't exist), so this is enforced in code, not left to the prompt.
    """
    known = {e["path"].lower() for e in tree} | {e["path"].rsplit("/", 1)[-1].lower() for e in tree}
    grounding = grounding_text.lower().replace("\\", "/")

    def grounded(name: str) -> bool:
        name = name.lower().strip("/")
        return (
            name in known
            or any(k.endswith("/" + name) for k in known)
            or name in grounding
        )

    candidates = set(_FILENAME_PATTERN.findall(response)) | set(_extract_paths(response))
    return {c for c in candidates if not grounded(c)}


def _children(tree: list[dict], dir_path: str) -> list[str]:
    return sorted(
        e["path"].rsplit("/", 1)[-1] + ("/" if e["type"] == "dir" else "")
        for e in tree
        if "/" in e["path"] and e["path"].rsplit("/", 1)[0] == dir_path
    )


def _format_listing(tree: list[dict], dir_path: str) -> str:
    children = _children(tree, dir_path)
    body = "\n".join(f"- {c}" for c in children) if children else "(empty)"
    return f"Real contents of '{dir_path}/' (from GitHub, just fetched):\n{body}"


def _top_level_listing(tree: list[dict]) -> str:
    top_level = sorted({e["path"].split("/")[0] for e in tree})
    return "Real top-level contents of the repo:\n" + "\n".join(f"- {t}" for t in top_level)


def _resolve_path(dirs: set[str], path: str) -> list[str]:
    """Dirs equal to `path` or ending in '/<path>' — users rarely type the
    full path from the repo root ("src/agents" for "backend/src/agents")."""
    target = path.lower()
    return sorted((d for d in dirs if d.lower() == target or d.lower().endswith("/" + target)), key=len)


@dataclass
class RepoView:
    """What the user's message resolved to in the real repo tree."""
    context: str = ""                                    # grounded text for the prompt
    listed_dirs: list[str] = field(default_factory=list)  # dirs whose contents were shown ("" = repo root)
    files: list[str] = field(default_factory=list)        # file paths worth reading
    # listed_dirs are only nearby alternatives (the requested path doesn't
    # exist) — show them, but never read their files as if they were asked for.
    fallback: bool = False


def _resolve_files(tree: list[dict], name: str) -> list[str]:
    target = name.lower().strip("/")
    return sorted(
        (e["path"] for e in tree if e["type"] == "file"
         and (e["path"].lower() == target or e["path"].lower().endswith("/" + target))),
        key=len,
    )


def _describe_explicit_path(tree: list[dict], dirs: set[str], path: str) -> RepoView:
    matches = _resolve_path(dirs, path)
    if matches:
        shown = matches[:3]
        return RepoView("\n\n".join(_format_listing(tree, d) for d in shown), listed_dirs=shown)

    files = _resolve_files(tree, path)
    if files:
        return RepoView(f"'{path}' is a FILE in the repository: {files[0]}", files=files[:1])

    # Deterministic negative answer plus the nearest real neighborhood, so the
    # model can say "doesn't exist, but here's what IS there" instead of
    # guessing or giving a bare "not found".
    view = RepoView(fallback=True)
    lines = [f"The path '{path}' does NOT exist in the repository (checked against the real GitHub tree)."]
    segments = path.split("/")
    for depth in range(len(segments) - 1, 0, -1):
        parents = _resolve_path(dirs, "/".join(segments[:depth]))
        if not parents:
            continue
        wanted = segments[depth].lower()
        for parent in parents[:3]:
            subdirs = [c.rstrip("/").lower() for c in _children(tree, parent) if c.endswith("/")]
            close = difflib.get_close_matches(wanted, subdirs, n=3, cutoff=0.75)
            if close:
                lines.append(f"Similar folder(s) in '{parent}/': " + ", ".join(close))
            lines.append(_format_listing(tree, parent))
            view.listed_dirs.append(parent)
        break
    else:
        lines.append(_top_level_listing(tree))
        view.listed_dirs.append("")
    view.context = "\n\n".join(lines)
    return view


def _match_dir_by_keyword(dirs: set[str], keywords: set[str]) -> str | None:
    dir_basenames = {d.rsplit("/", 1)[-1].lower(): d for d in dirs}

    matched_dir = next((dir_basenames[k] for k in keywords if k in dir_basenames), None)
    if matched_dir:
        return matched_dir

    # Typo tolerance ("ontrollers", "controlers") — a real user typing from
    # memory into a chat box will misspell a folder name, and falling back to
    # "nothing matched" every time that happens is unhelpful even though it's
    # honest. difflib needs no extra dependency and is good enough for short
    # identifier-like names.
    best_score, best_dir = 0.0, None
    for keyword in keywords:
        for basename, full_path in dir_basenames.items():
            shorter, longer = sorted((len(keyword), len(basename)))
            if (keyword in basename or basename in keyword) and shorter >= 0.8 * longer:
                # A near-complete substring hit (e.g. "ontrollers" missing the
                # leading 'c' of "controllers") is a stronger, more specific
                # signal than two same-length words that merely look alike
                # (e.g. "backjend" vs "backend") — score it above any
                # plausible SequenceMatcher ratio between two genuinely
                # different short words. The length guard stops a short word
                # from claiming a long folder ("repo" -> "repositories").
                score = 0.97
            else:
                score = difflib.SequenceMatcher(None, keyword, basename).ratio()
            if score > best_score:
                best_score, best_dir = score, full_path
    return best_dir if best_score >= 0.75 else None


def _mentioned_files(tree: list[dict], query: str) -> list[str]:
    """Real files named in the message by file name ("authController.js")."""
    found: list[str] = []
    for name in _FILENAME_PATTERN.findall(query.replace("\\", "/")):
        for path in _resolve_files(tree, name)[:1]:
            if path not in found:
                found.append(path)
    return found


def _describe_directory(tree: list[dict], query: str) -> RepoView:
    """
    Pure function (no I/O): real repo tree + user message -> what the message
    refers to, plus the grounded context the LLM gets. Precedence: explicit
    path in the message > folder name by keyword/typo match > top-level
    layout. Every branch returns real data, never an empty context, so the
    model always has something true to answer with rather than a reason to
    guess. Files named in the message are always collected for reading.
    """
    dirs = {e["path"] for e in tree if e["type"] == "dir"}
    mentioned = _mentioned_files(tree, query)

    paths = [p for p in _extract_paths(query) if not _FILENAME_PATTERN.fullmatch(p.rsplit("/", 1)[-1])]
    if paths:
        views = [_describe_explicit_path(tree, dirs, p) for p in paths[:2]]
        return RepoView(
            context="\n\n".join(v.context for v in views),
            listed_dirs=[d for v in views for d in v.listed_dirs],
            fallback=all(v.fallback for v in views),
            files=list(dict.fromkeys([f for v in views for f in v.files] + mentioned)),
        )

    if mentioned:
        return RepoView("\n".join(f"'{f}' is a FILE in the repository." for f in mentioned), files=mentioned)

    matched_dir = _match_dir_by_keyword(dirs, _extract_keywords(query))
    if matched_dir:
        return RepoView(_format_listing(tree, matched_dir), listed_dirs=[matched_dir])

    return RepoView("Couldn't match a specific folder name from the message. " + _top_level_listing(tree),
                    listed_dirs=[""])


# "Look inside" intent: reading a folder's files only makes sense when the
# user wants their contents reviewed/explained, not for a plain "list files".
_REVIEW_PATTERN = re.compile(
    r"\b(revisa(r|me)?|review|analiza(r)?|errore?s?|bugs?|falla(s|ndo)?|fallo|explica(me)?|explain"
    r"|qu[eé] hace|what does|lee(r)?|read|c[oó]digo de|code (of|in))\b",
    re.IGNORECASE,
)


def _verified_listing_footer(tree: list[dict], listed_dirs: list[str], response: str) -> str:
    """
    The real listing, appended in code when the model's reply left out
    entries it was given — so "what's in X / what does exist" never depends
    on a small model copying a list correctly (it often answers just "X
    doesn't exist" and drops the useful part).
    """
    blocks = []
    for d in listed_dirs:
        entries = _children(tree, d) if d else sorted(
            e["path"] + ("/" if e["type"] == "dir" else "") for e in tree if "/" not in e["path"]
        )
        if not entries or all(e.rstrip("/").lower() in response.lower() for e in entries):
            continue
        title = f"`{d}/`" if d else "la raíz del repositorio"
        blocks.append(f"📂 Contenido real (GitHub) de {title}:\n" + "\n".join(f"- {e}" for e in entries))
    return "\n\n".join(blocks)
