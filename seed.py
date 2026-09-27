import os
import sys

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.auth.schemas import UserCreate
from src.auth.service import create_tenant_and_user
from src.db import models
from src.db.database import SessionLocal, engine

# Create tables
models.Base.metadata.create_all(bind=engine)
db = SessionLocal()

try:
    user = UserCreate(
        email="admin@manitas.com",
        password="Admin123!",
        company_name="Manitas",
        role="superadmin"
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
