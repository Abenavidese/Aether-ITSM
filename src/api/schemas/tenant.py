"""Request bodies of the tenant settings endpoints, with every shape rule enforced at the edge."""
import re
from typing import Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, field_validator, model_validator

# Only "owner/repo" — this value is interpolated straight into a GitHub API URL,
# so it must never contain path separators, "..", or scheme/host characters.
GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


LOG_SERVICE_ID_PATTERNS = {
    "render": re.compile(r"srv-[a-z0-9]{10,40}"),
    # The dashboard shows "prj_..." but drain payloads carry the bare id
    # (Vercel's own drain example: "gdufoJxB6b9b1fEqr1jUtFkyavUU"); accept
    # both — src/integrations/platform_logs/vercel.py compares them normalized.
    "vercel": re.compile(r"(prj_)?[A-Za-z0-9]{10,40}"),
}
RENDER_OWNER_ID_PATTERN = re.compile(r"(tea|usr)-[a-z0-9]{10,40}")


def _validate_github_repo(v: Optional[str]) -> Optional[str]:
    if v and not GITHUB_REPO_PATTERN.match(v):
        raise ValueError("github_repo must be in the form 'owner/repo'")
    return v


class OnboardingPayload(BaseModel):
    github_token: str
    github_repo: str

    _validate_repo = field_validator("github_repo")(_validate_github_repo)


class MonitoredService(BaseModel):
    name: str
    url: str
    # Fase 10: optional link to the hosting platform's logs. These ids are
    # interpolated into platform API paths by the read-only client, so they
    # are validated to their exact documented shape here — never anything
    # that could smuggle "/", "..", "?" or "&" into a request.
    provider: Optional[Literal["render", "vercel"]] = None
    service_id: Optional[str] = None
    owner_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _bounded_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 80:
            raise ValueError("service name must be 1-80 characters")
        return v

    @field_validator("url")
    @classmethod
    def _http_url_without_credentials(cls, v: str) -> str:
        # The healthcheck URL is requested by OUR server (Fase 11.4). Shape
        # is checked here; the address itself (public only, no redirects)
        # is checked at request time by src/security/url_guard.py, since DNS
        # can change after the config is saved.
        parts = urlsplit(v.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("service url must be an http(s) URL")
        if parts.username or parts.password:
            raise ValueError("service url must not contain credentials")
        if len(v) > 500:
            raise ValueError("service url is too long")
        return v.strip()

    @model_validator(mode="after")
    def _validate_log_source(self):
        if self.provider is None:
            if self.service_id or self.owner_id:
                raise ValueError("service_id/owner_id require a provider")
            return self
        pattern = LOG_SERVICE_ID_PATTERNS[self.provider]
        if not self.service_id or not pattern.fullmatch(self.service_id):
            raise ValueError(f"service_id for {self.provider} must match {pattern.pattern}")
        if self.provider == "render":
            if not self.owner_id or not RENDER_OWNER_ID_PATTERN.fullmatch(self.owner_id):
                raise ValueError(f"owner_id for render must match {RENDER_OWNER_ID_PATTERN.pattern}")
        elif self.owner_id:
            raise ValueError(f"owner_id is not used by {self.provider}")
        return self


class UpdateSettingsPayload(BaseModel):
    github_token: Optional[str] = None
    github_repo: Optional[str] = None
    user_full_name: Optional[str] = None
    company_name: Optional[str] = None
    monitored_services: Optional[list[MonitoredService]] = None
    # Write-only secrets: GET /settings returns "MASKED" for them, and
    # sending "MASKED" back (the frontend's untouched field) keeps the stored
    # value. An empty string clears it.
    render_api_key: Optional[str] = None
    vercel_drain_secret: Optional[str] = None

    _validate_repo = field_validator("github_repo")(_validate_github_repo)

    @field_validator("monitored_services")
    @classmethod
    def _unique_service_names(cls, v):
        # The agent resolves "which service?" by name, so names must be unique.
        if v is not None:
            names = [s.name.strip().lower() for s in v]
            if len(names) != len(set(names)):
                raise ValueError("monitored service names must be unique")
        return v

    def changes(self) -> dict:
        """Only the fields the caller sent (None = leave unchanged), as plain data for the service."""
        data = {k: getattr(self, k) for k in type(self).model_fields if getattr(self, k) is not None}
        if self.monitored_services is not None:
            data["monitored_services"] = [s.model_dump(exclude_none=True) for s in self.monitored_services]
        return data
