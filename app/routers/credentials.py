from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.credential import Credential

router = APIRouter(prefix="/credentials")


@router.get("/")
async def list_credentials(request: Request, db: Session = Depends(get_db)):
    credentials = db.query(Credential).order_by(Credential.name).all()
    return request.app.state.templates.TemplateResponse(
        "credentials/list.html",
        {"request": request, "credentials": credentials},
    )


@router.get("/add")
async def add_credential_form(request: Request):
    return request.app.state.templates.TemplateResponse(
        "credentials/form.html",
        {"request": request, "credential": None},
    )


@router.post("/add")
async def add_credential(
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    password: str = Form(""),
    enable_secret: str = Form(""),
    ssh_key_path: str = Form(""),
    db: Session = Depends(get_db),
):
    cred = Credential(
        name=name,
        username=username,
        ssh_key_path=ssh_key_path or None,
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
        "credentials/form.html",
        {"request": request, "credential": cred},
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
    db: Session = Depends(get_db),
):
    cred = db.query(Credential).get(cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    cred.name = name
    cred.username = username
    cred.ssh_key_path = ssh_key_path or None
    if password:
        cred.set_password(password)
    if enable_secret:
        cred.set_enable_secret(enable_secret)
    db.commit()
    return RedirectResponse(url="/credentials", status_code=303)


@router.post("/{cred_id}/delete")
async def delete_credential(cred_id: int, db: Session = Depends(get_db)):
    cred = db.query(Credential).get(cred_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    db.delete(cred)
    db.commit()
    return RedirectResponse(url="/credentials", status_code=303)
