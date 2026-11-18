from __future__ import annotations

import json
import math
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import db
from db import get_db                      # 必須是這個物件，供 dependency override
from schemas import ObjectCreate, ObjectOut, ObjectUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="XR 場景物件管理 API", version="1.0.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


NOT_FOUND = "Object not found"


def _sanitize(value):
    """把 error 結構中的 non-finite float 轉成 JSON 可序列化字串。

    NaN -> "NaN", +Infinity -> "Infinity", -Infinity -> "-Infinity"。
    遞迴處理 list / tuple / dict；其餘型別（尤其 ctx 裡的例外物件）
    原樣保留，交給 jsonable_encoder 處理。
    """
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    return value


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    errors = jsonable_encoder(_sanitize(exc.errors()))
    return JSONResponse(status_code=422, content={"detail": errors})


def _row_to_out(row: sqlite3.Row) -> ObjectOut:
    data = dict(row)                      # sqlite3.Row → dict（123 行有說明）
    for key in ("position", "rotation", "scale"):
        data[key] = json.loads(data[key])
    return ObjectOut.model_validate(data)


def _check_exists(conn: sqlite3.Connection, object_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM objects WHERE id = ?", (object_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return row


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/objects", response_model=list[ObjectOut])
def list_objects(
    name: Optional[str] = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[ObjectOut]:
    if name is None:
        rows = conn.execute("SELECT * FROM objects ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM objects WHERE name LIKE ? ORDER BY id", (f"%{name}%",)
        ).fetchall()
    return [_row_to_out(r) for r in rows]


@app.get("/objects/{object_id}", response_model=ObjectOut)
def get_object(
    object_id: int,
    conn: sqlite3.Connection = Depends(get_db),
) -> ObjectOut:
    return _row_to_out(_check_exists(conn, object_id))


@app.post("/objects", response_model=ObjectOut, status_code=status.HTTP_201_CREATED)
def create_object(
    payload: ObjectCreate,
    conn: sqlite3.Connection = Depends(get_db),
) -> ObjectOut:
    cur = conn.execute(
        "INSERT INTO objects (name, model_url, position, rotation, scale) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            payload.name,
            payload.model_url,
            json.dumps(payload.position),
            json.dumps(payload.rotation),
            json.dumps(payload.scale),
        ),
    )
    conn.commit()
    return _row_to_out(_check_exists(conn, cur.lastrowid))


@app.put("/objects/{object_id}", response_model=ObjectOut)
def update_object(
    object_id: int,
    payload: ObjectUpdate,
    conn: sqlite3.Connection = Depends(get_db),
) -> ObjectOut:
    _check_exists(conn, object_id)
    conn.execute(
        "UPDATE objects SET name=?, model_url=?, position=?, rotation=?, scale=? "
        "WHERE id=?",
        (
            payload.name,
            payload.model_url,
            json.dumps(payload.position),
            json.dumps(payload.rotation),
            json.dumps(payload.scale),
            object_id,
        ),
    )
    conn.commit()
    return _row_to_out(_check_exists(conn, object_id))


@app.delete("/objects/{object_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_object(
    object_id: int,
    conn: sqlite3.Connection = Depends(get_db),
) -> Response:
    _check_exists(conn, object_id)
    conn.execute("DELETE FROM objects WHERE id = ?", (object_id,))
    conn.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
