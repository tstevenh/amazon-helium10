import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import (
    LoginRequest,
    PasswordResetRequest,
    TokenResponse,
    UserCreateRequest,
    UserDetailResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    service = AuthService(db)
    token = service.login(payload.email, payload.password)
    return TokenResponse(**token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


# ── User management (admin only) ───────────────────────────────────────────
#
# Until this existed the only way to add a teammate was running the seed
# script or an INSERT, so in practice everyone shared one login and the audit
# trail recorded "admin" for every action by anyone.

@router.get("/users", response_model=list[UserDetailResponse])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[User]:
    return UserRepository(db).list_all()


@router.post("/users", response_model=UserDetailResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> User:
    repo = UserRepository(db)
    if repo.get_by_email(payload.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with the email {payload.email} already exists",
        )
    return repo.create(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )


@router.patch("/users/{user_id}", response_model=UserDetailResponse)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    repo = UserRepository(db)
    user = repo.get_by_id(str(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return user

    # Two ways an admin could lock the whole team out of the app, both of
    # which are easy to do by accident on a screen full of toggles.
    if user.id == current_user.id:
        if fields.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account",
            )
        if fields.get("role") == "user":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot remove your own admin role — ask another admin",
            )

    # Backstop only: the caller is necessarily an active admin, so demoting a
    # *different* admin always leaves at least the caller. This fires only if
    # the admin requirement above is ever loosened.
    losing_an_admin = user.role == "admin" and user.is_active and (
        fields.get("role") == "user" or fields.get("is_active") is False
    )
    if losing_an_admin and repo.count_active_admins() <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This is the only active admin. Promote someone else first.",
        )

    return repo.update(user, **fields)


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: uuid.UUID,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    """Admin sets a new password directly.

    There is no email delivery in this app, so a reset is handed over in
    person rather than mailed.
    """
    repo = UserRepository(db)
    user = repo.get_by_id(str(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    repo.update(user, password_hash=hash_password(payload.password))
