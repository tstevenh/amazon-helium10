"""
Idempotent seed script for Sprint 1A's initial Admin + User accounts.

There is no user-management UI in Sprint 1A. Running this script is how the first two
accounts get created. Safe to run repeatedly — any email that already exists is skipped.

Run manually (inside the api container or locally with DATABASE_URL pointed at the right DB):
    python -m app.modules.auth.seed
"""
import os

from sqlalchemy.exc import IntegrityError

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
            try:
                repo.create(
                    email=entry["email"],
                    name=entry["name"],
                    password_hash=hash_password(entry["password"]),
                    role=entry["role"],
                )
            except IntegrityError:
                # The check above is not enough on its own. The api container
                # seeds on startup, and a deploy script that also seeds can be
                # running at the same moment — both see "absent", both insert,
                # one loses on uq_users_email. The account exists either way,
                # so this is a no-op, not a failure. Without this the deploy
                # printed an alarming traceback for a healthy outcome.
                db.rollback()
                print(f"[seed] skip — created concurrently: {entry['email']}")
                continue
            print(f"[seed] created: {entry['email']} ({entry['role']})")
    finally:
        db.close()


if __name__ == "__main__":
    seed_users()
