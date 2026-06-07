from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.item import Item

router = APIRouter()


class CreateItemRequest(BaseModel):
    name: str
    description: str | None = None
    price: float
    tax: float | None = None


@router.get("/items/{item_id}", response_model=Item)
async def read_item(item_id: int):
    if item_id <= 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return Item(id=item_id, name="Sample Item", description="A sample item", price=9.99, tax=0.5)


@router.post("/items", response_model=Item, status_code=201)
async def create_item(item: CreateItemRequest):
    return Item(id=1, **item.model_dump())
