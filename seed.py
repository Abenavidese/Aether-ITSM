import os
import sys

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.db import models
from src.db.database import SessionLocal, engine
from src.services.auth import TenantSignup, create_tenant_and_user

# Create tables
models.Base.metadata.create_all(bind=engine)
db = SessionLocal()

try:
    user = TenantSignup(
        email="admin@manitas.com",
        password="Admin123!",
        full_name="Manitas Admin",
        company_name="Manitas",
    )
    created_user = create_tenant_and_user(db, user)
    print("Seed successful!")
    print(f"Company ID: {created_user.company_id}")
    print("User Email: admin@manitas.com")
    print("User Password: Admin123!")
except Exception as e:
    print(f"Seed failed (maybe already seeded?): {e}")
finally:
    db.close()
