# 内控评价智能审核系统

> 站在上级复核方视角，AI 拿着问题清单和法规，对被检查单位的内控评价报告与佐证材料逐项核查，出具核查报告。

详见 `../内控评价合规审查智能体-完整开发文档v3.md`。

## 核心能力

- **法规知识库**：上位法 / 评价办法 / 编报指南附件 1/2 / 高频问题
- **问题清单库**：客户提供的真实性+相关性核查清单，AI 的「考题」
- **AI 核查引擎**：刚性规则（公章/日期/年度）+ LLM 语义核查
- **5 大检查维度**：总体合规性 / 相关性 / 评分合规 / 复核规范 / 报告编报
- **协同复核流程**：AI 初核 → 审查员标注 → 报告下发 → 整改销号
- **4 角色权限**：超级管理员 / 审查员 / 被检查单位 / 只读用户

## 技术栈

| 层 | 组件 |
|---|---|
| 前端 | 单页 HTML + Vanilla JS + Tailwind CDN |
| 后端 | Python FastAPI + SQLAlchemy + Celery |
| LLM | **DeepSeek V4 Pro**（默认，1M 上下文，OpenAI 兼容）/ Claude（备选）/ stub（离线兜底）|
| RAG | Qdrant + bge-large-zh（生产）/ 内存余弦（离线）|
| 数据 | PostgreSQL + MinIO + Redis |

## 本地快速运行

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload    # http://localhost:8000/
```

## Docker 全栈部署

```bash
cp .env.example .env             # 编辑端口/密码
docker compose up -d --build
docker compose exec backend python -m app.init_db
# 默认登录 admin / admin123（首次部署后请尽快修改）
```

## LLM API Key 配置

两种方式（任一即可）：
1. **环境变量**：`.env` 设置 `LLM_API_KEY=sk-...`
2. **后台界面**：登录后进「系统设置」页填入 DeepSeek API Key（覆盖环境变量）

## 更新日志（部分）

- **v2.10（2026-07-12）**：材料审核子 tab 里"内容审核（每份材料关键要素与判定）"面板临时隐藏（`index.html` 里 card 加 `style="display:none"`；后端数据和 JS 渲染保留，下版本恢复只需删一处 style）
- **v2.9（2026-07-12）**：材料绑定页加即时搜索框（匹配文件名 + 已绑定指标 name/code）+ 文件名点击新 tab 打开预览。前端 fetch+blob 携带 Bearer token（SPA localStorage token + 新 tab 天然不带 auth 的规避方案），复用后端已有的 `GET /api/materials/{id}/preview` 端点。**部署后已打开的旧 tab 需要硬刷（Cmd+Shift+R）加载新 app.js。** 详见 `docs/superpowers/plans/2026-07-12-material-search-and-open.md`
- **v2.8（2026-07-12）**：`material_matcher` 加二级文件夹语义识别，识别"XX业务/岗位职责说明书"类路径 → 岗位分离指标（I-14/21/26/33/38/45），修复 v1.5 之后 fallback 到"制度"类的错绑；配套 `app/scripts/rebind_wrong_bindings_v28.py` 一次性 rebind 历史存量。详见 `docs/superpowers/plans/2026-07-12-*.md`
- 更早版本变更见 `docs/superpowers/plans/` / `docs/superpowers/specs/`
