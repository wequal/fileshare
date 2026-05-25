from __future__ import annotations

import ipaddress
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.acl import PathAccessError, list_accessible_roots
from server.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    hash_password,
)
from server.config import get_settings
from server.database import db_cursor
from server.models import User
from server import multipart as mp
from server import storage

router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def health():
    return {"status": "ok"}


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool


class InitiateUploadRequest(BaseModel):
    path: str
    filename: str
    total_size: int = Field(ge=0)


class CompleteUploadRequest(BaseModel):
    final_parts: Optional[int] = Field(default=None, ge=1)


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    user = authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid username or password")
    token = create_access_token(user.id, user.username, user.is_admin)
    return TokenResponse(
        access_token=token,
        username=user.username,
        is_admin=user.is_admin,
    )


@router.post("/auth/register", response_model=TokenResponse)
async def register(body: RegisterRequest):
    settings = get_settings()
    if not settings.allow_public_registration:
        raise HTTPException(403, "Registration is disabled")

    with db_cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (body.username,)
        )
        if cur.fetchone():
            raise HTTPException(400, "Username already exists")
        cur.execute(
            """
            INSERT INTO users (username, password_hash, is_admin)
            VALUES (?, ?, 0)
            """,
            (body.username, hash_password(body.password)),
        )
        uid = cur.lastrowid

    token = create_access_token(uid, body.username, False)
    return TokenResponse(
        access_token=token,
        username=body.username,
        is_admin=False,
    )


@router.get("/auth/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "roots": list_accessible_roots(user),
    }


@router.get("/files")
async def list_files(path: str = "/", user: User = Depends(get_current_user)):
    try:
        return storage.list_directory(user, path)
    except PathAccessError as e:
        raise HTTPException(e.status_code, e.message) from e


@router.get("/files/download")
async def download_file(path: str, user: User = Depends(get_current_user)):
    try:
        resolved = storage.get_download_path(user, path)
    except PathAccessError as e:
        raise HTTPException(e.status_code, e.message) from e

    return FileResponse(
        path=resolved.physical_path,
        filename=resolved.physical_path.name,
        media_type="application/octet-stream",
    )


@router.post("/files/upload")
async def upload_simple(
    path: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    try:
        return await storage.save_upload(user, path, file)
    except PathAccessError as e:
        raise HTTPException(e.status_code, e.message) from e


@router.post("/files/mkdir")
async def create_dir(path: str, user: User = Depends(get_current_user)):
    try:
        return storage.mkdir(user, path)
    except PathAccessError as e:
        raise HTTPException(e.status_code, e.message) from e


@router.delete("/files")
async def delete_file(path: str, user: User = Depends(get_current_user)):
    try:
        storage.delete_path(user, path)
        return {"ok": True}
    except PathAccessError as e:
        raise HTTPException(e.status_code, e.message) from e


@router.post("/files/uploads")
async def initiate_multipart(
    body: InitiateUploadRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    try:
        mobile = mp._is_mobile_user_agent(request.headers.get("user-agent", ""))
        return mp.initiate_upload(
            user, body.path, body.filename, body.total_size, mobile=mobile
        )
    except PathAccessError as e:
        raise HTTPException(e.status_code, e.message) from e


@router.get("/files/uploads/{upload_id}")
async def upload_status(upload_id: str, user: User = Depends(get_current_user)):
    try:
        return mp.get_session_status(upload_id, user)
    except PathAccessError as e:
        raise HTTPException(e.status_code, e.message) from e


@router.put("/files/uploads/{upload_id}/parts/{part_number}")
async def upload_part(
    upload_id: str,
    part_number: int,
    request: Request,
    user: User = Depends(get_current_user),
):
    data = await request.body()
    try:
        return await mp.save_part(user, upload_id, part_number, data)
    except PathAccessError as e:
        raise HTTPException(e.status_code, e.message) from e


@router.post("/files/uploads/{upload_id}/complete")
async def complete_multipart(
    upload_id: str,
    body: CompleteUploadRequest = CompleteUploadRequest(),
    user: User = Depends(get_current_user),
):
    try:
        return await mp.complete_upload(user, upload_id, body.final_parts)
    except PathAccessError as e:
        raise HTTPException(e.status_code, e.message) from e
