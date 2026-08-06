"""Google sign-in — the only auth flow this app has."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from interview_bot.api import auth
from interview_bot.api import credits as credits_module
from interview_bot.api.schemas import GoogleLoginRequest, UserResponse
from interview_bot.integrations import google_auth
from interview_bot.persistence import users as user_store
from interview_bot.persistence.database import get_db
from interview_bot.persistence.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=UserResponse)
async def login_with_google(
    request: GoogleLoginRequest, response: Response, db: Session = Depends(get_db)
) -> UserResponse:
    try:
        identity = google_auth.verify(request.id_token)
    except google_auth.GoogleTokenError as e:
        raise HTTPException(status_code=401, detail="Invalid Google credential") from e

    user, is_new = user_store.get_or_create(
        db,
        google_sub=identity.sub,
        email=identity.email,
        name=identity.name,
        picture=identity.picture,
    )
    if is_new:
        credits_module.grant_signup_credits(user)
    db.commit()
    db.refresh(user)

    token = auth.create_user_session(db, user)
    auth.set_session_cookie(response, token)
    return _to_user_response(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    auth.delete_current_session(request, db)
    auth.clear_session_cookie(response)
    return Response(status_code=204)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(auth.get_current_user)) -> UserResponse:
    return _to_user_response(user)


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        picture_url=user.picture_url,
        credits=user.credits,
    )
