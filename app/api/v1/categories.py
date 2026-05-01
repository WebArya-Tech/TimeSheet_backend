from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID

from app.api import deps
from app.models.category import Category
from app.models.user import User
from app.schemas.category import Category as CategorySchema, CategoryCreate, CategoryUpdate

router = APIRouter()

@router.get("/", response_model=List[CategorySchema])
async def read_categories(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    categories = await Category.find(Category.is_deleted == False).skip(skip).limit(limit).to_list(length=limit)
    return categories

@router.post("/", response_model=CategorySchema)
async def create_category(
    *,
    category_in: CategoryCreate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    category = await Category.find_one(Category.category_name == category_in.category_name)
    if category:
        raise HTTPException(status_code=400, detail="Category already exists.")
        
    db_category = Category(**category_in.model_dump())
    await db_category.insert()
    return db_category

@router.put("/{id}", response_model=CategorySchema)
async def update_category(
    *,
    id: UUID,
    category_in: CategoryUpdate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    category = await Category.find_one(Category.id == id, Category.is_deleted == False)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
        
    update_data = category_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(category, field, value)
        
    await category.save()
    return category

@router.delete("/{id}")
async def delete_category(
    *,
    id: UUID,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    category = await Category.find_one(Category.id == id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
        
    # Soft delete
    category.is_deleted = True
    await category.save()
    return {"msg": "Category deleted successfully"}
