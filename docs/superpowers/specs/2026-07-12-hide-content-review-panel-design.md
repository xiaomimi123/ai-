# 隐藏"内容审核"panel（v2.10）

**日期**：2026-07-12
**范围**：纯前端 CSS 隐藏（1 行改动）
**动机**：核查任务详情页 → 材料审核子 tab 里的"内容审核（每份材料的关键要素与判定）"面板暂时不展示。用户复审时觉得这一屏信息噪音大（AI 5 对维度 chip 一屏 6+ 条颜色标签），先隐掉，下版本可能改回。

## 目标

- "内容审核"card 从 UI 消失
- 代码（render 函数 + 后端 data 生成）完整保留，未来改回来只需删一处 `style="display:none"`
- 隐藏原因在 HTML 注释里写明白，防止将来重构时误删

## 非目标

- 不删 `renderMrContent` 函数（app.js:1014-1050）—— 保留是恢复用
- 不改后端 `material_review_service.py`—— `content_review` 数据继续生成，别的面板或未来 UI 可能用
- 不加 feature flag / 后台开关（YAGNI；恢复就是删一行 style）
- 不删调用点 `renderMrContent(data.content_review)`（app.js:927）—— display:none 不移除 tbody 元素，`getElementById` + `innerHTML` 照常工作，无需守卫

## 设计

### 改动 1：`compliance-agent/frontend/index.html:449-470`

在 card `<div>` 上加 `style="display:none"`，并在前面加中文 HTML 注释说明临时隐藏 + 恢复方法：

```html
<!-- v2.10: 内容审核 panel 临时隐藏（下版本可能改回，删下方 style="display:none" 即恢复）
     后端 data.content_review 仍生成、renderMrContent 仍执行；只是 UI 不可见。 -->
<div class="card mb-4" style="display:none">
  <div class="section-title">内容审核（每份材料的关键要素与判定）</div>
  ... (剩下不动)
</div>
```

### 改动 2：cache buster `?v=2.9` → `?v=2.10`

`index.html` 里所有 `?v=2.9` 引用改成 `?v=2.10`，让浏览器强刷时命中新 index.html。

### 改动 3：README 加更新日志

```markdown
- **v2.10（2026-07-12）**：材料审核子 tab 里"内容审核（每份材料关键要素与判定）"面板临时隐藏（`index.html` 里 card 加 `style="display:none"`；后端数据和 JS 渲染保留，下版本恢复只需删一处 style）
```

## 涉及文件

| 文件 | 变更 |
|---|---|
| `compliance-agent/frontend/index.html` | card 加 `style="display:none"` + HTML 注释；`?v=2.9` → `?v=2.10` |
| `compliance-agent/README.md` | 加 v2.10 更新日志一行 |

**注意**：本次不改 `app.js`（renderMrContent 不需要动，display:none 不影响 getElementById）。

## 部署

Workbench 拖 `index.html` 到 `/opt/audit/compliance-agent/frontend/`；浏览器 Cmd+Shift+R。

## 手工验证

- [ ] 硬刷后进任意任务 → 材料审核子 tab
- [ ] "内容审核（每份材料的关键要素与判定）"card 完全消失
- [ ] 其它 3 个 card（重复性检测 / 匹配情况 / 时间线）正常显示
- [ ] F12 Console 无 "Cannot set properties of null" 类报错
- [ ] F12 Elements 找到 `<div class="card mb-4" style="display:none">` 存在但不显示

## 回滚

删 `style="display:none"` 一处即可，或 `git revert` 该 commit。
