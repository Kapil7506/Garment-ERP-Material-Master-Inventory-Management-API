from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Numeric, Enum, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class MaterialType(str, PyEnum):
    FABRIC = "Fabric"
    TRIM = "Trim"
    PACKAGING = "Packaging"

class UnitOfMeasurement(str, PyEnum):
    METER = "Meter"
    KG = "kg"
    PIECES = "Pieces"

class MaterialStatus(str, PyEnum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"

class TransactionType(str, PyEnum):
    OPENING_STOCK = "Opening Stock"
    MATERIAL_INWARD = "Material Inward"
    MATERIAL_ISSUE = "Material Issue"

class MaterialMaster(Base):
    __tablename__ = "material_master"

    id = Column(Integer, primary_key=True, index=True)
    material_code = Column(String(50), unique=True, nullable=False, index=True)
    material_name = Column(String(100), nullable=False, index=True)
    material_type = Column(Enum(MaterialType), nullable=False)
    uom = Column(Enum(UnitOfMeasurement), nullable=False)
    unit_rate = Column(Numeric(10, 2), nullable=False, default=0.00)
    minimum_stock_level = Column(Numeric(10, 2), nullable=False, default=0.00)
    status = Column(Enum(MaterialStatus), nullable=False, default=MaterialStatus.ACTIVE)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    inventory = relationship("InventoryStock", back_populates="material", uselist=False, cascade="all, delete-orphan")
    transactions = relationship("StockTransaction", back_populates="material", cascade="all, delete-orphan")


class InventoryStock(Base):
    __tablename__ = "inventory_stock"

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("material_master.id", ondelete="CASCADE"), unique=True, nullable=False)
    current_stock = Column(Numeric(10, 2), nullable=False, default=0.00)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    material = relationship("MaterialMaster", back_populates="inventory")


class StockTransaction(Base):
    __tablename__ = "stock_transactions"

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("material_master.id", ondelete="CASCADE"), nullable=False)
    transaction_type = Column(Enum(TransactionType), nullable=False)
    quantity = Column(Numeric(10, 2), nullable=False)
    previous_stock = Column(Numeric(10, 2), nullable=False)
    new_stock = Column(Numeric(10, 2), nullable=False)
    reference_note = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    material = relationship("MaterialMaster", back_populates="transactions")