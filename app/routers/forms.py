from fastapi import APIRouter, Depends, HTTPException, status
from security import get_current_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db

from ..models.user_model import Form, User
from ..schemas.form_schemas import FormCreate, FormUpdate


router = APIRouter(prefix="/forms", tags=["Forms"])


async def get_current_user_obj(
    email: str = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_form(
    form_data: FormCreate,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    new_form = Form(
        user_id=user.id,
        title=form_data.title,
        form_structure=form_data.form_structure,
        schedule_crons=form_data.schedule_crons,
    )
    db.add(new_form)
    await db.commit()
    await db.refresh(new_form)

    return {"form_id": new_form.id, "message": "Form created successfully"}


@router.get("")
async def get_all_forms(
    user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)
):
    query = select(Form).where(Form.user_id == user.id)
    result = await db.execute(query)
    forms = result.scalars().all()

    return [
        {
            "form_id": f.id,
            "title": f.title,
            "form_structure": f.form_structure,
            "schedule_crons": f.schedule_crons,
        }
        for f in forms
    ]


@router.get("/{id}")
async def get_form_by_id(
    id: int, user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)
):
    query = select(Form).where(Form.id == id, Form.user_id == user.id)
    result = await db.execute(query)
    form = result.scalar_one_or_none()

    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    return {
        "form_id": form.id,
        "title": form.title,
        "form_structure": form.form_structure,
        "schedule_crons": form.schedule_crons,
    }


@router.put("/{id}")
async def update_form(
    id: int,
    form_data: FormUpdate,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    query = select(Form).where(Form.id == id, Form.user_id == user.id)
    result = await db.execute(query)
    form = result.scalar_one_or_none()

    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    form.title = form_data.title
    form.form_structure = form_data.form_structure
    form.schedule_crons = form_data.schedule_crons

    await db.commit()
    return {"message": "Form updated successfully"}


@router.delete("/{id}")
async def delete_form(
    id: int, user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)
):
    query = select(Form).where(Form.id == id, Form.user_id == user.id)
    result = await db.execute(query)
    form = result.scalar_one_or_none()

    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    await db.delete(form)
    await db.commit()
    return {"message": "Form has been deleted"}
