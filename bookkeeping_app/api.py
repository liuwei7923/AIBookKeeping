"""FastAPI application composition."""

from fastapi import FastAPI

from bookkeeping_app.routes import admin, categorization_memory, health, transactions

app = FastAPI(title="AI Bookkeeping App MVP")
app.include_router(health.router)
app.include_router(admin.router)
app.include_router(categorization_memory.router)
app.include_router(transactions.router)
