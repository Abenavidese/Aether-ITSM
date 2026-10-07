"""Reference data every deployment needs (run at API startup): subscription plans and the platform superadmin."""
import logging

from src.core.config import get_settings
from src.db import models
from src.db.database import SessionLocal
from src.security.hashing import get_password_hash

logger = logging.getLogger(__name__)

SUPERADMIN_EMAIL = "admin@aether.ai"


def seed_database() -> None:
    db = SessionLocal()
    try:
        plans = [
            models.SubscriptionPlan(id="plan_free", name="Free", price_usd=0.0, max_users=2, max_tickets_per_month=100, max_ai_resolutions_per_month=50),
            models.SubscriptionPlan(id="plan_pro", name="Pro", price_usd=49.0, max_users=10, max_tickets_per_month=500, max_ai_resolutions_per_month=250),
            models.SubscriptionPlan(id="plan_enterprise", name="Enterprise", price_usd=199.0, max_users=999, max_tickets_per_month=9999, max_ai_resolutions_per_month=9999)
        ]
        for p in plans:
            existing = db.query(models.SubscriptionPlan).filter(models.SubscriptionPlan.id == p.id).first()
            if not existing:
                db.add(p)

        sa = db.query(models.User).filter(models.User.email == SUPERADMIN_EMAIL).first()
        if not sa:
            logger.info("Seeding superadmin account...")
            company = models.Company(name="Aether Systems", industry="SaaS", onboarding_completed="true", plan_id="plan_enterprise")
            db.add(company)
            db.commit()
            db.refresh(company)

            db.add(models.User(
                email=SUPERADMIN_EMAIL,
                full_name="Platform Creator",
                password_hash=get_password_hash(get_settings().superadmin_password),
                role="superadmin",
                company_id=company.id
            ))

        db.commit()
    except Exception as e:
        logger.error(f"Error seeding database: {e}")
    finally:
        db.close()
