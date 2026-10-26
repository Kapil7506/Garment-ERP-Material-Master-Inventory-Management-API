from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Any
from decimal import Decimal
from models import MaterialType, UnitOfMeasurement, MaterialStatus, TransactionType

# Base Schema with common attributes
class MaterialBase(BaseModel):
    material_code: str = Field(..., min_length=1, max_length=50, example="FAB-001")
    material_name: str = Field(..., min_length=1, max_length=100, example="Cotton Twill Fabric 200GSM")
    material_type: MaterialType
    uom: UnitOfMeasurement
    unit_rate: Decimal = Field(..., ge=0, decimal_places=2, example=4.50)
    minimum_stock_level: Decimal = Field(..., ge=0, decimal_places=2, example=100.00)
    status: MaterialStatus = Field(default=MaterialStatus.ACTIVE, example=MaterialStatus.ACTIVE)

# Schema for creating a material (Optional manual material_code)
class MaterialCreate(MaterialBase):
    pass

# Schema for updating a material (Partial updates allowed)
class MaterialUpdate(BaseModel):
    material_name: Optional[str] = Field(None, min_length=1, max_length=100)
    material_type: Optional[MaterialType] = None
    uom: Optional[UnitOfMeasurement] = None
    unit_rate: Optional[Decimal] = Field(None, ge=0)
    minimum_stock_level: Optional[Decimal] = Field(None, ge=0)
    status: Optional[MaterialStatus] = None

# Schema for Response/Output
class MaterialResponse(MaterialBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

class TransactionCreate(BaseModel):
    material_id: int = Field(..., description="ID of the material")
    transaction_type: TransactionType = Field(..., description="Opening Stock / Material Inward / Material Issue")
    quantity: Decimal = Field(..., gt=0, decimal_places=2, description="Rule 4: Quantity must be strictly positive (> 0)")
    reference_note: Optional[str] = Field(None, max_length=200, description="Optional document/slip reference")

class TransactionResponse(BaseModel):
    id: int
    material_id: int
    transaction_type: TransactionType
    quantity: Decimal
    previous_stock: Decimal
    new_stock: Decimal
    reference_note: Optional[str]
    created_at: Any

    model_config = ConfigDict(from_attributes=True)