import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user, get_session
from app.models import Category, Tag, User
from app.routers.auth import get_current_user
from app.schemas.taxonomy import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    TagCreate,
    TagOut,
)

router = APIRouter(tags=["taxonomy"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    payload: CategoryCreate,
    user: CurrentUser,
    session: DbSession,
) -> CategoryOut:
    await bind_current_user(session, user.id)
    category = Category(
        user_id=user.id,
        name=payload.name,
        kind=payload.kind,
        color=payload.color,
    )
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return CategoryOut.model_validate(category)


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    user: CurrentUser,
    session: DbSession,
) -> list[CategoryOut]:
    await bind_current_user(session, user.id)
    rows = await session.execute(
        select(Category).where(Category.user_id == user.id).order_by(Category.created_at)
    )
    return [CategoryOut.model_validate(c) for c in rows.scalars()]


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    user: CurrentUser,
    session: DbSession,
) -> CategoryOut:
    await bind_current_user(session, user.id)
    category = await session.get(Category, category_id)
    if category is None or category.user_id != user.id:
        raise HTTPException(status_code=404, detail="category not found")
    if payload.name is not None:
        category.name = payload.name
    if payload.kind is not None:
        category.kind = payload.kind
    if payload.color is not None:
        category.color = payload.color
    if payload.archived is not None:
        category.archived_at = datetime.now(UTC) if payload.archived else None
    await session.commit()
    await session.refresh(category)
    return CategoryOut.model_validate(category)


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> None:
    await bind_current_user(session, user.id)
    category = await session.get(Category, category_id)
    if category is None or category.user_id != user.id:
        raise HTTPException(status_code=404, detail="category not found")
    await session.delete(category)
    await session.commit()


@router.post("/tags", response_model=TagOut, status_code=201)
async def create_tag(
    payload: TagCreate,
    user: CurrentUser,
    session: DbSession,
) -> TagOut:
    await bind_current_user(session, user.id)
    tag = Tag(user_id=user.id, name=payload.name)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return TagOut.model_validate(tag)


@router.get("/tags", response_model=list[TagOut])
async def list_tags(
    user: CurrentUser,
    session: DbSession,
) -> list[TagOut]:
    await bind_current_user(session, user.id)
    rows = await session.execute(select(Tag).where(Tag.user_id == user.id).order_by(Tag.created_at))
    return [TagOut.model_validate(t) for t in rows.scalars()]


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> None:
    await bind_current_user(session, user.id)
    tag = await session.get(Tag, tag_id)
    if tag is None or tag.user_id != user.id:
        raise HTTPException(status_code=404, detail="tag not found")
    await session.delete(tag)
    await session.commit()
