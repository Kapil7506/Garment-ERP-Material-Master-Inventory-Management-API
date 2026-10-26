from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from decimal import Decimal
from sqlalchemy import or_

# Local imports
from database import get_db, engine # Assuming database setup module
import models
import schemas

# Create tables
models.Base.metadata.create_all(bind=engine)

#Title
app = FastAPI(
    title="Garment ERP - Material Master API",
    description="APIs for managing garment production raw materials, trims, and packaging items."
)

# ---------------------------------------------------------
# MATERIAL MASTER ENDPOINTS
# ---------------------------------------------------------

@app.post("/materials/", response_model=schemas.MaterialResponse, status_code=status.HTTP_201_CREATED)
def create_material(material: schemas.MaterialCreate, db: Session = Depends(get_db)):
    """
    **Create a new material record.**
    - Validates that `material_code` and `material_name` are provided and mandatory.
    - Ensures `material_code` is unique.
    - Validates that `unit_rate` and `minimum_stock_level` are not negative.
    """
    existing = db.query(models.MaterialMaster).filter(
        models.MaterialMaster.material_code == material.material_code
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Material Code '{material.material_code}' already exists. It must be unique."
        )

    db_material = models.MaterialMaster(**material.model_dump())
    db.add(db_material)
    db.commit()
    db.refresh(db_material)
    return db_material


@app.get("/materials/", response_model=List[schemas.MaterialResponse])
def list_materials(
    search: Optional[str] = Query(None, description="Search materials by code or name"),
    material_type: Optional[models.MaterialType] = Query(None),
    db: Session = Depends(get_db)
):
    """
    **Retrieve and list all materials.**
    - Supports searching by code or name (`?search=...`).
    - Supports filtering by type.
    """
    query = db.query(models.MaterialMaster)

    if search:
        query = query.filter(
            or_(
                models.MaterialMaster.material_code.ilike(f"%{search}%"),
                models.MaterialMaster.material_name.ilike(f"%{search}%")
            )
        )
    if material_type:
        query = query.filter(models.MaterialMaster.material_type == material_type)

    return query.all()


@app.get("/materials/{material_id}", response_model=schemas.MaterialResponse)
def get_material_by_id(material_id: int, db: Session = Depends(get_db)):
    """**Retrieve specific material details by ID.**"""
    material = db.query(models.MaterialMaster).filter(models.MaterialMaster.id == material_id).first()
    if not material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material with ID {material_id} not found."
        )
    return material


@app.put("/materials/{material_id}", response_model=schemas.MaterialResponse)
def update_material(material_id: int, updated_data: schemas.MaterialUpdate, db: Session = Depends(get_db)):
    """**Update existing material details.** (Partial updates supported)."""
    db_material = db.query(models.MaterialMaster).filter(models.MaterialMaster.id == material_id).first()
    if not db_material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material with ID {material_id} not found."
        )

    update_dict = updated_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(db_material, key, value)

    db.commit()
    db.refresh(db_material)
    return db_material


@app.patch("/materials/{material_id}/status", response_model=schemas.MaterialResponse)
def activate_deactivate_material(
    material_id: int, 
    new_status: models.MaterialStatus = Query(..., alias="status", description="Active or Inactive"),
    db: Session = Depends(get_db)
):
    """**Activate or deactivate a material record.**"""
    db_material = db.query(models.MaterialMaster).filter(models.MaterialMaster.id == material_id).first()
    if not db_material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Material with ID {material_id} not found."
        )

    db_material.status = new_status
    db.commit()
    db.refresh(db_material)
    return db_material

# ---------------------------------------------------------
# INVENTORY MANAGEMENT ENDPOINTS
# ---------------------------------------------------------

@app.post("/transactions/", response_model=schemas.TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_stock_transaction(tx: schemas.TransactionCreate, db: Session = Depends(get_db)):
    """
    **Process material stock transactions according to strict business rules:**
    - **Rule 1 & 2:** Increases stock on Inward; decreases stock on Issue.
    - **Rule 3:** Rejects Material Issue exceeding available stock.
    - **Rule 4:** Rejects negative or zero transaction quantities (enforced via Pydantic `gt=0`).
    - **Rule 5:** Rejects transactions if the material status is Inactive.
    - **Rule 6 & 8:** Maintains full audit history (date, material, quantity, type) in an append-only ledger.
    - **Rule 7:** Ensures database atomicity with automatic rollback on validation or processing failure.
    """
    try:
        # 1. Verify material existence
        material = db.query(models.MaterialMaster).filter(models.MaterialMaster.id == tx.material_id).first()
        if not material:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Material with ID {tx.material_id} not found."
            )

        # 2. Rule 5: Transactions must not be allowed for inactive materials
        if material.status != models.MaterialStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Transaction rejected: Material '{material.material_code}' is currently Inactive."
            )

        # 3. Get or initialize inventory stock record
        inventory = db.query(models.InventoryStock).filter(models.InventoryStock.material_id == tx.material_id).first()
        if not inventory:
            inventory = models.InventoryStock(material_id=tx.material_id, current_stock=Decimal("0.00"))
            db.add(inventory)
            db.flush()

        previous_stock = inventory.current_stock
        new_stock = previous_stock

        # 4. Rule 1, 2 & 3: Calculate and validate stock changes
        if tx.transaction_type == models.TransactionType.OPENING_STOCK:
            new_stock = tx.quantity
        elif tx.transaction_type == models.TransactionType.MATERIAL_INWARD:
            new_stock = previous_stock + tx.quantity  # Rule 1: Increases available stock
        elif tx.transaction_type == models.TransactionType.MATERIAL_ISSUE:
            new_stock = previous_stock - tx.quantity  # Rule 2: Decreases available stock
            if new_stock < 0:
                # Rule 3: Material issue exceeding available stock must be rejected
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Transaction Rejected: Insufficient stock. Current available stock is {previous_stock}, "
                        f"attempting to issue {tx.quantity} would result in a negative balance ({new_stock})."
                    )
                )

        # 5. Update inventory stock balance
        inventory.current_stock = new_stock

        # 6. Rule 6 & 8: Record transaction in historical audit ledger (append-only)
        db_tx = models.StockTransaction(
            material_id=tx.material_id,
            transaction_type=tx.transaction_type,
            quantity=tx.quantity,
            previous_stock=previous_stock,
            new_stock=new_stock,
            reference_note=tx.reference_note
        )
        db.add(db_tx)
        db.commit()
        db.refresh(db_tx)

        return db_tx

    except HTTPException as he:
        # Rule 7: Rollback any partial database modifications on failure
        db.rollback()
        raise he
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during transaction processing: {str(e)}"
        )


@app.get("/transactions/", response_model=List[schemas.TransactionResponse])
def list_stock_transactions(
    material_id: Optional[int] = Query(None, description="Filter history by material ID"),
    db: Session = Depends(get_db)
):
    """**Retrieve preserved historical stock transactions (Rule 8).**"""
    query = db.query(models.StockTransaction)
    if material_id:
        query = query.filter(models.StockTransaction.material_id == material_id)
    return query.order_by(models.StockTransaction.created_at.desc()).all()


# ---------------------------------------------------------
# 3. ERP REPORTS & ANALYTICS
# ---------------------------------------------------------

def calculate_closing_stock(db: Session, material_id: int) -> Decimal:
    """Computes closing stock strictly from the audit transaction ledger."""
    transactions = db.query(models.StockTransaction).filter(
        models.StockTransaction.material_id == material_id
    ).order_by(models.StockTransaction.created_at.asc()).all()

    stock = Decimal("0.00")
    for tx in transactions:
        if tx.transaction_type == models.TransactionType.OPENING_STOCK:
            stock = tx.quantity
        elif tx.transaction_type == models.TransactionType.MATERIAL_INWARD:
            stock += tx.quantity
        elif tx.transaction_type == models.TransactionType.MATERIAL_ISSUE:
            stock -= tx.quantity
            
    return max(stock, Decimal("0.00"))

@app.get("/reports/current-stock")
def get_current_stock_report(
    material_type: Optional[models.MaterialType] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Current stock report calculated dynamically using inventory transactions."""
    query = db.query(models.MaterialMaster)
    if material_type:
        query = query.filter(models.MaterialMaster.material_type == material_type)
    if search:
        query = query.filter(
            or_(
                models.MaterialMaster.material_code.ilike(f"%{search}%"),
                models.MaterialMaster.material_name.ilike(f"%{search}%")
            )
        )

    materials = query.all()
    report = []

    for mat in materials:
        closing_stock = calculate_closing_stock(db, mat.id)
        report.append({
            "material_id": mat.id,
            "material_code": mat.material_code,
            "material_name": mat.material_name,
            "material_type": mat.material_type,
            "uom": mat.uom,
            "unit_rate": mat.unit_rate,
            "minimum_stock_level": mat.minimum_stock_level,
            "closing_stock": closing_stock,
            "total_inventory_value": closing_stock * mat.unit_rate,
            "status": mat.status
        })

    return report

@app.get("/reports/material-details/{material_id}")
def get_material_stock_details(material_id: int, db: Session = Depends(get_db)):
    """Material-wise stock details and full transaction ledger."""
    material = db.query(models.MaterialMaster).filter(models.MaterialMaster.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found.")

    closing_stock = calculate_closing_stock(db, material_id)
    transactions = db.query(models.StockTransaction).filter(
        models.StockTransaction.material_id == material_id
    ).order_by(models.StockTransaction.created_at.desc()).all()

    return {
        "material_id": material.id,
        "material_code": material.material_code,
        "material_name": material.material_name,
        "material_type": material.material_type,
        "uom": material.uom,
        "unit_rate": material.unit_rate,
        "minimum_stock_level": material.minimum_stock_level,
        "closing_stock": closing_stock,
        "is_below_minimum": closing_stock < material.minimum_stock_level,
        "transaction_history": transactions
    }


@app.get("/reports/low-stock")
def get_low_stock_report(db: Session = Depends(get_db)):
    """Low-stock report based on minimum stock levels."""
    materials = db.query(models.MaterialMaster).filter(models.MaterialStatus.ACTIVE == models.MaterialMaster.status).all()
    low_stock_items = []

    for mat in materials:
        closing_stock = calculate_closing_stock(db, mat.id)
        if closing_stock < mat.minimum_stock_level:
            low_stock_items.append({
                "material_id": mat.id,
                "material_code": mat.material_code,
                "material_name": mat.material_name,
                "material_type": mat.material_type,
                "uom": mat.uom,
                "closing_stock": closing_stock,
                "minimum_stock_level": mat.minimum_stock_level,
                "deficit": mat.minimum_stock_level - closing_stock
            })

    return low_stock_items


@app.get("/reports/transactions-history")
def get_material_transaction_history(
    material_id: Optional[int] = Query(None),
    material_type: Optional[models.MaterialType] = Query(None),
    transaction_type: Optional[models.TransactionType] = Query(None),
    db: Session = Depends(get_db)
):
    """Material transaction history with multi-level material-wise filtering."""
    query = db.query(models.StockTransaction).join(models.MaterialMaster)

    if material_id:
        query = query.filter(models.StockTransaction.material_id == material_id)
    if material_type:
        query = query.filter(models.MaterialMaster.material_type == material_type)
    if transaction_type:
        query = query.filter(models.StockTransaction.transaction_type == transaction_type)

    return query.order_by(models.StockTransaction.created_at.desc()).all()