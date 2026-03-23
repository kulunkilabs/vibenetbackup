import os
import re
import time

import paramiko
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.credential import Credential
from app.models.group import Group

router = APIRouter(prefix="/credentials")


@router.get("/")
async def list_credentials(request: Request, db: Session = Depends(get_db)):
    credentials = db.query(Credential).order_by(Credential.name).all()
    return request.app.state.templates.TemplateResponse(
        request, "credentials/list.html", {"credentials": credentials},
    )


@router.get("/add")
async def add_credential_form(request: Request, db: Session = Depends(get_db)):
    return request.app.state.templates.TemplateResponse(
        request, "credentials/form.html",
        {"credential": None, "groups": db.query(Group).order_by(Group.name).all()},
    )


@router.post("/add")
async def add_credential(
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    password: str = Form(""),
    enable_secret: str = Form(""),
    ssh_key_path: str = Form(""),
    group: str = Form("default"),
    db: Session = Depends(get_db),
):
    cred = Credential(
        name=name,
        username=username,
        ssh_key_path=ssh_key_path or None,
        group=group or "default",
    )
    if password:
        cred.set_password(password)
    if enable_secret:
        cred.set_enable_secret(enable_secret)
    db.add(cred)
    db.commit()
    return RedirectResponse(url="/credentials", status_code=303)


@router.get("/{cred_id}/edit")
async def edit_credential_form(cred_id: int, request: Request, db: Session = Depends(get_db)):
    cred = db.query(Credential).get(cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    return request.app.state.templates.TemplateResponse(
        request, "credentials/form.html",
        {"credential": cred, "groups": db.query(Group).order_by(Group.name).all()},
    )


@router.post("/{cred_id}/edit")
async def edit_credential(
    cred_id: int,
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    password: str = Form(""),
    enable_secret: str = Form(""),
    ssh_key_path: str = Form(""),
    group: str = Form("default"),
    db: Session = Depends(get_db),
):
    cred = db.query(Credential).get(cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    cred.name = name
    cred.username = username
    cred.ssh_key_path = ssh_key_path or None
    cred.group = group or "default"
    if password:
        cred.set_password(password)
    if enable_secret:
        cred.set_enable_secret(enable_secret)
    db.commit()
    return RedirectResponse(url="/credentials", status_code=303)


@router.post("/generate-ssh-key")
async def generate_ssh_key(key_name: str = Form(...)):
    # Sanitize key_name: allow only alphanumeric, hyphens, underscores
    if not re.match(r'^[a-zA-Z0-9_-]+$', key_name):
        raise HTTPException(status_code=400, detail="Key name may only contain letters, numbers, hyphens, and underscores")

    settings = get_settings()
    ssh_key_dir = os.path.realpath(settings.SSH_KEY_DIR)
    os.makedirs(ssh_key_dir, mode=0o700, exist_ok=True)

    timestamp = int(time.time())
    filename = f"vibenet_{key_name}_{timestamp}"
    private_path = os.path.join(ssh_key_dir, filename)
    public_path = private_path + ".pub"

    # Path traversal protection
    if not os.path.realpath(private_path).startswith(ssh_key_dir):
        raise HTTPException(status_code=400, detail="Invalid key name")

    # Generate RSA 4096-bit key pair
    key = paramiko.RSAKey.generate(4096)

    # Save private key
    key.write_private_key_file(private_path)
    os.chmod(private_path, 0o600)

    # Build and save public key
    public_key = f"{key.get_name()} {key.get_base64()} vibenet-{key_name}"
    with open(public_path, "w") as f:
        f.write(public_key + "\n")
    os.chmod(public_path, 0o644)

    return JSONResponse({
        "ssh_key_path": os.path.realpath(private_path),
        "public_key": public_key,
    })


@router.post("/{cred_id}/delete")
async def delete_credential(cred_id: int, db: Session = Depends(get_db)):
    cred = db.query(Credential).get(cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    db.delete(cred)
    db.commit()
    return RedirectResponse(url="/credentials", status_code=303)
