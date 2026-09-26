"""
Repo files the agent must never read (Fase 11.9).

The Concierge reads real files from the tenant's GitHub repo and puts them
in an LLM prompt (and, through the reply, on an employee's screen). A
committed .env or private key would leak that way to anyone who can chat.
The check lives at the single choke point (integrations/github.py
get_file_content), so every current and future caller is covered.
"""
import fnmatch

# Matched case-insensitively against the file's basename.
_DENIED_BASENAMES = (
    ".env", ".env.*", "*.env",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    # Credential/secret DATA files — not code that merely handles secrets
    # (secretsController.js is exactly what a review should be able to read).
    "credentials", "*.credentials", "*credential*.json", "*credential*.y*ml", "*credential*.xml",
    "*secret*.json", "*secret*.y*ml", "*secret*.toml", "*secret*.txt",
    "service-account*.json", "*serviceaccount*.json",
    ".npmrc", ".pypirc", ".netrc", ".htpasswd", ".git-credentials", ".dockercfg",
    "terraform.tfstate*", "*.tfvars",
)
# Templates are meant to be committed and hold no real values.
_ALLOWED_TEMPLATES = (".env.example", ".env.sample", ".env.template", "*.example", "*.sample")


def is_sensitive_path(path: str) -> bool:
    basename = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
    if any(fnmatch.fnmatch(basename, p) for p in _ALLOWED_TEMPLATES):
        return False
    return any(fnmatch.fnmatch(basename, p) for p in _DENIED_BASENAMES)


class SensitiveFileError(PermissionError):
    """Refused to read a file that can hold credentials."""
