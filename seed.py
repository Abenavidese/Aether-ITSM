import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.db.database import SessionLocal, engine
from src.db import models
from src.auth.schemas import UserCreate
from src.auth.service import create_tenant_and_user

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
    print(f"Seed successful!")
    print(f"Company ID: {created_user.company_id}")
    print(f"User Email: admin@manitas.com")
    print(f"User Password: Admin123!")
except Exception as e:
    print(f"Seed failed (maybe already seeded?): {e}")
finally:
    db.close()
