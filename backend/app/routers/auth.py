"""Auth endpoints: login, register, and current-user profile."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.database import get_session
from app.models import TokenResponse, UserCreate, UserResponse
from app.table_models import User

router = APIRouter(prefix="/api")


@router.post("/auth/token", response_model=TokenResponse)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    """Exchange username + password for a signed JWT."""
    user = session.exec(select(User).where(User.username == form.username)).first()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({
        "sub": user.username,
        "user_id": user.id,
        "role": user.role,
        "property_code": user.property_code,
    })
    return TokenResponse(access_token=token, token_type="bearer")


@router.post("/auth/register", response_model=UserResponse, status_code=201)
def register(body: UserCreate, session: Session = Depends(get_session)):
    """Create a new user profile."""
    existing = session.exec(select(User).where(User.username == body.username)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")

    if not body.role and not body.property_code:
        raise HTTPException(
            status_code=422,
            detail="At least one of 'role' or 'property_code' must be provided",
        )

    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        name=body.name,
        role=body.role,
        property_code=body.property_code.upper() if body.property_code else None,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserResponse(
        id=user.id,
        username=user.username,
        name=user.name,
        role=user.role,
        property_code=user.property_code,
    )


@router.get("/users/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        name=current_user.name,
        role=current_user.role,
        property_code=current_user.property_code,
    )
