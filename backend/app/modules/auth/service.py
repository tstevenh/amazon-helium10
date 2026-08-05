from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)

    def authenticate(self, email: str, password: str) -> User:
        user = self.repo.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive",
            )
        return user

    def login(self, email: str, password: str) -> dict:
        user = self.authenticate(email, password)
        return create_access_token(user_id=str(user.id), role=user.role)
