# XR 場景物件管理 API — 系統架構與 API 規格書

> 文件版本：1.0.0　｜　日期：2026-11-18　｜　產出者：architect
>
> 本文件是 **唯一實作依據**。coder 請照本文件第 3、4、6、7 節的程式碼片段實作；tester 請照第 8 節撰寫測試。
>
> ⚠️ 與既有 `docs/compare.md` 的差異：該比較報告推薦「SQLite + SQLAlchemy」，但**本規格推翻該結論**。本專案硬性要求只用 Python 標準函式庫 `sqlite3`，**不得使用 SQLAlchemy / aiosqlite / 任何 ORM**。`app.py`（Streamlit YouBike 程式）與本次 API 無關，請保留原樣、不要改動。

---

## 1. 概述與目標

### 1.1 目標

建立一個輕量、可單機啟動、易於自動化測試的 REST API，用於管理 XR 場景中的 3D 物件。物件具備名稱、模型資源路徑，以及位置／旋轉／縮放三個三維向量。

### 1.2 設計原則

| 原則 | 說明 |
| --- | --- |
| 零外部服務 | 資料庫是單一檔案，不安裝、不啟動任何 DB server。 |
| 標準函式庫優先 | 資料存取只用 `sqlite3`；不引入 ORM。 |
| 驗證前移 | 所有輸入驗證在 Pydantic v2 完成，失敗一律 HTTP 422， handler 內不再做型別檢查。 |
| 可隔離測試 | 透過 `get_db` dependency override 或置換 `db.DB_PATH`，讓每個測試有自己的暫存 DB。 |
| 單一真值來源 | `main.py` 必須 `from db import get_db`，並用 `Depends(get_db)`，才能被 `app.dependency_overrides[get_db]` 覆寫。 |

### 1.3 啟動方式（coder 需更新 `requirements.txt`）

```bash
pip install -r requirements.txt
uvicorn main:app --reload          # http://127.0.0.1:8000
# 文件： http://127.0.0.1:8000/docs
```

> `requirements.txt` 目前只有 Streamlit 相關套件，coder 必須加入第 2 節列出的五個套件（可保留既有 Streamlit 套件，但 API 不依賴它們）。pytest 與 httpx 屬開發／測試依賴，仍建議寫入同一份檔案以方便繳交重現。

---

## 2. 技術堆疊與相依套件清單

| 套件 | 版本範圍 | 用途 | 類別 |
| --- | --- | --- | --- |
| `fastapi` | `>=0.110,<1.0` | 路由、Dependency Injection、錯誤回應、OpenAPI | 執行 |
| `uvicorn` | `>=0.27,<1.0` | ASGI server | 執行 |
| `pydantic` | `>=2.0,<3.0` | v2 模型驗證（`field_validator` / `ConfigDict`） | 執行 |
| `pytest` | `>=8.0,<9.0` | 測試執行器 | 測試 |
| `httpx` | `>=0.27,<1.0` | `fastapi.testclient.TestClient` 的底層 client | 測試 |
| `sqlite3` | Python 標準函式庫（隨 CPython，無須安装） | 資料庫存取 | 內建 |

**明確禁止**：`sqlalchemy`、`aiosqlite`、`databases`、`tortoise-orm`、`peewee`、`pymysql`、`psycopg2` 等任何 ORM／非標準 DB 驅動。

建議寫入 `requirements.txt` 的內容（coder 處理）：

```text
fastapi>=0.110,<1.0
uvicorn>=0.27,<1.0
pydantic>=2.0,<3.0
pytest>=8.0,<9.0
httpx>=0.27,<1.0
```

> 注意：`TestClient` 環境若缺少 `httpx` 會在 `import` 時直接報錯，因此 `httpx` 不可省略。

---

## 3. 資料模型

### 3.1 欄位總表

| 欄名 | 型別（API） | DB 欄位型別 | 必填 | 驗證規則 | 說明 |
| --- | --- | --- | --- | --- | --- |
| `id` | `int` | `INTEGER PRIMARY KEY AUTOINCREMENT` | 唯讀 | 由伺服器產生；客戶端送出即 422 | 正整數，唯一，遞增 |
| `name` | `str` | `TEXT NOT NULL` | ✅ | `strip()` 後長度 1–100，不可為空 | 前後空白會被移除後存入 |
| `model_url` | `str` | `TEXT NOT NULL` | ✅ | 長度 1–500；必須以 `http://`、`https://` 或 `/` 開頭 | 不做 trim，前綴必須在字首 |
| `position` | `list[float]` | `TEXT NOT NULL`（JSON 陣列） | ✅ | 剛好 3 個有限數 `[x, y, z]` | 世界座標，單位由前端約定 |
| `rotation` | `list[float]` | `TEXT NOT NULL`（JSON 陣列） | ✅ | 剛好 3 個有限數 `[x, y, z]` | 弧度，不限制正負與範圍 |
| `scale` | `list[float]` | `TEXT NOT NULL`（JSON 陣列） | ✅ | 剛好 3 個有限數，**每個 `> 0`** | 0 與負數皆驗證失敗 |

### 3.2 Pydantic v2 模型（`schemas.py`）

三個對外模型：

- `ObjectCreate`：`name`、`model_url`、`position`、`rotation`、`scale`（**不含 `id`**），用於 `POST /objects`。
- `ObjectUpdate`：欄位與 `ObjectCreate` **完全相同**（PUT 為全量替換，非部分更新），用於 `PUT /objects/{id}`。
- `ObjectOut`：在 `ObjectCreate` 的基礎上多一個 `id: int`，用於所有回應。

三者共用一個内部基底 `ObjectBase`（不需要 export）。完整程式碼如下，coder 可直接照抄：

```python
# schemas.py
from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _clean_vec(value: Any, field: str, *, positive: bool) -> list[float]:
    """共用的三維向量驗證器。positive=True 時額外要求每個元素 > 0。"""
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} 必須是長度為 3 的陣列")
    if len(value) != 3:
        raise ValueError(f"{field} 必須剛好 3 個元素")

    result: list[float] = []
    for item in value:
        # bool 是 int 的子類別，必須明確排除
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{field} 元素必須是數字，不接受字串或布林值")
        try:
            num = float(item)
        except (OverflowError, ValueError):
            raise ValueError(f"{field} 元素必須是有限數（不可為 NaN / Infinity）")
        if not math.isfinite(num):
            raise ValueError(f"{field} 元素必須是有限數（不可為 NaN / Infinity）")
        if positive and num <= 0:
            raise ValueError("scale 元素必須嚴格大於 0")
        result.append(num)
    return result


class ObjectBase(BaseModel):
    # from_attributes：讓 ObjectOut 可用 model_validate(dict)
    # extra="forbid"：客戶端不得送出 id 或任何未知欄位 → 422
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    name: str
    model_url: str
    position: list[float]
    rotation: list[float]
    scale: list[float]

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        s = v.strip()
        if not (1 <= len(s) <= 100):
            raise ValueError("name 去除前後空白後長度必須為 1–100，且不可為空")
        return s

    @field_validator("model_url")
    @classmethod
    def _validate_model_url(cls, v: str) -> str:
        if not (1 <= len(v) <= 500):
            raise ValueError("model_url 長度必須為 1–500")
        if not (v.startswith("http://") or v.startswith("https://") or v.startswith("/")):
            raise ValueError("model_url 必須以 http://、https:// 或 / 開頭")
        return v

    @field_validator("position", "rotation", mode="before")
    @classmethod
    def _validate_vec3(cls, v: Any, info: Any) -> list[float]:
        # mode="before"：在 Pydantic 自動把 "1" 轉成 1.0 之前先攔截字串
        return _clean_vec(v, info.field_name, positive=False)

    @field_validator("scale", mode="before")
    @classmethod
    def _validate_scale(cls, v: Any) -> list[float]:
        return _clean_vec(v, "scale", positive=True)


class ObjectCreate(ObjectBase):
    pass


class ObjectUpdate(ObjectBase):
    pass


class ObjectOut(ObjectBase):
    id: int
```

### 3.3 序列化注意事項（重要，避免踩雷）

`sqlite3.Row` **不支援 `.id` 這種 attribute 存取**，只支援 `row["id"]`。因此即使 `ObjectOut` 設了 `from_attributes=True`，也**不能**直接 `ObjectOut.model_validate(row)`。

正確做法是先在 endpoint 把 `Row` 轉成 `dict`，再交給 Pydantic：

```python
data = dict(row)
data["position"] = json.loads(data["position"])
data["rotation"] = json.loads(data["rotation"])
data["scale"] = json.loads(data["scale"])
obj = ObjectOut.model_validate(data)   # ✅
# ObjectOut.model_validate(row)        # ❌ 會失敗
```

> `from_attributes=True` 仍必須設定，以符合規格並讓未來從 ORM-like 物件轉換時可用；差異只在於此處的資料來源是 `sqlite3.Row`。

---

## 4. 輸入驗證規則

所有驗證失敗都由 FastAPI 自動回 **HTTP 422**，body 格式見第 9 節。handler 不需要自行回傳 422。

### 4.1 逐條規則與錯誤情境

| # | 欄位 | 規則 | 有效範例 | 無效範例（預期 422） |
| --- | --- | --- | --- | --- |
| V1 | `id` | 唯讀，客戶端不可送出 | 不送出 | `{"id": 1, ...}` → `extra_forbidden` |
| V2 | `name` | `strip()` 後非空且 1–100 字 | `" chair "` → 存 `"chair"` | `""`、`"   "`、`"x"*101` |
| V3 | `model_url` | 1–500 字，前綴 `http://` / `https://` / `/` | `"/models/a.glb"`、`"https://x/b.glb"` | `""`、`"ftp://x"`、`"www.x.com/a"`、`"x"*501` |
| V4 | `position` | 必須是 list/tuple，剛好 3 個元素 | `[0, 1.5, -2]` | `{}`、`"1,2,3"`、`[1,2]`、`[1,2,3,4]` |
| V5 | `position` | 每個元素必須是 `int`/`float`，**不接受字串** | `[1, 2, 3]` | `["1", 2, 3]`、`[None, 2, 3]`、`[True, 2, 3]` |
| V6 | `position` | 每個元素必須有限（拒 NaN / Infinity） | `[1e10, -0.0, 3]` | `[float("nan"), 2, 3]`、`[float("inf"), 2, 3]`、`[float("-inf"), 2, 3]`、極大整數（`10**1000`）→ 422 |
| V7 | `rotation` | 同 V4/V5/V6（弧度，不限制範圍） | `[3.14, -6.28, 100]` | `[1, 2]`、`[1, "2", 3]`、`[nan, 0, 0]` |
| V8 | `scale` | 剛好 3 個有限數字（同 V4/V5/V6） | `[1, 1, 1]` | `[1, 2]`、`[1, "2", 3]`、`[inf, 1, 1]` |
| V9 | `scale` | **每個元素嚴格 `> 0`** | `[0.5, 1, 2.5]` | `[0, 1, 1]`、`[-1, 1, 1]`、`[1, 1, -0.0001]` |
| V10 | -path `id` | 必須是整數 | `/objects/1` | `/objects/abc` → 422，`loc=["path","object_id"]` |
| V11 | 整體 | 未知額外欄位一律拒絕 | — | `{"name":..., "color":"red", ...}` → 422 |

### 4.2 驗證順序（tester 需注意）

FastAPI **先解析並驗證 path / query / body，再進入 handler**。因此：

- `PUT /objects/999` 搭配無效 body → 回 **422**（不是 404）。
- `PUT /objects/999` 搭配有效 body → 回 **404**。
- `GET /objects/abc` → 回 **422**。
- `POST` 的 `id` 檢查屬 body 驗證，也早於任何 DB 操作。

### 4.3 設計說明

- 使用 `mode="before"` 是為了**阻擋 Pydantic 的隱性轉型**：`list[float]` 預設會把 `"1"` 轉成 `1.0`，若不攔截就無法「拒絕字串型態的轉型誤入」。
- 明確排除 `bool`，因為 Python 中 `isinstance(True, int)` 為 `True`，否則 `[True, 1, 1]` 會被當成 `[1.0, 1.0, 1.0]`。
- 整數接受並正規化為浮點數，因此 JSON 回應中會看到 `1.0`。tester 比對時請用數值相等（`1 == 1.0` 在 Python 成立），不要比對字串。

---

## 5. API 端點規格

Base URL：`http://127.0.0.1:8000`。所有 request/response 皆為 `application/json`（204 除外）。

### 5.1 `GET /health`

| 項目 | 內容 |
| --- | --- |
| 說明 | 健康檢查，便於測試與驗證服務已啟動 |
| 參數 | 無 |
| Request body | 無 |
| Success | `200 OK` |
| Response | `{"status": "ok"}` |

```http
GET /health HTTP/1.1
```
```json
{ "status": "ok" }
```

---

### 5.2 `GET /objects`

| 項目 | 內容 |
| --- | --- |
| 說明 | 列出所有物件，依 `id` 升冪排序 |
| Query（選用） | `name: str | None = None` — 模糊比對（`LIKE %name%`）。不提供則回傳全部。 |
| Request body | 無 |
| Success | `200 OK` |
| Response | `ObjectOut` 陣列 |

```http
GET /objects HTTP/1.1
GET /objects?name=chair HTTP/1.1   # 選用过滤
```
```json
[
  {
    "id": 1,
    "name": "chair",
    "model_url": "/models/chair.glb",
    "position": [1.0, 0.0, 2.5],
    "rotation": [0.0, 1.57, 0.0],
    "scale": [1.0, 1.0, 1.0]
  }
]
```

> 空資料表回傳 `[]`（不是 404）。

---

### 5.3 `GET /objects/{id}`

| 項目 | 內容 |
| --- | --- |
| 說明 | 取得單一物件 |
| Path | `id: int` |
| Success | `200 OK` + 單一 `ObjectOut` |
| Error | `404`（找不到）、`422`（id 非整數） |

```http
GET /objects/1 HTTP/1.1
```
成功：
```json
{
  "id": 1,
  "name": "chair",
  "model_url": "/models/chair.glb",
  "position": [1.0, 0.0, 2.5],
  "rotation": [0.0, 1.57, 0.0],
  "scale": [1.0, 1.0, 1.0]
}
```
失敗：
```json
{ "detail": "Object not found" }
```

---

### 5.4 `POST /objects`

| 項目 | 內容 |
| --- | --- |
| 說明 | 建立物件，`id` 由伺服器產生 |
| Request body | `ObjectCreate`（**不可含 `id`**） |
| Success | `201 Created` + 含 `id` 的 `ObjectOut` |
| Error | `422`（驗證失敗） |

Request：
```json
{
  "name": "  chair  ",
  "model_url": "/models/chair.glb",
  "position": [1, 0, 2.5],
  "rotation": [0, 1.57, 0],
  "scale": [1, 1, 1]
}
```
Response `201`：
```json
{
  "id": 1,
  "name": "chair",
  "model_url": "/models/chair.glb",
  "position": [1.0, 0.0, 2.5],
  "rotation": [0.0, 1.57, 0.0],
  "scale": [1.0, 1.0, 1.0]
}
```
> 注意 `name` 已被 trim，整數已轉為浮點數。建議 INSERT 後用 `cur.lastrowid` 再 SELECT 一次回傳，以確保回傳值與 DB 實際內容一致。

---

### 5.5 `PUT /objects/{id}`

| 項目 | 內容 |
| --- | --- |
| 說明 | **全量替換**指定物件的五個可寫欄位；`id` 不變 |
| Path | `id: int` |
| Request body | `ObjectUpdate`（五個欄位皆必填，結構同 `ObjectCreate`） |
| Success | `200 OK` + 更新後的 `ObjectOut` |
| Error | `404`（找不到）、`422`（驗證失敗或 id 非整數） |

Request：
```json
{
  "name": "table",
  "model_url": "https://example.com/table.glb",
  "position": [0, 0, 0],
  "rotation": [0, 0, 0],
  "scale": [2, 2, 2]
}
```
Response `200`：
```json
{
  "id": 1,
  "name": "table",
  "model_url": "https://example.com/table.glb",
  "position": [0.0, 0.0, 0.0],
  "rotation": [0.0, 0.0, 0.0],
  "scale": [2.0, 2.0, 2.0]
}
```
> 找不到時回 `{"detail": "Object not found"}`。驗證錯誤優先於 404（見 4.2）。

---

### 5.6 `DELETE /objects/{id}`

| 項目 | 內容 |
| --- | --- |
| 說明 | 刪除指定物件 |
| Path | `id: int` |
| Request body | 無 |
| Success | `204 No Content`，**body 必須為空** |
| Error | `404`（找不到）、`422`（id 非整數） |

```http
DELETE /objects/1 HTTP/1.1
HTTP/1.1 204 No Content
```
> 實作要點：`return Response(status_code=status.HTTP_204_NO_CONTENT)`，不要回 `None` 搭配額外 body。找不到時回 `{"detail": "Object not found"}` + 404。

---

### 5.7 端點與狀態碼總表

| Method | Path | 成功 | 主要失敗 |
| --- | --- | --- | --- |
| GET | `/health` | 200 | — |
| GET | `/objects` | 200 | — |
| GET | `/objects/{id}` | 200 | 404 / 422 |
| POST | `/objects` | 201 | 422 |
| PUT | `/objects/{id}` | 200 | 404 / 422 |
| DELETE | `/objects/{id}` | 204 | 404 / 422 |

---

## 6. 資料庫 schema 與連線管理

### 6.1 `db.py` 完整內容

```python
# db.py
import sqlite3

# 預設資料庫檔案路徑。測試可在 import 後改指向 tmp_path。
DB_PATH = "xr_objects.db"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS objects (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL,
    model_url TEXT    NOT NULL,
    position  TEXT    NOT NULL,   -- JSON 陣列：[x, y, z]
    rotation  TEXT    NOT NULL,   -- JSON 陣列：[x, y, z]
    scale     TEXT    NOT NULL    -- JSON 陣列：[x, y, z]，每個 > 0
)
"""


def init_db() -> None:
    """建立資料表（若不存在）。使用明確 close，因 with connect() 不會關閉連線。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI dependency：每次請求产生一條連線，结束時保证关闭。"""
    conn = sqlite3.connect(DB_PATH)   # 在呼叫時讀取 DB_PATH，方便 monkeypatch
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
```

### 6.2 設計要點

1. **欄位對應**：DB 用 7 個欄位，三個向量以 JSON 字串存放（`json.dumps` 寫入、`json.loads` 讀出）。格式固定為長度 3 的數字陣列。
2. **`row_factory = sqlite3.Row`**：必須在 `get_db()` 內設定，不可省略。
3. **`DB_PATH` 在呼叫時讀取**：`get_db()` 內直接參考模組全域變數，因此 `monkeypatch.setattr(db, "DB_PATH", ...)` 會生效；不要把路徑在 import 時用預設參數綁死。
4. **交易**：寫入（`INSERT` / `UPDATE` / `DELETE`）後必須 `conn.commit()`；查詢不需要。
5. **初始化時機**：在 `main.py` 用 lifespan 呼叫 `db.init_db()`，確保 `uvicorn main:app` 一啟動就有資料表。tester 只要在建立 `TestClient` **之前**改好 `db.DB_PATH`，lifespan 就會在暫存檔上建表。
6. **不啟用 WAL / 索引**：本規模（數十至數萬筆 CRUD）不需要；見第 10 節。
7. **COMMIT vs CLOSE**：`with sqlite3.connect(...)` 只會 commit/rollback，**不會關閉連線**，所以 `init_db()` 與 `get_db()` 都用 `try/finally: conn.close()`。

---

## 7. 檔案結構與職責

```text
XR_HW/
├── app.py               # 既有 Streamlit YouBike 程式（保留，不修改）
├── db.py                # 【新增】DB_PATH、init_db()、get_db()
├── schemas.py           # 【新增】ObjectCreate / ObjectUpdate / ObjectOut + 驗證
├── main.py              # 【新增】FastAPI app、lifespan、6 個端點、_row_to_out()
├── requirements.txt     # 【更新】加入 fastapi/uvicorn/pydantic/pytest/httpx
├── tests/
│   ├── .gitkeep
│   └── test_api.py      # 【新增】pytest + TestClient（tester 負責）
└── docs/
    ├── spec.md          # 本文件（architect 唯一產出）
    └── compare.md       # 既有評估報告（歷史文件，保留）
```

### 7.1 `main.py` 參考實作（coder 可直接照抄）

```python
# main.py
from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status

import db
from db import get_db                      # 必須是這個物件，供 dependency override
from schemas import ObjectCreate, ObjectOut, ObjectUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="XR 場景物件管理 API", version="1.0.0", lifespan=lifespan)

NOT_FOUND = "Object not found"


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
    name: Optional[str] = Query(default=None),      # 不用 str | None：本機 Python 3.9.13 不支援 PEP 604
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
```

> **Python 版本相容說明（偏離原稿）**：本機 Python 為 **3.9.13**，不支援 PEP 604 的 `str | None` 聯合法（需 3.10+）。因此 `list_objects` 的 `name` 參數改寫為 `Optional[str]` 並搭配 `from typing import Optional`。兩者行為完全等價（皆為「可為 `None` 的字串」），不影響 `Query(default=None)` 的驗證與 OpenAPI 輸出；coder 請以此版本為準。

### 7.2 資料流（請求生命週期）

```text
HTTP request
  → FastAPI 解析 path / query / body
  → Pydantic (ObjectCreate / ObjectUpdate) 驗證 ──失敗──> 422（handler 不執行）
  → endpoint 呼叫 Depends(get_db)
  → get_db 建立 sqlite3.Connection(row_factory=sqlite3.Row)，yield
  → endpoint 執行 SQL（寫入後 conn.commit()）
  → SELECT → sqlite3.Row → dict(row) → json.loads 向量 → ObjectOut.model_validate
  → FastAPI 序列化為 JSON + 狀態碼（200 / 201 / 204）
  → dependency teardown：conn.close()
```

### 7.3 給 coder 的修改建議摘要

- 新增 `db.py`、`schemas.py`、`main.py`（依上方程式碼）。
- 更新 `requirements.txt`（依第 2 節）。
- **不要**修改 `app.py`、`tests/**`、`docs/compare.md`。

---

## 8. 測試策略

### 8.1 推薦隔離方式（tester 請採用「雙保險」）

在 `tests/test_api.py` 建立 fixture：**同時**置換 `db.DB_PATH` 並覆寫 dependency。如此 lifespan 的 `init_db()` 與所有請求都會用同一個暫存檔，且不受工作目錄既有 `xr_objects.db` 影響。

```python
# tests/test_api.py
import sqlite3

import pytest
from fastapi.testclient import TestClient

import db
from main import app, get_db   # get_db 必須與 main.Depends 用的是同一個物件


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(test_db))
    db.init_db()                       # 显式建表（lifespan 也会建一次，IF NOT EXISTS 安全）

    def override_get_db():
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:     # with 才会触发 lifespan
            yield c
    finally:
        app.dependency_overrides.clear()
```

**替代做法（僅置換路徑）**：不改 dependency，只 `monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))` 再 `db.init_db()`。這可行，前提是 coder 照 6.1 讓 `get_db()` 在呼叫時才讀取 `DB_PATH`。

> 每個測試函式用同一個 `client` fixture 但 `tmp_path` 不同 → 彼此完全隔離，不需手動清理資料。

### 8.2 測試案例清單（19 個，tester 可逐條照寫）

| # | 案例 | 請求 | 預期狀態 | 關鍵斷言 |
| --- | --- | --- | --- | --- |
| 1 | 健康檢查 | `GET /health` | 200 | `json() == {"status": "ok"}` |
| 2 | 空列表 | `GET /objects` | 200 | `json() == []` |
| 3 | 建立成功 | `POST /objects`（合法資料） | 201 | `id` 為 `int` 且 `> 0`；`name == "chair"`（已 trim）；向量為 `float` |
| 4 | 建立後可查 | `POST` 後 `GET /objects` | 200 | `len == 1`，`[0]["name"] == "chair"` |
| 5 | 單筆查詢 | `GET /objects/{id}` | 200 | 回傳欄位與建立時一致 |
| 6 | 查不存在 | `GET /objects/9999` | 404 | `detail == "Object not found"` |
| 7 | path 非整數 | `GET /objects/abc` | 422 | `detail[0]["loc"]` 含 `"object_id"` |
| 8 | 空名稱 | `POST` name = `""` 或 `"   "` | 422 | `detail` 為 list |
| 9 | 名稱過長 | `POST` name = `"x"*101` | 422 | `detail[0]["loc"]` 含 `"name"` |
| 10 | URL 前綴錯誤 | `POST` model_url = `"ftp://x.glb"` | 422 | loc 含 `"model_url"` |
| 11 | URL 空字串 | `POST` model_url = `""` | 422 | loc 含 `"model_url"` |
| 12 | 向量長度不足 | `POST` position = `[1, 2]` | 422 | loc 含 `"position"` |
| 13 | 向量含 NaN | `POST` rotation = `[float("nan"), 0, 0]` | 422 | loc 含 `"rotation"` |
| 14 | 向量含 Infinity | `POST` position = `[float("inf"), 0, 0]` | 422 | loc 含 `"position"` |
| 15 | 字串轉型誤入 | `POST` position = `["1", 2, 3]` | 422 | loc 含 `"position"` |
| 16 | scale 為 0 / 負數 | `POST` scale = `[1, 0, 2]` 與 `[1, -1, 2]` | 422 | loc 含 `"scale"` |
| 17 | 全量更新 + 404 | `PUT /objects/{id}` 合法 → 200；`PUT /objects/9999` 合法 → 404 | 200 / 404 | 更新後 `name` 改變、`id` 不變 |
| 18 | 刪除 | `DELETE /objects/{id}` → 204；再 `GET` → 404 | 204 / 404 | 第一次 `response.content == b""`；`DELETE /objects/9999` → 404 |
| 19 | 極大整數 overflow | `POST` position = `[10**1000, 0, 0]` | 422 | `detail` 為 list 且 `detail[0]["loc"]` 含 `"position"`（**不可為 500**，見 3.2 / V6） |

**額外建議案例（可選）**：
- 客戶端送 `id` 欄位 → 422（案例 20，`extra_forbidden`）。
- `PUT /objects/9999` 搭配無效 body → 422（驗證優先於 404，案例 21）。
- `GET /objects?name=chair` 只回符合的物件（案例 22）。
- 連續建立兩筆，`id` 遞增且不重複（案例 23）。

### 8.3 範例測試碼（案例 3 與 16）

```python
def test_create_ok(client):
    r = client.post("/objects", json={
        "name": "  chair  ",
        "model_url": "/models/chair.glb",
        "position": [1, 0, 2.5],
        "rotation": [0, 1.57, 0],
        "scale": [1, 1, 1],
    })
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["id"], int) and body["id"] > 0
    assert body["name"] == "chair"
    assert body["position"] == [1.0, 0.0, 2.5]


@pytest.mark.parametrize("bad_scale", [[1, 0, 2], [1, -1, 2], [1, 2], [1, "2", 3]])
def test_bad_scale(client, bad_scale):
    r = client.post("/objects", json={
        "name": "chair",
        "model_url": "/a.glb",
        "position": [0, 0, 0],
        "rotation": [0, 0, 0],
        "scale": bad_scale,
    })
    assert r.status_code == 422
    assert any("scale" in e["loc"] for e in r.json()["detail"])
```

---

## 9. 錯誤回應格式

### 9.1 404 Not Found

由 `HTTPException(status_code=404, detail="Object not found")` 產生：

```http
HTTP/1.1 404 Not Found
Content-Type: application/json
```
```json
{ "detail": "Object not found" }
```

> `detail` 字串必須**完全**是 `Object not found`（大小寫、空格皆不可差）。

### 9.2 422 Unprocessable Entity

由 FastAPI / Pydantic 自動產生，`detail` 是**陣列**，每筆含 `loc` / `msg` / `type` / `input`：

```http
HTTP/1.1 422 Unprocessable Entity
```
```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "scale", 1],
      "msg": "Value error, scale 元素必須嚴格大於 0",
      "input": "0",
      "ctx": { "error": "scale 元素必須嚴格大於 0" },
      "url": "https://errors.pydantic.dev/2.x/v/value_error"
    }
  ]
}
```

常見 `loc` 前綴：
- 欄位驗證失敗 → `["body", "<field>"]`，向量元素失败會多一項索引，如 `["body", "scale", 1]`。
- path 非整數 → `["path", "object_id"]`。
- 未知欄位 → `["body", "<field>"]`，`type == "extra_forbidden"`。

### 9.3 其他狀態碼

| 狀態碼 | 情境 |
| --- | --- |
| 200 | GET 單筆／列表、PUT 成功 |
| 201 | POST 成功 |
| 204 | DELETE 成功（無 body） |
| 404 | 指定 id 不存在 |
| 422 | 任何輸入驗證失敗 |
| 500 | 未預期伺服器錯誤（不應在正常測試中出現） |

> ⚠️ **必要偏離（覆蓋原稿「不自訂 exception handler」的說法）**：實際執行環境為 `fastapi 0.128.8` + `pydantic 2.13.5`，在此環境下若請求攜帶 NaN / Infinity，Pydantic 雖會正確觸發 422 驗證錯誤，但該錯誤的 `detail[i]["input"]` 會帶入 non-finite float；FastAPI 預設的 `RequestValidationError` 序列化器在 `json.dumps(..., allow_nan=False)` 時會拋 `ValueError: Out of range float values are not JSON compliant`，最終被轉成 **500**，違反 V6 與「驗證失敗一律 422」的約定。
>
> 因此 coder 已在 `main.py` 註冊自訂 `@app.exception_handler(RequestValidationError)`：於回傳前遞迴走訪 `exc.errors()`，把 non-finite float 依序替換為字串 `"NaN"` / `"Infinity"` / `"-Infinity"`，再以 `JSONResponse(status_code=422, content={"detail": errors})` 回傳。此改動**只調整序列化方式**，對外合約不變：狀態碼仍為 **422**、`detail` 仍為 **list**、每筆 `loc` 仍含欄位名（例如 `["body", "position", 0]`）、`msg` / `type` / `input` 結構一致；tester 的斷言方式不受影響。
>
> **版本落差註記**：此版本（`pydantic 2.13.5`）的預設 422 輸出**不含 `url` 欄位**。第 9.2 節範例中的 `"url": "https://errors.pydantic.dev/2.x/v/value_error"` 屬早期版本落差，請以「不含 `url`」為準；tester 請勿把 `url` 當作必要欄位檢查。

---

## 10. 不在範圍內的事項

| 項目 | 說明 |
| --- | --- |
| 空間索引 / 幾何查詢 | 不做 R-tree、PostGIS、bounding box、距離或「附近物件」查詢。`position` 僅儲存與回傳。 |
| `?type=` 過濾 | 資料模型沒有 `type` 欄位，故不實作；僅選用支援 `?name=`。 |
| 部分更新（PATCH） | `PUT` 採全量替換；不提供 `PATCH`。 |
| 並發寫入優化 | 不啟用 WAL、不調整 `busy_timeout`、不做連線池。單一寫者鎖在本規模可接受。 |
| ORM / Migration | 不用 SQLAlchemy、Alembic；schema 變動靠 `CREATE TABLE IF NOT EXISTS`，不提供版本遷移。 |
| 身份驗證與授權 | 無 API key / JWT / 使用者權限，所有端點公開。 |
| 分頁 | `GET /objects` 回傳全部，不做 `limit` / `offset`。 |
| 批次操作 | 不提供批量建立／更新／刪除。 |
| 檔案上傳 | `model_url` 只是字串路徑，不上傳、不驗證 URL 可達性。 |
| 美化／前端 | `app.py` 的 Streamlit YouBike 頁面與本 API 無關，不整合。 |
| Async DB | endpoint 用同步 `def` + 同步 `sqlite3`，不改用 aiosqlite。 |

---

## 附錄：交接 check-list

**coder**
- [ ] 新增 `db.py`（`DB_PATH`、`init_db()`、`get_db()`，`row_factory=sqlite3.Row`，`finally: close()`）
- [ ] 新增 `schemas.py`（`ObjectBase` + `ObjectCreate` / `ObjectUpdate` / `ObjectOut`，`ConfigDict(from_attributes=True, extra="forbid")`，向量用 `mode="before"` 驗證）
- [ ] 新增 `main.py`（lifespan 呼叫 `init_db()`、6 個端點、404 detail 固定字串、DELETE 回空 body）
- [ ] 更新 `requirements.txt`（5 個套件）
- [ ] 不碰 `app.py`、`tests/**`、`docs/compare.md`

**tester**
- [ ] 依 8.1 建立 `client` fixture（置換 `DB_PATH` + `dependency_overrides`）
- [ ] 依 8.2 完成至少 18 個案例
- [ ] 422 檢查 `detail` 為 list 且 `loc` 含正確欄位名；404 檢查 `detail == "Object not found"`
- [ ] 不修改任何功能程式碼
