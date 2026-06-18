"""MeshTech — Tech Company — port 8131"""
import sys
sys.path.insert(0, "/app")
from shared.base_app import create_company_app
app = create_company_app()
