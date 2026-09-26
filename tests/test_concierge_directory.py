"""
Unit tests for the Concierge's repo-directory grounding (_describe_directory).

Pure function over a fake GitHub tree shaped like the real test repo
(Abenavidese/core-ecommerce-api) — no network, no LLM. Each case is a real
message that previously produced a wrong or empty answer in the chat.
"""
from src.agent.concierge.repo_access import _format_file
from src.agent.concierge.repo_view import (
    _describe_directory, _extract_paths, _ungrounded_repo_names, _verified_listing_footer,
)

_DIRS = [
    "backend", "backend/src", "backend/src/controllers", "backend/src/middleware",
    "backend/src/repositories", "frontend", "frontend/src", "frontend/src/pages",
]
_FILES = [
    "README.md", "backend/src/server.js",
    "backend/src/controllers/authController.js", "backend/src/controllers/cartController.js",
    "backend/src/middleware/auth.js", "backend/src/repositories/userRepo.js",
    "frontend/src/App.jsx", "frontend/src/pages/Home.jsx",
]
TREE = [{"path": p, "type": "dir"} for p in _DIRS] + [{"path": p, "type": "file"} for p in _FILES]


def test_nonexistent_explicit_path_is_reported_as_missing_with_real_neighbors():
    # The original bug: "qué hay en /src/agents" never fetched the tree at all.
    context = _describe_directory(TREE, "revisa el repo y dime qyue hay en /src/agents").context
    assert "'src/agents' does NOT exist" in context
    assert "Real contents of 'backend/src/'" in context
    assert "controllers/" in context


def test_partial_path_resolves_to_full_path():
    context = _describe_directory(TREE, "que hay en src/controllers?").context
    assert "Real contents of 'backend/src/controllers/'" in context
    assert "authController.js" in context


def test_short_word_does_not_claim_a_longer_folder():
    # "repo" used to substring-match "repositories/" and list the wrong folder.
    context = _describe_directory(TREE, "revisa el repo y dime que hay").context
    assert "repositories" not in context
    assert "Real top-level contents" in context


def test_typo_tolerance_still_works():
    context = _describe_directory(TREE, "lista la carpeta ontrollers").context
    assert "Real contents of 'backend/src/controllers/'" in context


def test_misspelled_path_suggests_the_real_folder():
    context = _describe_directory(TREE, "muestrame src/controlers").context
    assert "does NOT exist" in context
    assert "Similar folder(s) in 'backend/src/': controllers" in context


def test_urls_are_not_treated_as_repo_paths():
    assert _extract_paths("mira https://github.com/foo/bar por favor") == []


def test_windows_backslash_path_is_recognized():
    # "\src\agent revisa esto" wasn't parsed as a path, the model only got
    # the top-level layout and invented a folder + files.
    assert _extract_paths(r"\src\agent revisa esto") == ["src/agent"]
    assert "'src/agent' does NOT exist" in _describe_directory(TREE, r"\src\agent revisa esto").context


def test_invented_files_are_flagged_but_real_and_user_mentioned_ones_are_not():
    reply = (
        "No hay un directorio /src/agent. Sin embargo, hay un directorio /src/agents en el backend "
        "con agent.service.js y agent.route.js. En backend/src/controllers está authController.js."
    )
    user_text = r"\src\agent revisa esto"
    ungrounded = _ungrounded_repo_names(reply, TREE, user_text)
    assert ungrounded == {"agent.service.js", "agent.route.js", "src/agents"}
    assert "src/agent" not in ungrounded          # the user asked about it
    assert "authController.js" not in ungrounded  # really exists
    assert "backend/src/controllers" not in ungrounded


def test_file_named_in_message_is_selected_for_reading():
    view = _describe_directory(TREE, "revisa authController.js, creo que el login falla")
    assert view.files == ["backend/src/controllers/authController.js"]


def test_explicit_file_path_is_selected_for_reading():
    view = _describe_directory(TREE, "que hace src/middleware/auth.js?")
    assert view.files == ["backend/src/middleware/auth.js"]


def test_listing_view_reports_which_dirs_were_shown():
    assert _describe_directory(TREE, "que hay en src/controllers").listed_dirs == ["backend/src/controllers"]
    missing = _describe_directory(TREE, "que hay en src/agents")
    assert missing.listed_dirs == ["backend/src", "frontend/src"]


def test_footer_adds_the_real_listing_only_when_the_reply_omits_it():
    dirs = ["backend/src/controllers"]
    terse = _verified_listing_footer(TREE, dirs, "El directorio /src/agent no existe.")
    assert "authController.js" in terse and "cartController.js" in terse
    complete = "Contiene authController.js y cartController.js."
    assert _verified_listing_footer(TREE, dirs, complete) == ""


def test_file_content_is_numbered_and_truncation_is_explicit():
    content = "\n".join(f"line {i}" for i in range(1, 101))
    formatted = _format_file("a.js", content, budget=200)
    assert formatted.splitlines()[1] == "   1 | line 1"
    assert "PARTIAL: only lines 1-" in formatted and "of 100" in formatted
    assert "(COMPLETE FILE, 1 lines)" in _format_file("a.js", "x = 1", budget=200)


def test_missing_path_view_is_marked_as_fallback():
    # Its parent dirs are shown as alternatives but must not be read as if
    # the user had asked to review them.
    assert _describe_directory(TREE, r"\src\agent revisa esto").fallback is True
    assert _describe_directory(TREE, "revisa src/controllers").fallback is False


def test_list_items_from_details_are_rendered_in_the_reply():
    from src.agent.concierge.reply import _compose_reply
    from src.agent.state import ConciergeResult
    result = ConciergeResult(response_text="Esto hace cada archivo:", resolved=True,
                             details=["auth.js: valida el JWT", "- wrap.js: captura errores async"])
    assert _compose_reply(result) == (
        "Esto hace cada archivo:\n\n- auth.js: valida el JWT\n- wrap.js: captura errores async"
    )


def test_schema_junk_items_are_dropped_from_the_reply():
    from src.agent.concierge.reply import _compose_reply
    from src.agent.state import ConciergeResult
    result = ConciergeResult(response_text="Intro", resolved=True,
                             details=["real finding: cartController.js:5", "tool_used_check_service_status:false,"])
    assert _compose_reply(result) == "Intro\n\n- real finding: cartController.js:5"
