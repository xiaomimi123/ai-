# 行政事业单位文档合规检查智能体

自研（不依赖 Dify）的文档合规协同检查系统。详见 `../行政事业单位文档合规检查智能体-自研技术开发文档.md`。

## 当前进度

**Phase 1（已完成）：单文件合规检查闭环** —— 解析 → 刚性校验 → RAG+LLM 柔性校验 → 问题台账 → 报告导出，已对「合同」类文档跑通并通过测试。

设计文档：`../docs/superpowers/specs/2026-05-31-phase1-single-file-check-design.md`

## 关键设计：离线可运行 + 生产可切换

所有外部重依赖均「接口 + 可降级实现」，默认零外部依赖即可运行测试，通过 `.env` 切换生产实现：

| 能力 | 离线默认 | 生产（.env 开启） |
|------|---------|------------------|
| 数据库 | SQLite | PostgreSQL（`DATABASE_URL`）|
| Embedding | 确定性 hash 向量 | bge-large-zh（`EMBEDDER=bge`）|
| 向量库 | 内存余弦 | Qdrant（`VECTOR_STORE=qdrant`）|
| LLM | 保守 stub | Claude（`LLM_PROVIDER=claude` + key）|

刚性规则不依赖任何外部服务，是确定性可测核心。

## 本地开发（不用 Docker，最快）

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt           # 或仅装测试所需子集
pytest                                     # 跑全部单元 + 端到端测试
uvicorn app.main:app --reload             # 启动 API，访问 http://localhost:8000/docs
```

默认走 SQLite + 内存向量库 + stub LLM，无需任何外部服务。

## Docker（全栈，对齐生产）

```bash
cp .env.example .env          # 填数据库密码、LLM key 等
docker compose up -d --build
docker compose exec backend python -m app.init_db
docker compose exec backend python -m app.rag.ingest --dir ./data/regulations
# 前端: http://localhost   API 文档: http://localhost:8000/docs
```

## API（Phase 1）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + 当前后端实现 |
| GET | `/api/templates` | 列出检查模板（7 套，Phase 1 仅合同就绪）|
| POST | `/api/documents` | 上传文档（multipart，带分类 metadata）|
| POST | `/api/checks` | 对文档执行模板检查 → 生成问题台账 |
| GET | `/api/checks/{id}` | 查看检查任务与台账 |
| GET | `/api/checks/{id}/report` | 导出 docx 检查报告 |

## 合同刚性规则（确定性，不调 LLM）

合同编号、签订日期、甲乙方主体、金额大小写一致性、必备条款（付款/违约/期限）、签章留痕。

## 后续阶段

- Phase 2：扩展 9 大分类 + 7 套模板
- Phase 3：跨文件联动校验引擎（招采链 / 财务链 / 报告链）+ Celery 异步
- Phase 4：前端 UI、协同复核、权限细分、批量处理
