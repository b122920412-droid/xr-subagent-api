# XR 場景物件管理 API — 資料庫方案比較報告

> 評估日期：2026-11-18
> 資料來源：3 個子代理**並行**評估回傳的統一 JSON（下方完整附上）
> 結論：**推薦方案一：SQLite + SQLAlchemy（9.0 / 10）**

---

## 一、評估情境與評分前提

三個子代理使用**完全相同的情境與評分尺度**，以確保分數可直接比較：

- **API 職責**：管理 XR 場景物件（id、名稱、類型、位置 x/y/z、旋轉、縮放、可見性、材質/資源路徑、時間戳），提供 CRUD、依類型/空間範圍查詢、批次更新與最終狀態持久化。
- **規模**：單機／小隊開發，約數千至數萬筆；讀多寫少，偶有批次位置更新。
- **最高優先**：本地開發與自動化測試方便、**無需外部服務**、**pip install + 一指令啟動**、方便繳交與重現。
- **次要需求**：型別安全、查詢能力、未來可擴充性與並發處理。
- **評分尺度**：1–10 浮點數，代表「在上述情境下的整體適用性」。

---

## 二、子代理回傳的 JSON（已統一格式與欄位順序）

### 方案一：SQLite + SQLAlchemy

```json
{
  "方案編號": 1,
  "方案名稱": "方案一：SQLite + SQLAlchemy",
  "資料庫": "SQLite",
  "存取層": "SQLAlchemy",
  "優點": [
    "嵌入式、零外部服務：資料庫即單一檔案，無需安裝或管理獨立資料庫伺服器，完全符合「無需外部服務即可執行」要求。",
    "部署與繳交極簡單：pip install fastapi uvicorn sqlalchemy alembic 後一指令即可啟動，可把 schema 初始化寫進啟動流程，繳交程式（加選配 .db 檔）即可重現。",
    "測試便利性高：可用 sqlite:///:memory: 或 pytest tmp_path 暫存檔建立彼此隔離的 fixture，速度快、無須清理外部服務或重置狀態。",
    "與 Python/FastAPI/Pydantic 整合成熟：SQLAlchemy 2.0 型別化 ORM（Mapped/mapped_column）搭配 Pydantic v2 的 from_attributes 可無縫做型別驗證與序列化。",
    "Alembic 遷移支援完整：可自動產生遷移腳本、版本控管 schema，適合迭代開發與最終狀態持久化。"
  ],
  "缺點": [
    "寫入為單一寫者鎖：所有寫入被序列化，批次更新或大量寫入時會阻塞其他寫入，高並發寫入能力有限。",
    "無原生空間索引／幾何查詢：沒有 PostGIS 類功能，空間範圍查詢需自行對 x/y/z 做 BETWEEN 搭配複合索引，或另用 rtree 虛擬表；距離／鄰近等進階查詢較麻煩。",
    "水平擴充受限：單機檔案資料庫無法被多實例共享，若未來需多台服務或高並發寫入必須遷移到 PostgreSQL 等。",
    "非同步整合需留意：FastAPI async 端點搭配同步 SQLAlchemy 需放進執行緒池，或改用 aiosqlite，增加相依與心智負擔。",
    "SQLite 的 ALTER TABLE 支援有限，Alembic 部分 schema 變更需用 batch 模式重建表。",
    "跨網路檔案系統（NFS）檔案鎖定不可靠，不適合分散式部署；大量批次更新若未分批或未用 bulk 操作，可能長時間持有寫鎖。"
  ],
  "效能評估": "在數千至數萬筆、讀多寫少的 XR 物件場景下，搭配適當索引（id、type、timestamp 及 x/y/z 複合索引）與 WAL 模式，單點查詢與依類型／包圍盒的範圍查詢通常為亞毫秒至數毫秒。寫入因單一寫者鎖而序列化，但本情境寫少故影響有限。批次位置更新應使用 SQLAlchemy Core update 或 bulk_update_mappings 並包在單一交易中，數萬筆更新約在數十毫秒至數秒完成，應避免 ORM 逐筆 flush。JSON1 可用於材質／資源等半結構化欄位查詢。整體效能對本作業規模充足，瓶頸主要出現在高並發寫入與真實幾何／空間查詢，而非一般 CRUD 與範圍過濾。",
  "部署複雜度": "低",
  "部署複雜度說明": "嵌入式資料庫，無需安裝、設定或維運獨立伺服器；相依套件僅 fastapi/uvicorn/sqlalchemy（加上 alembic/pydantic），可 pip install -r requirements.txt 後以單一指令（如 uvicorn main:app，或 python run.py 先初始化 DB 再啟動）完成。Schema 可用 create_all 或 alembic upgrade head 建立，設定檔與選配預先建立的 .db 檔一併繳交即可重現。僅需確認執行環境有寫入權限且 SQLite 版本支援 JSON1/rtree。",
  "適用場景": [
    "本地開發與自動化測試（in-memory DB、pytest fixture）",
    "單機／小隊協作、原型驗證與作業繳交",
    "讀多寫少、偶發批次位置更新的中小型 XR 場景物件管理",
    "需要型別安全 ORM 與資料庫遷移的 Python/FastAPI 專案",
    "CI/CD 中要求零外部服務、快速重現的整合測試"
  ],
  "推薦分數": 9.0,
  "評分理由": "在本作業以本地開發、自動化測試與一鍵繳交重現為最高優先的前提下，SQLite + SQLAlchemy 幾乎完美命中：零外部服務、單檔資料庫、in-memory 測試、成熟的 ORM/Alembic 與 Pydantic 整合，且對數萬筆讀多寫少的 XR 物件查詢效能充裕。扣分的部分主要來自單一寫者鎖的並發寫入限制、缺乏原生空間索引／幾何查詢，以及未來多實例擴充需遷移；但這些都屬次要需求，且可透過 WAL、複合索引／rtree、bulk update 緩解，故給予 9.0 的高推薦分數。"
}
```

### 方案二：PostgreSQL + AsyncPG

```json
{
  "方案編號": 2,
  "方案名稱": "方案二：PostgreSQL + AsyncPG",
  "資料庫": "PostgreSQL",
  "存取層": "AsyncPG",
  "優點": [
    "AsyncPG 是專為 Python asyncio 設計的原生非同步驅動，採用二進位協定與 prepared statement，吞吐量與延遲明顯優於同步驅動，能直接搭配 FastAPI 的 async endpoint 與 SQLAlchemy 2.0 async engine，避免阻塞事件迴圈。",
    "SQL 功能完整且型別系統強大：JSONB 可存放材質／資源路徑與任意 metadata 並用 GIN 索引查詢，另支援列舉、陣列、CHECK/FK/NOT NULL 等完整性約束，有利於 XR 物件結構的型別安全。",
    "PostGIS + GiST/SP-GiST 空間索引可對 x/y/z 位置提供真正的 2D/3D 空間語意，有效率地處理 bounding box、半徑、距離等空間 range 查詢，是其他輕量方案難以比擬的優勢。",
    "MVCC 成熟，讀不阻塞寫、寫不阻塞讀，適合讀多寫少且偶有批次更新的負載；交易、隔離層級與崩潰回復可靠。",
    "批次更新效率高：大量資料可用 COPY，中等批量可用 execute_values/executemany 搭配單一交易，比逐筆 UPDATE 快一個數量級以上。",
    "可擴充性強：未來可加讀取副本、資料表分區、pgbouncer/asyncpg 連線池，搭配 Alembic 做 schema 遷移，便於長期演進。",
    "最終狀態持久化可靠，適合需要正式維運與多人協作的場景。"
  ],
  "缺點": [
    "需要獨立執行的 PostgreSQL 伺服器或 Docker 容器，與本作業「無需外部服務、pip install + 一指令啟動」的最高優先需求直接衝突，繳交與重現需額外文件與 docker-compose。",
    "測試需要真實 DB（test container 或獨立測試資料庫），CI 必須安裝並啟動 PostgreSQL，測試隔離（transaction rollback、truncate、database per test）較繁瑣且速度較慢。",
    "維運成本較高：版本升級、備份還原、連線數調校、權限與磁碟管理都需處理；asyncpg 連線池設定不當易耗盡連線。",
    "AsyncPG 只能連 PostgreSQL，與特定資料庫綁定較深，日後想換回 SQLite/嵌入式方案需重寫存取層。",
    "對數千至數萬筆的單機／小隊規模而言明顯 overkill，啟動延遲、記憶體與程序占用都高於 SQLite 類方案，反而拖慢本地開發與自動化測試。",
    "非同步程式設計心智負擔較高，忘記 await、連線生命週期管理不當會產生難以除錯的問題；PostGIS 還增加額外安裝依賴（延伸套件）。",
    "批次更新會產生 dead tuples，需適當 VACUUM/ANALYZE 與索引維護，否則長期效能會下降。"
  ],
  "效能評估": "在 query 層面，AsyncPG 單連線吞吐高、延遲低，主鍵或索引查詢數萬筆資料可在毫秒級完成；讀多寫少負載配合 MVCC，讀取不會被寫入阻塞。批次位置更新方面，COPY 在大量資料時最快，execute_values/executemany 搭配單一交易次之，皆遠優於逐筆更新；空間 range 查詢若有 GiST 索引可維持近似 O(log n)，無索引則退化為全表掃描，必須針對位置欄位或 PostGIS geography 欄位建立索引。瓶頸在本情境下往往不是查詢本身，而是資料庫程序啟動、連線建立與容器額外開銷；相較嵌入式方案，整體起步成本偏高，但尖峰吞吐、並發與擴充上限最高。",
  "部署複雜度": "中",
  "部署複雜度說明": "需額外運行 PostgreSQL 服務：本機可用 Docker/docker-compose 一鍵啟動，或安裝本機 PostgreSQL，無法像 SQLite 單檔直接開箱。若允許 Docker 並提供 compose 檔，部署可控但仍需管理容器、資料卷、連線字串與測試用資料庫；若不允許容器或要求純 pip install 即可執行，則複雜度會升到高。相較之下，它換來的是最接近正式環境的行為與最強的查詢／空間能力。",
  "適用場景": [
    "需要真正空間查詢（範圍、距離、bounding box、3D 位置）並願意導入 PostGIS 的 XR 應用",
    "重視型別安全、SQL 查詢能力、JSONB 彈性 schema 與長期可擴充性的專案",
    "有多人協作、並發讀寫、可靠交易與正式／生產部署需求的系統",
    "CI/CD 已具備 Docker 或 test container 基礎設施，能接受真實 DB 測試",
    "資料量持續成長、需要讀取副本、分區或複雜分析查詢的場景"
  ],
  "推薦分數": 6.3,
  "評分理由": "PostgreSQL + AsyncPG 在效能、型別安全、JSONB/PostGIS 空間查詢、批次更新與 MVCC 並發上都是三大方案中能力最完整、最適合未來擴充的選擇，AsyncPG 與 FastAPI/SQLAlchemy async 的整合也相當成熟。然而本作業以本地開發、自動化測試與「pip install + 一指令啟動、無外部服務」的繳交重現為最高優先，PostgreSQL 必須額外啟動伺服器或容器、測試需真實 DB，啟動與維運成本明顯高出輕量嵌入式方案；對數千至數萬筆的讀多寫少小規模而言效益不成比例。因此授予中等偏上的分數：能力頂尖但與本情境的首要目標部分衝突，適合願接受 Docker 與測試容器成本的團隊，而非純繳交導向的最短路徑。"
}
```

### 方案三：MongoDB + Motor

```json
{
  "方案編號": 3,
  "方案名稱": "方案三：MongoDB + Motor",
  "資料庫": "MongoDB",
  "存取層": "Motor",
  "優點": [
    "文件模型與 FastAPI/Pydantic 高度對應：transform（position/rotation/scale）、material/resource 可直接巢狀內嵌，讀寫幾乎不需要 ORM 映射，id 可用自訂字串或 ObjectId 轉 str。",
    "Motor 原生 async/await，與 FastAPI async endpoint 無縫整合，DB I/O 不阻塞 event loop，讀多寫少的 API 吞吐與延遲表現好。",
    "彈性 schema：XR 物件類型異質、欄位常增減（不同 type 有不同屬性），不需預先定義嚴格 table，適合原型迭代；型別安全可由 Pydantic 在應用層補足。",
    "原生 2dsphere 索引與 $near/$geoWithin 查詢，對 XR 的「附近物件」「半徑／視錐範圍」空間查詢是直接可用的殺手級功能，數萬筆下效率極佳。",
    "bulk_write 支援批次位置更新，單次 round-trip 完成大量 update/upsert，比逐筆寫入快一個數量級，符合偶發批次更新情境。",
    "索引策略多元：{type:1}、{position:'2dsphere'}、{timestamp:1}、TTL 自動過期；可建複合索引 {type:1, position:'2dsphere'} 同時過濾類型與空間。",
    "並發與擴充性成熟：replica set 容錯、需要時可用多文件 ACID transaction、未來可 sharding，次要需求中的可擴充性與並發處理最強。",
    "生態系與文件豐富，Motor + FastAPI 整合範例多，長期維護與技術債風險低。"
  ],
  "缺點": [
    "需要獨立伺服器：必須另外跑 mongod 或 Docker 容器，無法單靠 pip install + 一指令啟動，直接抵觸「無需外部服務即可執行」與繳交重現的核心要求。",
    "維運成本較高：需處理 server 啟動、healthcheck、資料 volume 持久化、連線字串、版本相容；相較嵌入式方案多一個 process 要管理。",
    "型別安全較弱：schemaless 需仰賴 Pydantic 在寫入前驗證，否則易出現欄位不一致；ObjectId 序列化需額外轉 str。",
    "測試便利性受限：mongomock 為純 Python 可免伺服器，但對 2dsphere/$near、transaction、部分 aggregation 支援不完整；testcontainers 則要求 CI／開發機安裝 Docker。",
    "資源較重：mongod 本身佔用記憶體與磁碟，對「數千至數萬筆」的單機小隊規模而言優勢用不到，有殺雞用牛刀之感。",
    "一致性取捨：單文件原子性夠用，但跨文件批次更新若要 ACID 需 replica set + session transaction，增加複雜度與延遲，與讀多寫少最大吞吐目標略有衝突。",
    "最終狀態持久化雖可靠，但若用 mongomock 當測試／展示 backend 則為記憶體狀態，重啟即消失，不能當作真實持久化方案。"
  ],
  "效能評估": "讀多寫少的數萬筆情境下效能不是瓶頸：索引命中查詢接近 O(log n)，2dsphere $near 以 geohash/B-tree 實作，空間範圍查詢飛快；bulk_write 讓批次位置更新只需一次網路往返，穩定且可預期；Motor 非同步不阻塞 event loop，並發連線由連線池管理。主要瓶頸反而來自 mongod 本身的記憶體／磁碟 I/O、無索引的全表掃描、以及 transaction 的額外開銷。整體而言效能遠超需求，但多得一個伺服器的啟動延遲與資源消耗。",
  "部署複雜度": "中",
  "部署複雜度說明": "pip install motor 很簡單，但必須另外安裝並啟動 MongoDB server（本機 mongod 或 docker run mongo），並管理資料 volume、連線與健康檢查；繳交需附 docker-compose.yml 與操作說明，無法真正做到「pip install + 一指令啟動」。若改用 mongomock_motor 可勉強達成免伺服器測試，但缺乏持久化與完整 geo/transaction 支援，僅適合測試而非正式持久化。",
  "適用場景": [
    "需要真實地理空間查詢（$near / $geoWithin）的 XR 場景，例如依玩家位置即時找出附近物件。",
    "物件結構異質、欄位頻繁變動的原型開發階段。",
    "開發／評審環境已具備 Docker 或標準 CI 流程，可接受容器化啟動。",
    "FastAPI async 服務，重視 event loop 不被 DB I/O 阻塞。",
    "未來預期擴充到分散式、高並發、多文件格式或需要交易的長期專案。"
  ],
  "推薦分數": 6.0,
  "評分理由": "技術契合度很高：async Motor 與 FastAPI/Pydantic 無縫整合、文件即 API 模型、transform/material 可內嵌、2dsphere $near 對 XR 空間查詢價值明確、bulk_write 處理批次更新、讀寫效能對數萬筆綽綽有餘，次要需求（查詢力、擴充性、並發）表現最好。但在本作業「本地開發／測試／繳交優先、無需外部服務、pip install + 一指令啟動」的核心前提下，MongoDB 必須額外啟動 mongod 或 Docker，測試還得在 mongomock 與 testcontainer 之間取捨，重現與繳交摩擦明顯大於嵌入式方案。因此整體適用性給 6.0；若評審環境保證 Docker 可用且特別重視地理空間查詢，可調升至 7 分以上。"
}
```

> 註：子代理回傳內容已做格式正規化（欄位順序一致、移除多餘佔位鍵、修正少許中英混排贅字），論點與分數均未改動。

---

## 三、面向比較表

| 比較構面 | 方案一 SQLite + SQLAlchemy | 方案二 PostgreSQL + AsyncPG | 方案三 MongoDB + Motor |
| --- | --- | --- | --- |
| **推薦分數** | **9.0（第 1）** | 6.3（第 2） | 6.0（第 3） |
| 部署複雜度 | **低**（單檔、零服務） | 中（需 server／Docker） | 中（需 mongod／Docker） |
| 一指令啟動／pip install 即可 | **✅ 完全符合** | ❌ 需額外服務 | ❌ 需額外服務 |
| 本地開發與測試便利 | **✅ in-memory／tmp_path，最快** | ⚠️ 需真實 DB／test container | ⚠️ mongomock 功能不全或需容器 |
| 繳交與重現性 | **✅ 極高** | ⚠️ 需 compose + 說明 | ⚠️ 需 compose + 說明 |
| 讀寫效能（數萬筆、讀多寫少） | 充足（亞毫秒～數毫秒） | 最高（非同步 + MVCC） | 很高（非同步 + 索引） |
| 批次位置更新 | ✅ bulk_update_mappings + WAL | ✅ COPY／execute_values | ✅ bulk_write（單次往返） |
| 空間／範圍查詢 | ⚠️ 自行用 x/y/z 複合索引或 rtree | ✅ PostGIS GiST（最強） | ✅ 2dsphere $near（直觀） |
| 型別安全／驗證 | ✅ SQLAlchemy 2.0 + Pydantic | ✅ JSONB + 約束 + Pydantic | ⚠️ schemaless，靠 Pydantic 補 |
| 並發寫入 | ⚠️ 單一寫者鎖 | ✅ MVCC | ✅ replica set／transaction |
| 長期可擴充性 | ❌ 單機為主，需遷移 | ✅ 最強（副本、分區） | ✅ 強（sharding） |
| 與 FastAPI 整合 | 成熟（sync 執行緒池／aiosqlite） | 成熟（原生 async） | 成熟（原生 async） |
| 最主要風險 | 並發寫入與進階空間查詢 | 啟動／維運成本與 overkill | 外部服務依賴與 schemaless |

---

## 四、排序比較表

| 排名 | 方案 | 分數 | 部署複雜度 | 核心優勢 | 致命傷（在本情境） | 判定 |
| :---: | --- | :---: | :---: | --- | --- | --- |
| **1** | **SQLite + SQLAlchemy** | **9.0** | 低 | 零外部服務、單檔、in-memory 測試、Alembic 成熟 | 單一寫者鎖、無原生空間索引 | ✅ **推薦採用** |
| 2 | PostgreSQL + AsyncPG | 6.3 | 中 | AsyncPG 高效能、JSONB/PostGIS、MVCC、可擴充最強 | 必須額外啟動服務，與繳交重現優先衝突 | ⭕ 保留為未來升級路徑 |
| 3 | MongoDB + Motor | 6.0 | 中 | 文件即模型、2dsphere $near、異質 schema、bulk_write | 必須跑 mongod，測試需 mongomock／容器取捨 | ⭕ 僅在重視空間查詢且環境有 Docker 時考慮 |

---

## 五、最終選擇與理由

### ✅ 推薦選擇：**方案一 — SQLite + SQLAlchemy**

理由如下：

1. **完全命中最高優先需求**：SQLite 是嵌入式單檔資料庫，無需安裝、設定或維運任何外部服務；`pip install -r requirements.txt` 後一指令即可啟動，完全符合「無需外部服務、方便本地測試與繳交」的作業要求。PostgreSQL 與 MongoDB 都必須額外跑伺服器或容器，直接與此要求衝突。
2. **測試成本最低**：可用 `sqlite:///:memory:` 或 pytest `tmp_path` 建立彼此隔離的 fixture，無須清理外部狀態或重置資料庫，CI 也最快、最穩定。
3. **效能對本規模已充足**：數千至數萬筆、讀多寫少的 XR 物件場景，搭配 id/type/timestamp 與 x/y/z 複合索引或 rtree，查詢可達亞毫秒至數毫秒；批次更新用 `bulk_update_mappings` 包在單一交易即可。潛在瓶頸（單一寫者鎖）在「寫少」前提下影響有限。
4. **工程成熟度與型別安全**：SQLAlchemy 2.0 的 `Mapped` / `mapped_column` 搭配 Pydantic v2 `from_attributes`，再加上 Alembic 遷移，足以兼顧開發效率與 schema 演進。
5. **繳交與重現性最佳**：繳交時附上程式、requirements、Alembic 遷移與選配的 `.db` 檔即可重現，評審/test container 環境不必安裝 PostgreSQL 或 MongoDB。
6. **缺點皆為次要且可緩解**：單一寫者鎖可用 WAL + 批次交易緩解；缺乏原生空間索引可用 x/y/z 複合索引、rtree 或 JSON1 因應；若未來真的需要高並發或 PostGIS，再遷移到方案二，SQLAlchemy 抽象層可降低替換成本。

### 何時改選其他方案（給評審的補充判斷）

- 若**必須做真實 3D 幾何／半徑查詢且已有 Docker/CI 基礎設施** → 可改選 PostgreSQL + PostGIS（方案二）。
- 若**物件結構高度異質、頻繁增減欄位，且特別重視 `$near` 地理查詢與 Docker 環境** → 可考慮 MongoDB + Motor（方案三）。

### 方案三子代理額外提供的風險與緩解（摘錄）

- 外部 mongod／Docker 抵觸免服務要求 → 附 `docker-compose.yml`；CI 用 testcontainers；mongomock 僅供測試且明確標示不具持久化。
- mongomock 不完整支援 `2dsphere/$near`／transaction → 空間與交易整合測試改用真實 MongoDB，或以 `$geoWithin` + 手動距離計算替代。
- schemaless 欄位不一致 → 所有寫入強制通過單一 Pydantic model，type 用 Enum，id 統一轉 str。
- 批次更新部分失敗 → 用 `ordered=False` 的 `bulk_write` 並檢查 `BulkWriteError.writeErrors`；需全有全無才用 transaction。
- 單機資源／啟動成本過高 → 限制 wiredTiger 快取、用輕量 image、不啟用 sharding，僅用單節點。

---

## 六、建議實作要點（若採用推薦方案）

- 啟用 `PRAGMA journal_mode=WAL`、`foreign_keys=ON`、`busy_timeout`。
- 建立索引：`id`（PK）、`type`、`timestamp`，以及 `(x, y, z)` 複合索引；包圍盒查詢用 `BETWEEN`。
- 批次位置更新用 SQLAlchemy Core `update` 或 `bulk_update_mappings`，避免 ORM 逐筆 flush。
- 材質／資源路徑等半結構化欄位可用 SQLite JSON1（`JSON_EXTRACT`）+ 運算式索引。
- 測試用 `StaticPool` + `check_same_thread=False` 的 in-memory engine，搭配 pytest fixture 隔離。
- 需要 async endpoint 不阻塞時，可改掛 `aiosqlite` 的 async engine；仍維持同一 SQLAlchemy 抽象。
