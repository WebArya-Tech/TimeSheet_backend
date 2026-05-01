from typing import Optional
from pydantic import BaseModel, UUID4

class CategoryBase(BaseModel):
    category_name: str
    allowed_on_weekend: bool = False
    allowed_on_holiday: bool = False

class CategoryCreate(CategoryBase):
    pass

class CategoryUpdate(BaseModel):
    category_name: Optional[str] = None
    allowed_on_weekend: Optional[bool] = None
    allowed_on_holiday: Optional[bool] = None

class CategoryInDBBase(CategoryBase):
    id: UUID4

    model_config = {"from_attributes": True}

class Category(CategoryInDBBase):
    pass
