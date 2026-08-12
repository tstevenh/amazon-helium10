from sqlalchemy.orm import Session

from app.modules.auth.models import User

# The database constrains role via ck_users_role. Anything outside this set
# raises CheckViolation on insert, so the API must reject it first.
ALLOWED_ROLES = ("admin", "user")


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        return self.db.query(User).filter(User.email == email).first()

    def get_by_id(self, user_id: str) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()

    def create(self, *, email: str, name: str, password_hash: str, role: str) -> User:
        user = User(email=email, name=name, password_hash=password_hash, role=role)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def list_all(self) -> list[User]:
        """Newest last, so the seeded admin stays at the top of the screen."""
        return self.db.query(User).order_by(User.created_at.asc()).all()

    def count_active_admins(self) -> int:
        """Used to refuse the change that would lock everyone out."""
        return (
            self.db.query(User)
            .filter(User.role == "admin", User.is_active.is_(True))
            .count()
        )

    def update(self, user: User, **fields) -> User:
        for key, value in fields.items():
            setattr(user, key, value)
        self.db.commit()
        self.db.refresh(user)
        return user
