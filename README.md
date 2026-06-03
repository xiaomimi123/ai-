# 内控评价合规审查智能体

行政事业单位 **内部控制评价报告核查** 的 AI 辅助系统。从被检查单位提交的材料里自动识别 54 项评价指标，按"评价指标 + 问题清单 + 法规库"三块黄金数据交叉核验，最终产出 Excel 工作底稿与 Word 核查报告。

---

## 核心能力

- **AI 阅读材料自动分类**：批量上传文件夹 → LLM 看内容把每份材料绑定到 54 项指标，实测命中率 **91-100%**
- **AI 阅卷打分**：对每条指标按「核查要点 + 扣分规则」给出核查后得分；规则引擎 + LLM 语义判断双路径
- **工作底稿在线编辑**：所见即所得编辑「核查后得分 / 调整说明 / 5 对材料判定」，blur 自动保存
- **状态机**：草稿（AI 生成）→ 复核中 → 已定稿（锁定为只读）
- **Word 报告 = 底稿**：定稿后导出报告会注入审计师的修订内容
- **法规库 RAG**：Qdrant 向量库存上位法/评价办法/编报指南，AI 核查时引用具体条款
- **5 大问题维度**：真实性 / 完整性 / 合规性 / 重复性 / 匹配性
- **疑点批量忽略**：按维度一键标记 "ignored"，避免逐条点击

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI · SQLAlchemy · Celery · python-docx · openpyxl |
| LLM | DeepSeek V4 Pro（OpenAI 兼容），可切换为 Claude；提供 stub 模式离线运行 |
| 向量库 | Qdrant |
| 数据库 | PostgreSQL（生产）/ SQLite（本地开发） |
| 任务队列 | Celery + Redis |
| 对象存储 | MinIO |
| 前端 | 原生 HTML + ES2020 + 自定义 CSS（无框架，可单文件部署） |
| 部署 | Docker Compose 7 服务一体编排 |

## 快速开始

```bash
# 1) 克隆
git clone https://github.com/xiaomimi123/ai-.git
cd ai-/compliance-agent

# 2) 配置 LLM API Key（可选，不配置走 stub 模式）
cp .env.example .env  # 编辑里面的 LLM_API_KEY

# 3) 一键启动
docker compose up -d

# 4) 初始化指标库
docker compose exec backend python -m app.seeds.load_indicators_55

# 5) 打开浏览器
open http://localhost:8000/
# 默认账号：admin / admin123（首次登录后请立刻改密码）
```

## 目录结构

```
compliance-agent/
├── backend/
│   ├── app/
│   │   ├── api/               # FastAPI 路由
│   │   ├── core/              # 配置 / 认证 / 权限
│   │   ├── engine/            # 核查引擎（rule + LLM + orchestrator）
│   │   ├── llm/               # DeepSeek / Claude / Stub 客户端
│   │   ├── models/            # SQLAlchemy 模型
│   │   ├── parsers/           # PDF / Word / Excel 解析
│   │   ├── rag/               # 向量库 + 嵌入
│   │   ├── seeds/             # 54 项指标 seed
│   │   ├── services/          # 业务服务（材料匹配 / 工作底稿 / 报告 / ...）
│   │   └── tasks/             # Celery 任务
│   └── tests/                 # pytest（74+ 测试覆盖）
├── frontend/                  # 静态前端（无构建步骤）
├── docs/                      # 设计文档
└── docker-compose.yml
```

## 使用流程

```
1. 上传被检查单位的材料文件夹 → AI 自动绑定到 54 项指标
   ↓
2. 触发 AI 核查（快速 / 精确两种模式）
   ↓
3. 自动生成工作底稿（54 项明细 + 5 对材料判定）
   ↓
4. 复核：在底稿表格里直接改"核查后得分""调整得分说明"，blur 自动保存
   ↓
5. 「完成复核，定稿」→ 锁定底稿为只读
   ↓
6. 导出 Word 报告（含审计师修订） + Excel 1:1 复刻底稿模板
```

## 评分规则

| 严重度 | 扣分系数 |
|---|---|
| 高风险 | 指标满分 × 50% |
| 中风险 | 指标满分 × 25% |
| 低风险 | 指标满分 × 10% |

复核状态权重：pending / confirmed = 100%，ignored = 0%，adjusted = 50%

等级阈值：**优 ≥ 90 / 良 ≥ 80 / 中 ≥ 60 / 差 < 60**

## 测试

```bash
cd backend
python -m pytest -q
# 74 passed
```

## 项目状态

- ✅ V1：基础核查 + 工作底稿生成
- ✅ V2：底稿在线编辑 + 定稿状态机 + 报告读底稿
- ✅ V3：54 项指标新模板 + Excel 表头智能识别 + 噪音减 80%
- 🚧 V4：多人协作锁 / 历史版本 / 监控面板

## License

仅供学习交流使用。
