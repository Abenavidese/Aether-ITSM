"""
In-app notifications for the person who reported a ticket (Fase 16).

Written in the same transaction as the ticket change that causes them, so a
notification exists if and only if the change was committed. Texts are for
non-technical readers and built by code from known fields; the only model
text that can appear is a resolution summary, redacted and cut. Links
(GitHub issue / pull request) are only attached for roles that can follow
them — an employee gets the news, not a link into the engineering repo.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from src.db.database import SessionLocal
from src.db.models import Notification, Ticket, User
from src.security.redaction import redact

logger = logging.getLogger(__name__)

LINK_ROLES = {"admin", "superadmin"}
_MAX_SUMMARY_CHARS = 300

TICKET_OPENED, RESOLVED, ESCALATED, PENDING_HUMAN = "ticket_opened", "resolved", "escalated", "pending_human"
ISSUE_OPENED, FIX_PROPOSED = "issue_opened", "fix_proposed"


def _incident_service(ticket: Ticket) -> str | None:
    try:
        services = json.loads(ticket.incident or "null") or {}
        return ", ".join(s["name"] for s in services.get("services", [])) or None
    except (ValueError, TypeError, KeyError):
        return None


def _summary(text: str | None) -> str:
    text = redact((text or "").strip())
    return text if len(text) <= _MAX_SUMMARY_CHARS else text[:_MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


def _message(kind: str, ticket: Ticket, detail: str | None) -> tuple[str, str]:
    ref = ticket.external_id
    if kind == TICKET_OPENED:
        return (f"Abrimos tu ticket {ref}",
                f"Recibimos tu reporte «{_summary(ticket.title)}». Te avisaremos aquí cuando avance.")
    if kind == PENDING_HUMAN:
        return (f"Tu solicitud {ref} espera aprobación",
                "Hay un plan listo, pero un administrador debe aprobarlo antes de ejecutarlo.")
    if kind == ESCALATED:
        service = _incident_service(ticket)
        if service:
            return (f"Ingeniería está revisando el fallo de {service}",
                    f"Confirmamos un problema en {service} (ticket {ref}). El equipo de ingeniería ya tiene el "
                    "diagnóstico y está trabajando en ello; no necesitas hacer nada más.")
        return (f"Tu ticket {ref} pasó al equipo técnico",
                "Lo revisará una persona del equipo técnico. Te avisaremos aquí cuando esté resuelto.")
    if kind == ISSUE_OPENED:
        return (f"Caso registrado para ingeniería ({ref})", "El ticket ya está registrado en el repositorio del equipo.")
    if kind == FIX_PROPOSED:
        return (f"Hay una corrección en revisión ({ref})",
                "Preparamos un cambio que corrige el fallo. Un ingeniero lo está revisando antes de publicarlo; "
                "te avisaremos cuando esté resuelto.")
    if kind == RESOLVED:
        body = _summary(detail) if detail else "El equipo técnico marcó tu ticket como resuelto."
        return f"Tu ticket {ref} está resuelto", body
    raise ValueError(f"unknown notification kind {kind!r}")


def notify(db, ticket: Ticket, kind: str, detail: str | None = None, link: str | None = None) -> None:
    """Adds the requester's notification to `db` (the caller commits)."""
    user = db.get(User, ticket.user_id)
    if user is None:
        return
    title, body = _message(kind, ticket, detail)
    db.add(Notification(tenant_id=ticket.tenant_id, user_id=user.id, ticket_id=ticket.id, kind=kind, title=title,
                        body=body, link=link if user.role in LINK_ROLES else None))


@dataclass(frozen=True)
class NotificationView:
    id: str
    kind: str
    title: str
    body: str
    link: str | None
    ticket_external_id: str | None
    read: bool
    created_at: str | None


def list_for_user(user_id: str, tenant_id: str, limit: int = 30) -> tuple[list[NotificationView], int]:
    db = SessionLocal()
    try:
        rows = (db.query(Notification, Ticket.external_id)
                .outerjoin(Ticket, Ticket.id == Notification.ticket_id)
                .filter(Notification.user_id == user_id, Notification.tenant_id == tenant_id)
                .order_by(Notification.created_at.desc()).limit(limit).all())
        unread = db.query(Notification).filter(Notification.user_id == user_id, Notification.tenant_id == tenant_id,
                                               Notification.read_at.is_(None)).count()
        views = [NotificationView(n.id, n.kind, n.title, n.body, n.link, external_id, n.read_at is not None,
                                  n.created_at.isoformat() if n.created_at else None) for n, external_id in rows]
        return views, unread
    finally:
        db.close()


def mark_read(user_id: str, tenant_id: str, notification_id: str | None = None) -> int:
    """Marks one (or, with no id, every) notification of THIS user as read. Returns how many changed."""
    db = SessionLocal()
    try:
        query = db.query(Notification).filter(Notification.user_id == user_id, Notification.tenant_id == tenant_id,
                                              Notification.read_at.is_(None))
        if notification_id:
            query = query.filter(Notification.id == notification_id)
        changed = query.update({Notification.read_at: datetime.now(timezone.utc)}, synchronize_session=False)
        db.commit()
        return changed
    finally:
        db.close()


@dataclass(frozen=True)
class MyTicket:
    external_id: str
    title: str
    status: str
    created_at: str | None
    resolved_at: str | None


def tickets_for_user(user_id: str, tenant_id: str, limit: int = 20) -> list[MyTicket]:
    db = SessionLocal()
    try:
        rows = (db.query(Ticket).filter(Ticket.user_id == user_id, Ticket.tenant_id == tenant_id)
                .order_by(Ticket.created_at.desc()).limit(limit).all())
        return [MyTicket(t.external_id, t.title, t.status, t.created_at.isoformat() if t.created_at else None,
                         t.resolved_at.isoformat() if t.resolved_at else None) for t in rows]
    finally:
        db.close()
