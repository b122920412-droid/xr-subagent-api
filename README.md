# XR_HW — XR 場景物件管理 API 與 OpenCode 多代理權限設計

本資料夾包含一個以 Python + FastAPI + SQLite + pytest 實作的 **XR 場景物件管理 API**（含 WebXR / Three.js 首頁），並使用 OpenCode V2 的 **子代理（Subagent）** 功能，以**最小權限原則（Least Privilege）**拆分四個專業角色，由主代理（orchestrator）調度開發。

## 目錄結構

```text
.opencode/
├── agents/
│   ├── architect.md      # 架構師：產出 docs/spec.md
│   ├── coder.md          # 開發工程師：實作 FastAPI 程式碼
│   ├── tester.md         # 測試工程師：只在 tests/** 寫測試
│   ├── reviewer.md       # 程式碼審查員：完全唯讀
│   └── orchestrator.md   # 主代理／團隊協調者（primary）
└── opencode.jsonc        # default_agent = orchestrator
app.py                    # 既有 Streamlit YouBike 程式（本次 API 未使用）
db.py                     # sqlite3 連線與 init_db() / get_db()
schemas.py                # Pydantic v2 模型與輸入驗證
main.py                   # FastAPI app、6 個 API 端點、靜態掛載與首頁
static/
└── index.html            # WebXR / Three.js 3D 檢視首頁
docs/
├── spec.md               # architect 產出的 API 規格書
└── compare.md            # 資料庫方案比較報告
tests/
└── test_api.py           # tester 的 pytest 自動化測試
```

## 設計原則

1. **先寬後窄，最後符合者勝出**：OpenCode 的 `permissions` 是有順序的規則清單，**最後一筆符合的規則決定結果**。因此每份設定檔都先寫最寬的「全部拒絕」基線，再依序放寬特定動作、最後才寫路徑白名單。
2. **明確拒絕優於字典判斷**：OpenCode 內建基礎政策是 `* → allow`，所以一定要先用自己的 `* → deny` 覆蓋它，否則等於沒設限。
3. **職責分離**：每個人只能碰自己該碰的東西 — 架構師不寫程式、測試不改功能碼、審查員唯讀、協調者不碰檔案。
4. **嚴格白名單**：未被列出的動作（`webfetch`、`glob`、`grep` 等）一律維持拒絕。

`effect` 三種值：

| effect | 意義 |
| --- | --- |
| `allow` | 直接放行，不詢問 |
| `ask` | 等待使用者/客戶決定 |
| `deny` | 直接阻擋 |

## 權限設計說明表

| 代理 (ID) | 模式 | 職責 | `read` | `edit` | `shell` | `subagent` | 備註 |
| --- | --- | --- | :---: | :---: | :---: | :---: | --- |
| **architect** | subagent | 系統架構與 API 規格設計 | ✅ 全部 | ⚠️ 僅 `docs/**` | ❌ | ❌ | 唯一產出 `docs/spec.md`，避免偷寫程式碼 |
| **coder** | subagent | 依規格實作 Python FastAPI | ✅ 全部 | ✅ 全部 | ⚠️ `ask` | ❌ | 唯一可寫功能程式碼；shell 需確認 |
| **tester** | subagent | 撰寫並執行 pytest | ✅ 全部 | ⚠️ 僅 `tests/**` | ✅ | ❌ | 不能修改功能程式碼 |
| **reviewer** | subagent | 客觀審查品質與安全 | ✅ 全部 | ❌ | ❌ | ❌ | 完全唯讀，只提建議 |
| **orchestrator** | primary | 調度四個子代理並彙整 | ✅ 全部 | ❌ | ❌ | ⚠️ 僅四個 ID | 白名單：`architect` / `coder` / `tester` / `reviewer` |

> 圖例：✅ 允許　⚠️ 受限　❌ 拒絕

## 各代理的規則順序（由寬到窄）

### architect

```yaml
- { action: "*",       resource: "*",       effect: deny }  # 最寬：全部拒絕
- { action: "shell",   resource: "*",       effect: deny }  # 明確禁止 shell
- { action: "subagent", resource: "*",       effect: deny }  # 明確禁止派生
- { action: "read",    resource: "*",       effect: allow } # 放寬：唯讀全部
- { action: "edit",    resource: "docs/**", effect: allow } # 最窄：只寫 docs/**
```

### coder

```yaml
- { action: "*",        resource: "*", effect: deny }  # 最寬：全部拒絕
- { action: "subagent",  resource: "*", effect: deny }  # 明確禁止派生
- { action: "shell",     resource: "*", effect: ask  }  # 例外：shell 需確認
- { action: "read",      resource: "*", effect: allow } # 放寬：讀取
- { action: "edit",      resource: "*", effect: allow } # 放寬：編輯程式碼
```

### tester

```yaml
- { action: "*",        resource: "*",        effect: deny }  # 最寬：全部拒絕
- { action: "subagent",  resource: "*",        effect: deny }  # 明確禁止派生
- { action: "read",      resource: "*",        effect: allow } # 放寬：讀取
- { action: "shell",     resource: "*",        effect: allow } # 放寬：執行 pytest
- { action: "edit",      resource: "tests/**", effect: allow } # 最窄：只寫 tests/**
```

### reviewer

```yaml
- { action: "*",        resource: "*", effect: deny }  # 最寬：全部拒絕
- { action: "edit",      resource: "*", effect: deny }  # 明確禁止修改
- { action: "shell",     resource: "*", effect: deny }  # 明確禁止 shell
- { action: "subagent",  resource: "*", effect: deny }  # 明確禁止派生
- { action: "read",      resource: "*", effect: allow } # 唯一例外：唯讀
```

### orchestrator

```yaml
- { action: "*",       resource: "*",         effect: deny }  # 最寬：不碰檔案/不執行
- { action: "read",     resource: "*",         effect: allow } # 唯讀掌握現況
- { action: "question", resource: "*",         effect: allow } # 可問使用者
- { action: "subagent", resource: "architect", effect: allow } # 白名單開始
- { action: "subagent", resource: "coder",     effect: allow }
- { action: "subagent", resource: "tester",    effect: allow }
- { action: "subagent", resource: "reviewer",  effect: allow } # 最窄：特定 agent ID
```

## 使用方式

在 OpenCode 中直接對主代理下指令，例如：

```text
依照團隊流程，先請 architect 產出 FastAPI 規格，再交給 coder 實作，
完成後讓 tester 跑 pytest，最後請 reviewer 審查。
```

也可以個別指定：

```text
Use the reviewer subagent to review my current changes.
```

## API 使用說明與啟動指令

### 環境需求

- Python 3.9 以上（本機驗證版本：3.9.13）
- 相依套件已列於 `requirements.txt`

### 安裝與啟動（Windows / PowerShell）

```powershell
# 1. 建立虛擬環境（若已存在可略過）
python -m venv .venv

# 2. 安裝相依套件
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. 啟動 API 伺服器
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

啟動後可用網址：

| 網址 | 說明 |
| --- | --- |
| <http://127.0.0.1:8000/> | **WebXR / Three.js 首頁**，即時顯示 `/objects` 中的 3D 物件 |
| <http://127.0.0.1:8000/docs> | FastAPI 自動產生的 Swagger 互動文件 |
| <http://127.0.0.1:8000/health> | 健康檢查，回 `{"status": "ok"}` |

> Linux / macOS 請把 `.\.venv\Scripts\python.exe` 換成 `.venv/bin/python`。

### 執行測試

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

目前成果：**36 passed**（含 CRUD、驗證錯誤、404、NaN/Infinity、超大整數等案例）。

### API 端點總表

| Method | Path | 成功狀態 | 說明 |
| --- | --- | :---: | --- |
| `GET` | `/` | 200 | WebXR / Three.js 3D 檢視首頁（HTML） |
| `GET` | `/health` | 200 | 健康檢查 |
| `GET` | `/objects` | 200 | 列出所有物件，依 `id` 升冪；可用 `?name=xxx` 模糊比對 |
| `GET` | `/objects/{id}` | 200 | 取得單一物件 |
| `POST` | `/objects` | 201 | 新增物件，`id` 由伺服器產生 |
| `PUT` | `/objects/{id}` | 200 | 全量更新物件（五個可寫欄位都要送） |
| `DELETE` | `/objects/{id}` | 204 | 刪除物件（回應無內容） |

失敗狀態：`404`（找不到物件，`detail` 為 `"Object not found"`）、`422`（輸入驗證失敗）。

### 物件格式範例

`POST /objects` 的 request body（不可含 `id`）：

```json
{
  "name": "  chair  ",
  "model_url": "/models/chair.glb",
  "position": [1, 0, 2.5],
  "rotation": [0, 1.57, 0],
  "scale": [1, 1, 1]
}
```

回應（`name` 已 trim，整數正規化為浮點數）：

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

用 `curl` 新增一筆：

```powershell
curl -X POST http://127.0.0.1:8000/objects `
  -H "Content-Type: application/json" `
  -d '{"name":"chair","model_url":"/models/chair.glb","position":[1,0,2.5],"rotation":[0,1.57,0],"scale":[1,1,1]}'
```

### 欄位與驗證規則

| 欄位 | 型別 | 規則 |
| --- | --- | --- |
| `id` | `int` | 唯讀，由伺服器產生；客戶端送出即 422 |
| `name` | `str` | trim 後長度 1–100，不可為空 |
| `model_url` | `str` | 長度 1–500，須以 `http://`、`https://` 或 `/` 開頭 |
| `position` | `[x, y, z]` | 剛好 3 個有限數字，不接受字串、布林、NaN、Infinity |
| `rotation` | `[x, y, z]` | 同 position（弧度，可為任意有限值） |
| `scale` | `[x, y, z]` | 剛好 3 個有限數字，且每個都必須 `> 0` |

### WebXR 首頁操作

- 頁面每 3 秒輪詢 `/objects`，自動同步新增／更新／刪除的物件。
- 每個物件以彩色方塊表示，套用 API 的 `position`、`rotation`（弧度）、`scale`，上方 Sprite 顯示名稱。
- 滑鼠左鍵拖曳旋轉視角、滾輪縮放、右鍵拖曳平移。
- 若瀏覽器支援 WebXR 且環境為 HTTPS 或 localhost，右下角會出現 **VR Button** 可進入沉浸式模式。
- Three.js 由 CDN 載入，首次開啟需網路連線；API 本身不受影響。

更完整的規格（含資料流、錯誤格式、測試案例）請見 [`docs/spec.md`](docs/spec.md)。

## 注意事項

- `.opencode/opencode.jsonc` 將 `default_agent` 設為 `orchestrator`，新工作階段會由協調者起手；既有工作階段不會被強制切換。
- 內建的 `build` 代理仍存在且權限較寬。若要更嚴格的隔離，可在 `opencode.jsonc` 的 `agents` 中加入 `"build": { "disabled": true }`（犧牲直接使用 build 的便利性）。
- 路徑比對會正規化為 `/` 並在 Windows 上不分大小寫；`docs/**` 與 `tests/**` 已比對整個路徑。
- 若要放寬其他動作（例如讓 coder 能上網查文件），請在對應代理的規則**尾端**新增 `allow`，切勿放在 `deny` 之前，否則會被後面的規則覆蓋。
