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
