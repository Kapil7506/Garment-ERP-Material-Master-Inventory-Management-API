# garment_ERP Project

## Description
This project helps garment_ERP manage tasks efficiently.

## Clone or extract the project folder into your workspace
1. create the folder name as garment_erp
2. cd garment_erp

## Create and activate a Python virtual environment
Python -m venv .ERP_env
# On Windows:
venv\Scripts\activate


## Install required packages:
pip install -r Requirement.txt

## Database Configuration
1. Install posgresql
2. $env:DATABASE_URL="postgresql://postgres:your_password@localhost:5432/Database_name"
3. Run the query CREATE DATABASE garment_erp_db
4. Ensure the database exists in PostgreSQL


## Start the development server using Uvicorn
Run the command line in console = uvicorn main:app --reload
