"""
Idempotent seed script for Sprint 1A's initial Admin + User accounts.

There is no user-management UI in Sprint 1A. Running this script is how the first two
accounts get created. Safe to run repeatedly — any email that already exists is skipped.

Run manually (inside the api container or locally with DATABASE_URL pointed at the right DB):
    python -m app.modules.auth.seed
"""
import os

from app.core.security import hash_password
from app.database import SessionLocal
from app.modules.auth.repository import UserRepository

SEED_USERS = [
    {
        "email": os.getenv("SEED_ADMIN_EMAIL", "admin@example.com"),
        "name": "Admin User",
        "password": os.getenv("SEED_ADMIN_PASSWORD", "ChangeMe123!"),
        "role": "admin",
    },
    {
        "email": os.getenv("SEED_USER_EMAIL", "user@example.com"),
        "name": "Standard User",
        "password": os.getenv("SEED_USER_PASSWORD", "ChangeMe123!"),
        "role": "user",
    },
]


def seed_users() -> None:
    db = SessionLocal()
    repo = UserRepository(db)
    try:
        for entry in SEED_USERS:
            existing = repo.get_by_email(entry["email"])
            if existing is not None:
                print(f"[seed] skip — already exists: {entry['email']}")
                continue
            repo.create(
                email=entry["email"],
                name=entry["name"],
                password_hash=hash_password(entry["password"]),
                role=entry["role"],
            )
            print(f"[seed] created: {entry['email']} ({entry['role']})")
    finally:
        db.close()


if __name__ == "__main__":
    seed_users()
