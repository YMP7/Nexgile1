"""FastAPI app. Run from the repo root: uvicorn backend.main:app"""
from fastapi import FastAPI, HTTPException

from . import analysis

app = FastAPI(title="Revenue bridge API")


@app.get("/api/revenue-bridge")
def revenue_bridge():
    return analysis.get_numbers()["bridge"]


@app.get("/api/initiative/{name}")
def initiative(name: str):
    inits = analysis.get_numbers()["initiatives"]
    if name not in inits:
        raise HTTPException(404, f"unknown initiative; use one of {sorted(inits)}")
    return inits[name]


@app.get("/api/summary")
def summary():
    return analysis.get_numbers()["summary"]
