# Phase 1 设计：单文件合规检查闭环

> 对应《行政事业单位文档合规检查智能体 自研技术开发文档 v1.0》第六章「第一阶段」。
> 范围：跑通一类文档（合同）的 解析 → 刚性校验 → RAG+LLM 柔性校验 → 问题台账 → 报告导出 闭环。

## 目标

交付一个**可本地运行、可单元测试**的后端，实现单份合同文档的完整检查闭环；同时搭好 §5 的项目骨架与 Docker 编排，为后续阶段（9 大分类 / 7 套模板 / 联动校验）预留扩展点。

## 架构分层（与开发文档 §1 一致）

- 应用服务层：FastAPI（`backend/app`）
- AI 能力层：RAG（`app/rag`）+ LLM 适配（`app/llm`）+ 规则引擎（`app/rules`）
- 数据层：SQLAlchemy（本地 SQLite / 生产 PostgreSQL）+ 向量库（Qdrant / 本地回退）+ 对象存储（本地目录 / MinIO）

## 可离线运行的关键设计

为保证「现在就能跑、能测」，外部重依赖全部走**接口 + 可降级实现**：

| 能力 | 生产实现（.env 开启） | 离线回退（默认） |
|------|----------------------|------------------|
| 数据库 | PostgreSQL（`DATABASE_URL`） | SQLite 文件 |
| Embedding | bge-large-zh（sentence-transformers） | 确定性 hash 向量（无需下载模型） |
| 向量库 | Qdrant | 内存 + numpy 余弦检索 |
| LLM | Claude（`ANTHROPIC_API_KEY`） | Stub（返回固定结构，便于测试管线） |
| 对象存储 | MinIO/OSS | 本地 `storage/` 目录 |

刚性规则**不依赖任何外部服务**，是 Phase 1 的确定性可测核心。

## 模块与接口

### parsers（统一入口 + 策略分发）
- `parse(path) -> ParsedDocument`，按扩展名分发到 docx/pdf/xlsx/txt 解析器。
- 统一输出（§3.2）：`{text, page_blocks:[{page,section,content}], tables, metadata}`。
- 位置信息（页码/章节）贯穿全流程，供问题定位。

### rules（规则引擎）
- `RigidRule`：确定性校验（正则/字段提取/一致性判断），返回 `Issue` 列表。
  - 合同刚性规则示例：合同编号是否存在、签订日期是否存在、甲乙方是否齐全、金额大小写一致性、签章/落款关键词是否缺失、必备条款（付款/违约/期限）是否缺失。
- `SoftRule`：组装 文档片段 + RAG 召回法规 → LLM 输出疑点。
- `CheckTemplate`：一套规则的集合（Phase 1 实现「合同全流程检查模板」）。
- 引擎遍历模板规则，汇总 `Issue`。

### rag
- `chunk_regulation(text)`：法规按「条款」切分，chunk 保留 法规名/条款号 metadata。
- `Embedder` 接口 + bge / stub 两实现。
- `VectorStore` 接口 + Qdrant / 内存 两实现，支持 metadata（category）过滤。
- `retrieve(query, category, top_k)`。

### llm
- `LLMClient` 接口：`complete(prompt)` / `extract_json(prompt, schema)`。
- Claude 实现 + Stub 实现。

### models（数据层）
- `Document`、`CheckTask`、`Issue`（§3.6 统一结构：疑点描述/资料位置/法规依据/问题类别/风险等级/整改建议）。

### api
- `POST /api/documents`（上传 + 解析）
- `POST /api/checks`（对文档跑模板检查 → 生成 Issue 台账）
- `GET /api/checks/{id}`（查看台账）
- `GET /api/checks/{id}/report`（导出 docx 报告）
- `GET /api/health`

## 数据流

上传文件 → 存对象存储 → 解析缓存 → 选模板 → 规则引擎（刚性确定性 + 柔性 LLM+RAG）→ 写 Issue 台账 → 按需导出 docx 报告。

## 错误处理

- 解析失败：记录错误、标注该文档「需人工」，不中断任务。
- LLM/向量库不可用：自动降级到 stub/内存实现，刚性规则结果不受影响。
- LLM 幻觉防护：prompt 强约束「只引用检索到的法规，不得编造条款」，结果定位为辅助、需人工复核。

## 测试策略

- 单元测试覆盖：刚性规则（金额大小写一致性、必备要素缺失）、解析输出结构、RAG 分块与检索（用 stub embedder）、台账生成。
- 端到端：用一份样本合同文本跑完 解析→刚性校验→台账，断言检出预置问题。

## 不在本阶段范围（YAGNI）

- 9 大分类全部模板（仅合同）
- 跨文件联动校验引擎（第三阶段）
- 前端完整 UI、协同/权限（仅留骨架目录）
- Celery 异步（Phase 1 同步执行，接口预留）
