import concurrent.futures
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import get_db       
from models import Base
from main import app

# PostgreSQL Test Database URL (Override via environment variable if needed)
SQLALCHEMY_TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", 
    "postgresql://postgres:your_password@localhost:5432/garment_test_db"
)

engine = create_engine(SQLALCHEMY_TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Override the get_db dependency for tests
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


# Pytest fixture to reset tables before every single test
import pytest

@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    # Drop all tables and recreate them clean before each test
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

# ---------------------------------------------------------
# Mandatory Test Scenarios
# ---------------------------------------------------------

# --- 1. Duplicate Material Code Test ---
def test_create_material_duplicate_code():
    payload = {
        "material_code": "FAB-DUP-01",
        "material_name": "Denim Fabric 14OZ",
        "material_type": "Fabric",
        "uom": "Meter",
        "unit_rate": 5.50,
        "minimum_stock_level": 100.00,
        "status": "Active"
    }
    response_1 = client.post("/materials/", json=payload)
    assert response_1.status_code == 201

    response_2 = client.post("/materials/", json=payload)
    assert response_2.status_code == 400
    assert "already exists" in response_2.json()["detail"]


# --- 2. Missing Mandatory Fields Test ---
def test_create_material_missing_fields():
    payload = {
        "material_name": "Incomplete Trim",
        "material_type": "Trim",
        "uom": "Pieces",
        "minimum_stock_level": 50.00
    }
    response = client.post("/materials/", json=payload)
    assert response.status_code == 422


# --- 3. Issuing More Stock Than Available Test ---
def test_issue_excess_stock():
    mat_res = client.post("/materials/", json={
        "material_code": "TRM-01",
        "material_name": "Plastic Button",
        "material_type": "Trim",
        "uom": "Pieces",
        "unit_rate": 0.10,
        "minimum_stock_level": 200.00,
        "status": "Active"
    })
    mat_id = mat_res.json()["id"]

    client.post("/transactions/", json={
        "material_id": mat_id,
        "transaction_type": "Opening Stock",
        "quantity": 100.00
    })

    issue_res = client.post("/transactions/", json={
        "material_id": mat_id,
        "transaction_type": "Material Issue",
        "quantity": 150.00
    })
    assert issue_res.status_code == 400
    assert "Insufficient stock" in issue_res.json()["detail"]


# --- 4. Processing Inward/Outward and Verifying Closing Stock ---
def test_inward_outward_and_closing_stock():
    mat_res = client.post("/materials/", json={
        "material_code": "PKG-01",
        "material_name": "Polybag Medium",
        "material_type": "Packaging",
        "uom": "Pieces",
        "unit_rate": 0.50,
        "minimum_stock_level": 50.00,
        "status": "Active"
    })
    mat_id = mat_res.json()["id"]

    client.post("/transactions/", json={"material_id": mat_id, "transaction_type": "Opening Stock", "quantity": 500.00})
    client.post("/transactions/", json={"material_id": mat_id, "transaction_type": "Material Inward", "quantity": 200.00})
    client.post("/transactions/", json={"material_id": mat_id, "transaction_type": "Material Issue", "quantity": 150.00})

    report_res = client.get(f"/reports/material-details/{mat_id}")
    assert report_res.status_code == 200
    assert float(report_res.json()["closing_stock"]) == 550.00


# --- 5. Attempting Transactions Against Inactive Materials Test ---
def test_inactive_material_transaction():
    mat_res = client.post("/materials/", json={
        "material_code": "FAB-INACTIVE",
        "material_name": "Discontinued Fabric",
        "material_type": "Fabric",
        "uom": "Meter",
        "unit_rate": 3.00,
        "minimum_stock_level": 10.00,
        "status": "Inactive"
    })
    mat_id = mat_res.json()["id"]

    res = client.post("/transactions/", json={
        "material_id": mat_id,
        "transaction_type": "Material Inward",
        "quantity": 100.00
    })
    assert res.status_code == 400
    assert "Inactive" in res.json()["detail"]


# --- 6. Negative or Zero Transaction Quantities Test ---
def test_negative_or_zero_quantity_transaction():
    res_zero = client.post("/transactions/", json={
        "material_id": 1,
        "transaction_type": "Material Inward",
        "quantity": 0.00
    })
    assert res_zero.status_code == 422

    res_neg = client.post("/transactions/", json={
        "material_id": 1,
        "transaction_type": "Material Inward",
        "quantity": -50.00
    })
    assert res_neg.status_code == 422


# --- 7. Concurrent Stock Issue Requests Test ---
def test_concurrent_stock_issues():
    mat_res = client.post("/materials/", json={
        "material_code": "FAB-CONC",
        "material_name": "Concurrent Test Fabric",
        "material_type": "Fabric",
        "uom": "Meter",
        "unit_rate": 10.00,
        "minimum_stock_level": 20.00,
        "status": "Active"
    })
    mat_id = mat_res.json()["id"]

    client.post("/transactions/", json={
        "material_id": mat_id,
        "transaction_type": "Opening Stock",
        "quantity": 400.00
    })

    def issue_worker():
        return client.post("/transactions/", json={
            "material_id": mat_id,
            "transaction_type": "Material Issue",
            "quantity": 300.00
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(issue_worker), executor.submit(issue_worker)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    status_codes = [res.status_code for res in results]
    assert 201 in status_codes
    assert 400 in status_codes

    report = client.get(f"/reports/material-details/{mat_id}").json()
    assert float(report["closing_stock"]) == 100.00