from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.group import Group

router = APIRouter(prefix="/groups")


@router.get("/")
async def list_groups(request: Request, db: Session = Depends(get_db)):
    groups = db.query(Group).order_by(Group.name).all()
    return request.app.state.templates.TemplateResponse(
        "groups/list.html",
        {"request": request, "groups": groups},
    )


@router.post("/add")
async def add_group(
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not db.query(Group).filter(Group.name == name).first():
        db.add(Group(name=name, description=description or None))
        db.commit()
    return RedirectResponse(url="/groups", status_code=303)


@router.post("/{group_id}/delete")
async def delete_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).get(group_id)
    if group:
        db.delete(group)
        db.commit()
    return RedirectResponse(url="/groups", status_code=303)
