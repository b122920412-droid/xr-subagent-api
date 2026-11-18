"""XR 場景物件管理 API 自動化測試（依 docs/spec.md 第 8 節）。

執行方式（PowerShell，專案根目錄）：
    .\\.venv\\Scripts\\python.exe -m pytest tests -v

注意：本機 Python 為 3.9.13，避免使用 PEP 604（X | None）語法。
"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

import db
from main import app, get_db  # get_db 必須與 main.Depends 用的是同一個物件


# --------------------------------------------------------------------------- #
# 8.1 fixture：雙保險（置換 db.DB_PATH + dependency override + lifespan）
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(test_db))
    db.init_db()  # 顯式建表（lifespan 也會建一次，IF NOT EXISTS 安全）

    def override_get_db():
        conn = sqlite3.connect(db.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:  # with 才會觸發 lifespan
            yield c
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# 測試輔助函式
# --------------------------------------------------------------------------- #
def valid_payload(**overrides):
    """回傳一份合法的 ObjectCreate body，可用關鍵字覆蓋特定欄位。"""
    payload = {
        "name": "  chair  ",
        "model_url": "/models/chair.glb",
        "position": [1, 0, 2.5],
        "rotation": [0, 1.57, 0],
        "scale": [1, 1, 1],
    }
    payload.update(overrides)
    return payload


def post_raw_json(client, payload):
    """以原始 content 送出 JSON。

    httpx 0.28 在 json= 參數使用 allow_nan=False，無法序列化 NaN/Infinity；
    这里改用 json.dumps 的預設（allow_nan=True）產生 'NaN'/'Infinity' token，
    再以 content= 送出。Starlette 的 request.json() 底層 json.loads 會將其
    解析回真正的 float('nan')/float('inf')，因此仍能驗證 API 的有限數檢查。
    """
    body = json.dumps(payload)  # allow_nan=True（預設）
    return client.post(
        "/objects",
        content=body,
        headers={"Content-Type": "application/json"},
    )


def assert_422(response, field=None, error_type=None):
    """驗證 422 回應格式：detail 為 list，且（選擇性）含指定欄位 / 錯誤類型。"""
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list), detail
    if field is not None:
        assert any(field in e["loc"] for e in detail), detail
    if error_type is not None:
        assert any(e["type"] == error_type for e in detail), detail


def assert_404(response):
    """驗證 404 回應格式：detail 必須完全等於 'Object not found'。"""
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Object not found"}


def assert_object(body, *, name="chair", model_url="/models/chair.glb",
                  position=None, rotation=None, scale=None, object_id=None):
    """驗證 ObjectOut 的欄位內容與型別。

    可變預設值改用 None + 函式內建立，避免共享可變物件（future-proof）；
    預設內容與斷言強度維持不變。
    """
    if position is None:
        position = [1.0, 0.0, 2.5]
    if rotation is None:
        rotation = [0.0, 1.57, 0.0]
    if scale is None:
        scale = [1.0, 1.0, 1.0]
    if object_id is not None:
        assert isinstance(body["id"], int) and body["id"] == object_id
    else:
        assert isinstance(body["id"], int) and body["id"] > 0
    assert body["name"] == name
    assert body["model_url"] == model_url
    assert body["position"] == position
    assert body["rotation"] == rotation
    assert body["scale"] == scale
    for key in ("position", "rotation", "scale"):
        assert all(isinstance(v, float) for v in body[key])


# --------------------------------------------------------------------------- #
# 正常 CRUD（案例 1–6、17、18）
# --------------------------------------------------------------------------- #
def test_health(client):
    """案例 1：健康檢查。"""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_empty(client):
    """案例 2：空資料表回傳空陣列（不是 404）。"""
    r = client.get("/objects")
    assert r.status_code == 200
    assert r.json() == []


def test_create_ok(client):
    """案例 3：建立成功——name 被 trim、整數轉浮點、id 為正整數。"""
    r = client.post("/objects", json=valid_payload())
    assert r.status_code == 201, r.text
    assert_object(r.json())


def test_list_after_create(client):
    """案例 4：建立後可查。"""
    created = client.post("/objects", json=valid_payload())
    assert created.status_code == 201

    r = client.get("/objects")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "chair"
    assert body[0]["id"] == created.json()["id"]


def test_get_one(client):
    """案例 5：單筆查詢，回傳欄位與建立時一致。"""
    created = client.post("/objects", json=valid_payload()).json()
    oid = created["id"]

    r = client.get("/objects/{}".format(oid))
    assert r.status_code == 200
    assert r.json() == created


def test_get_not_found(client):
    """案例 6：查不存在 id → 404。"""
    assert_404(client.get("/objects/9999"))


def test_put_ok_full_update(client):
    """案例 17a：全量更新成功，name 改變、id 不變。"""
    created = client.post("/objects", json=valid_payload()).json()
    oid = created["id"]

    updated_body = {
        "name": "table",
        "model_url": "https://example.com/table.glb",
        "position": [0, 0, 0],
        "rotation": [0, 0, 0],
        "scale": [2, 2, 2],
    }
    r = client.put("/objects/{}".format(oid), json=updated_body)
    assert r.status_code == 200, r.text
    assert_object(
        r.json(),
        name="table",
        model_url="https://example.com/table.glb",
        position=[0.0, 0.0, 0.0],
        rotation=[0.0, 0.0, 0.0],
        scale=[2.0, 2.0, 2.0],
        object_id=oid,
    )

    # 透過 GET 再次確認已持久化
    assert client.get("/objects/{}".format(oid)).json()["name"] == "table"


def test_delete_ok_then_404(client):
    """案例 18a：刪除成功回 204 且 body 為空；再 GET → 404。"""
    created = client.post("/objects", json=valid_payload()).json()
    oid = created["id"]

    r = client.delete("/objects/{}".format(oid))
    assert r.status_code == 204
    assert r.content == b""

    assert_404(client.get("/objects/{}".format(oid)))
    assert client.get("/objects").json() == []


# --------------------------------------------------------------------------- #
# 不存在的 ID（案例 6、17b、18b）
# --------------------------------------------------------------------------- #
def test_put_not_found(client):
    """案例 17b：PUT 合法 body 到不存在的 id → 404。"""
    assert_404(client.put("/objects/9999", json=valid_payload(name="table")))


def test_delete_not_found(client):
    """案例 18b：DELETE 不存在的 id → 404。"""
    assert_404(client.delete("/objects/9999"))


# --------------------------------------------------------------------------- #
# 錯誤驗證（案例 7–16、19–20）
# --------------------------------------------------------------------------- #
def test_path_not_int(client):
    """案例 7：path 非整數 → 422，loc 含 'object_id'。"""
    assert_422(client.get("/objects/abc"), field="object_id")


@pytest.mark.parametrize("bad_name", ["", "   "])
def test_empty_name(client, bad_name):
    """案例 8：空名稱（含全空白）→ 422，detail 為 list。"""
    assert_422(client.post("/objects", json=valid_payload(name=bad_name)),
               field="name")


def test_name_too_long(client):
    """案例 9：名稱超過 100 字 → 422，loc 含 'name'。"""
    assert_422(client.post("/objects", json=valid_payload(name="x" * 101)),
               field="name")


@pytest.mark.parametrize("bad_url", ["ftp://x.glb", "www.x.com/a", "x" * 501])
def test_bad_model_url(client, bad_url):
    """案例 10：URL 前綴錯誤 / 過長 → 422，loc 含 'model_url'。"""
    assert_422(client.post("/objects", json=valid_payload(model_url=bad_url)),
               field="model_url")


def test_empty_model_url(client):
    """案例 11：URL 空字串 → 422，loc 含 'model_url'。"""
    assert_422(client.post("/objects", json=valid_payload(model_url="")),
               field="model_url")


@pytest.mark.parametrize("bad_field", ["position", "rotation", "scale"])
def test_vec_too_short(client, bad_field):
    """案例 12：向量長度不足 → 422，loc 含對應欄位名。"""
    assert_422(client.post("/objects", json=valid_payload(**{bad_field: [1, 2]})),
               field=bad_field)


# --------------------------------------------------------------------------- #
# 已修正（原框架層缺陷）：coder 已在 main.py 註冊自訂 RequestValidationError
# handler，於序列化前遞迴把 error 中的 non-finite float 轉成
# "NaN" / "Infinity" / "-Infinity" 字串，因此含 NaN / Infinity 的 request
# 現在可正確回 422（detail 為 list、loc 含對應欄位名）。
# 以下案例均為正式測試，無 xfail；底層驗證邏輯另由下方 schema 層測試驗證。
# --------------------------------------------------------------------------- #
def test_vec_nan(client):
    """案例 13：向量含 NaN → 422，loc 含 'rotation'。"""
    assert_422(post_raw_json(client, valid_payload(
        rotation=[float("nan"), 0, 0])), field="rotation")


@pytest.mark.parametrize(
    "bad_field,bad_vec",
    [("position", [float("inf"), 0, 0]),
     ("rotation", [0, float("-inf"), 0])],
)
def test_vec_infinity(client, bad_field, bad_vec):
    """案例 14：向量含 Infinity / -Infinity → 422，loc 含對應欄位名。"""
    assert_422(post_raw_json(client, valid_payload(
        **{bad_field: bad_vec})), field=bad_field)


def test_schema_rejects_non_finite_vectors():
    """驗證底層 Pydantic validator 確實拒絕 NaN / Infinity（不經 HTTP 序列化）。

    搭配上方 HTTP 案例，確認驗證與 422 回應序列化两端皆正確。
    """
    from pydantic import ValidationError

    from schemas import ObjectCreate

    bad_vectors = [
        float("nan"),
        float("inf"),
        float("-inf"),
    ]
    for bad in bad_vectors:
        with pytest.raises(ValidationError) as exc_info:
            ObjectCreate.model_validate(valid_payload(position=[bad, 0, 0]))
        assert any("position" in e["loc"] for e in exc_info.value.errors())


def test_vec_huge_integer_overflow(client):
    """超大整數元素（float() 轉型拋 OverflowError）→ 422，不得為 500。

    10**1000 是合法 JSON 整數（1001 位，低於 CPython int→str 上限），
    httpx 0.28 的 json= 不適用此處故以 json.dumps(...).encode() + content= 送出。
    422 detail 的 input 會包含這個大整數，必須能被自訂 handler 序列化。
    """
    payload = valid_payload(position=[10 ** 1000, 0, 0])
    body = json.dumps(payload).encode("utf-8")
    r = client.post(
        "/objects",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert_422(r, field="position")


def test_vec_string_coercion(client):
    """案例 15：字串轉型誤入（Pydantic 預設會把 '1' 轉成 1.0）→ 422。"""
    assert_422(client.post("/objects", json=valid_payload(
        position=["1", 2, 3])), field="position")


def test_vec_bool(client):
    """向量含布林值（bool 是 int 子類別，需明確排除）→ 422。"""
    assert_422(client.post("/objects", json=valid_payload(
        position=[True, 2, 3])), field="position")


@pytest.mark.parametrize("bad_scale", [[1, 0, 2], [1, -1, 2], [1, 1, -0.0001]])
def test_bad_scale(client, bad_scale):
    """案例 16：scale 為 0 / 負數 → 422，loc 含 'scale'。"""
    assert_422(client.post("/objects", json=valid_payload(scale=bad_scale)),
               field="scale")


def test_extra_id_field(client):
    """案例 19（選配）：客戶端送 id 欄位 → 422（extra_forbidden）。"""
    body = valid_payload()
    body["id"] = 1
    assert_422(client.post("/objects", json=body),
               field="id", error_type="extra_forbidden")


def test_unknown_extra_field(client):
    """未知額外欄位一律拒絕 → 422（extra_forbidden）。"""
    body = valid_payload()
    body["color"] = "red"
    assert_422(client.post("/objects", json=body),
               field="color", error_type="extra_forbidden")


def test_put_9999_invalid_body(client):
    """案例 20（選配）：PUT 9999 + 無效 body → 422（驗證優先於 404）。"""
    assert_422(client.put("/objects/9999", json=valid_payload(scale=[1, 0, 2])),
               field="scale")


# --------------------------------------------------------------------------- #
# 選配案例（21、22）
# --------------------------------------------------------------------------- #
def test_name_filter(client):
    """案例 21（選配）：?name= 模糊比對，只回符合的物件。"""
    assert client.post("/objects", json=valid_payload(name="chair")).status_code == 201
    assert client.post("/objects", json=valid_payload(
        name="table", model_url="/models/table.glb")).status_code == 201
    assert client.post("/objects", json=valid_payload(
        name="armchair", model_url="/models/armchair.glb")).status_code == 201

    r = client.get("/objects", params={"name": "chair"})
    assert r.status_code == 200
    names = [item["name"] for item in r.json()]
    assert names == ["chair", "armchair"]  # LIKE %chair% 且依 id 升冪

    assert client.get("/objects", params={"name": "not-exist"}).json() == []


def test_id_increments(client):
    """案例 22（選配）：連續建立兩筆，id 遞增且不重複。"""
    first = client.post("/objects", json=valid_payload()).json()
    second = client.post("/objects", json=valid_payload(name="table")).json()

    assert isinstance(first["id"], int) and isinstance(second["id"], int)
    assert first["id"] > 0
    assert second["id"] > first["id"]


# --------------------------------------------------------------------------- #
# 已修正紀錄（原「NaN / Infinity 回 500」缺陷）
# --------------------------------------------------------------------------- #
# 原問題重現：POST /objects，body 含 position:[NaN,0,0] → 原為 HTTP 500。
#   （JSON 的 NaN 是非標準 token，Python json.loads 可解析；
#     httpx 0.28 的 json= 不允許 NaN，故測試以 raw content 送出。）
#
# 原根因：FastAPI 預設 exception handler 把 input=[nan,...] 原樣放進 422 body，
#   Starlette JSONResponse 以 json.dumps(allow_nan=False) 序列化時拋 ValueError。
#
# 修正（coder 已完成）：main.py 註冊自訂 RequestValidationError handler，
#   序列化前遞迴把 non-finite float 轉成 "NaN"/"Infinity"/"-Infinity" 字串。
#   案例 13 / 14 已恢復為一般測試，預期並實際回 422，detail 為 list 且 loc 正確。
# --------------------------------------------------------------------------- #
