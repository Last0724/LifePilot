# LifePilot — `ui/mechanisms.py` 只读审计报告

- **审计对象**: `ui/mechanisms.py`（244 行）
- **所在分支/提交**: `feature/frontend` @ `5ae95fd`
- **审计方式**: 只读。未修改任何功能，未合并任何分支，未新建任何实现。
- **角色**: Frontend owner / 集成协调（本报告供对比 A / DSH 现有模块时使用）

---

## 0. 总体架构

### 入口点与 Dashboard 集成钩子

```
app.py ──▶ ui.preview.main()
              ├─ _after_calendar(view)                      ← 由 render_dashboard(..., after_calendar=...) 回调
              │     ├─ observe_calendar(MECHANISM_KEY, view == "Week")
              │     └─ 若 view == "Week": render_mechanisms(SCHEDULE_KEY, MECHANISM_KEY, DEMO_START)
              ├─ 任务编辑保存路径: record_task_updates(before, updated, MECHANISM_KEY)
              └─ 生成新计划时: reset_plan_mechanisms(MECHANISM_KEY)
```

具体接线位置（`ui/preview.py`）：

| 钩子 | 位置 | 作用 |
|---|---|---|
| `observe_calendar` | preview.py:65,69（`_after_calendar`） | 每次进入周视图使 `visits += 1`，驱动模板轮换 |
| `render_mechanisms` | preview.py:71 | 周视图下渲染三列机制卡片 |
| `reset_plan_mechanisms` | preview.py:82（`_show_plan`） | 新计划生成时重置轮次/计时器/undo |
| `record_task_updates` | preview.py:174 | 任务编辑保存时结算模拟分数与排名 |

### 状态管理

全部在 `st.session_state[f"{key}_mechanisms"]`（浏览器会话级，无持久化）：

```python
{"score": 784, "rank": 12_847, "round": 0, "tip_since": monotonic(),
 "visits": 0, "was_week": False, "undo": None, "notice": ""}
```

另有临时闪光消息 `st.session_state[f"{key}_flash"]`，渲染后弹出即消费（pop）。

### 数据真实度

**全部为模拟/硬编码**，无后端、无网络、无持久化。唯一“真实”输入是用户日历（`st.session_state[schedule_key]`）——机制 1 会真实修改它（需用户逐项确认）。

### 对其他 UI 组件的依赖

| 依赖 | 用途 |
|---|---|
| `ui.calendar_input.first_overlap` | 判断时间段冲突（机制 1、2 共用） |
| `ui.components.apply_theme` 的 CSS | `.lp-mechanism-kicker/title/copy`、`.lp-rankings`、`.lp-demo-anchor` 样式 |
| `ui.planner` 的任务 dict 结构 | `id/date/title/start/end/completed/is_fixed/category`（"HH:MM" 字符串时间） |
| `streamlit`（`st.dialog`、`st.fragment(run_every=...)`、`st.html`） | 弹窗与定时刷新 |
| 标准库 `html.escape`、`time.monotonic`、`uuid.uuid4`、`datetime.date` | — |

---

## 1. 机制一：Endless Optimization（无尽优化）

### 入口与流程

1. 周视图出现三列卡片，第一列为优化卡；`st.fragment(run_every="25s")` 每 25 秒自动刷新一次提示
2. 点 **Review optimization** → `@st.dialog` 打开 `_optimization_dialog`
3. 弹窗列出本轮拟改动（最多 6 项），每项一个 checkbox
4. 点 **Apply changes** → 必须**全部勾选**才生效；未全选则报错并停在弹窗
5. 生效后：`round += 1`、`score += 3`、flash "AI found another +X% improvement"

### 25 秒刷新

- `TIP_INTERVAL = 25`（秒）
- `_optimization_signal` 是 `st.fragment(run_every=f"{TIP_INTERVAL}s")`——每 25 秒客户端自动重渲染该片段，提示永不消失
- `_gain()` 中的 `elapsed = monotonic() // 25` 让百分比随“停留时长”轮换

### 潜在提升百分比

- 固定循环序列 `GAINS = (2, 3, 2.3, 2.7)`
- `gain = GAINS[(round + elapsed) % 4]` —— **不会递减、不会归零**，是循环出现的虚假数字（弹窗内标注 "Simulated estimate"）
- 与任务书里的 3.7% 示例不同：当前实现没有 3.7% 这个值

### 任务调整规则（`_propose`）

1. 按 `(date, start)` 排序
2. **跳过** `is_fixed` 与 `completed` 任务
3. 对每个可动任务依次尝试偏移 `(±5, ∓5, ±10, ∓10)` 分钟，奇偶轮次交替正负顺序
4. 新时段必须满足 `0 ≤ start < end < 1440` 且与所有任务不重叠（`first_overlap`）
5. **六次上限**：`len(changes) == 6` 立即停止 → 每轮最多提出 6 处修改

### 状态

`round`、`tip_since`、`score`（每轮 +3）。

### 已知局限

- 增益值循环不衰减，用户永远“还能再优化”，但数字不逼真（不递减）
- 只能平移时间段，不做真正的重排/合并
- “必须全选”制造摩擦，但没有跳过入口时容易被堵住——好在弹窗可关闭，日历主流程不受阻

---

## 2. 机制二：Guru Template Marketplace（大师模板）

### 入口与流程

1. 第二列卡片 "AI PICK · DEMO PROMOTION"，标题按 `visits` 轮换（每进一次周视图换一个）
2. 点 **View template** → `_template_dialog`
3. 弹窗：模板名 + 模拟价格 + 摘要 + 拟议日程块（3 段）
4. 计算“替换当天 N 个未完成且非固定任务、新增 M 个模板块（不与固定/已完成冲突）”
5. **Apply demo template** → 真实替换日历（被移除任务存入 `undo` 快照），flash 提示
6. 卡片出现 **Undo template** → 还原，除非发生时段冲突则拒绝还原

### 定价

硬编码 `TEMPLATES`（3 个）：¥199 / ¥299 / ¥149，对应声称增益 +300% / +500% / +220%。价格仅作为 caption 展示（"Demo price"），**没有支付环节**。

### Upsell 触发

- 唯一触发点是**访问轮换**：`_suggested_template = TEMPLATES[(max(1, visits)-1) % 3]`——用户每进周视图就换一个模板推销
- **没有** 62% 潜力提示、没有 premium 锁定、没有“解锁”动作；应用免费，价格纯装饰

### 完整模板市场是否存在？

**不存在。** 这是一个“每次一个模板”的轮播推销，不是目录/商店：无搜索、无分类、无已购记录、无档位限制。

### 状态

`visits`（轮换指针）、`undo`（最后一次应用的快照：被移除任务 + 新增 id 集合）。

### 已知局限

- `undo` 只有**单快照**，连续应用两个模板后只能还原最后一次
- 模板块只有 3 段、硬编码，无个性化
- 被移除任务只活在 `undo` 快照里，页面刷新即永久丢失

---

## 3. 机制三：Leaderboard（生产力榜）

### 入口与流程

1. 第三列卡片 "DAILY SCORE · SIMULATED"：显示 `score` 分、全球排名 `#rank`、距第一的分差
2. 点 **View leaderboard** → `_leaderboard_dialog`
3. 选范围（Global / Friends / Weekly）→ HTML 表格 3 行 + 你的分数行
4. **Simulate task completion** → `_reward(state, 1)`：`score += 12`、`rank += 17`，flash 提示
5. 完成真实任务（`record_task_updates`）也会触发同一套 `_reward` 结算

### 排名指标与分数计算

- 初始：`score = 784`，`rank = 12_847`
- 分数：完成一个非固定任务 +12（重开一个 -12），`score = max(0, …)`
- 排名：`rank = max(1, rank + 17 × (完成数 − 重开数))`
- Weekly 视图显示 `score − 680` 作为周分

> ⚠️ **注意一个反向设计**：排名数字是**变大**的（12,847 → 12,864），提示语写 "Your simulated global rank **fell** 17 places"——完成任务反而掉名次。这是刻意的 reverse-UX 幽默，但对比模块时需要明确：它不是正常的排名上升逻辑。

### 模拟数据

`RANKINGS` 硬编码三个范围、每个 3 名玩家（"Productivity Master"、"WorkHarder_24_7"、"Maya (demo)"…）。弹窗内明确标注 "Fictional players and simulated scores."

### 是否真实用户？

**否。** 无账号、无网络请求、无持久化，纯前端模拟。

### 已知局限

- 每榜仅 3 名对手，无历史曲线
- 排名不会随时间自然漂移，只随“模拟完成”或真实任务结算变化
- 名次变化方向是反向的（完成→掉名次），演示前需说明

---

## 4. 现有测试与实测结果

- **`ui/mechanisms.py` 本身没有任何测试**（`git grep -i mechanism tests/` 无命中）
- 仓库现有测试位于 `tests/`（同分支）：
  - `tests/guru.test.js` — 覆盖 `ui/experience/guru.js`（大师体验，与 mechanisms.py 不同模块）
  - `tests/experience.test.js` — 覆盖 `ui/experience/model.js`（XP/通知模型）
- **实测**（Node v24.21.0，feature/frontend 检出 @5ae95fd）：

```bash
node --test tests/guru.test.js tests/experience.test.js
# tests 13 · pass 13 · fail 0  (guru 6/6, experience 7/7)
```

- 备注：`node --test tests/`（目录参数）在该 Node 构建下报 `tests:1:1` 加载失败；显式列文件参数则全部通过
- Python 侧无测试框架；mechanisms.py 的 `first_overlap` 依赖在 JS 测试之外没有任何覆盖

---

## 5. 结论（供对比决策）

| | 机制一 优化 | 机制二 模板 | 机制三 排行榜 |
|---|---|---|---|
| 入口 | 周视图卡片 + 25s 定时片段 | 周视图卡片（轮换） | 周视图卡片 |
| 是否改动用户真实日历 | 是（逐项确认后） | 是（替换当天任务） | 否 |
| 数据 | 模拟（增益循环） | 硬编码 3 模板 | 硬编码 3×3 玩家 |
| 商业化动机 | 拉时长（反复优化） | 变现（价格只是摆设，无支付） | 留存（社交比较） |
| 完整性缺口 | 增益不衰减 | **没有完整市场**（仅轮播单品） | 排名方向反向、对手过少 |
| 测试 | 无 | 无 | 无 |

**本次审计未做任何修改。** A / DSH 的模块是否补充 `ui/mechanisms.py`，请对比后决定；如决定整合，建议优先补：模板市场的档位/解锁逻辑、排行榜的合理排名方向与对手数量、以及 mechanisms.py 的 Python 侧单元测试。
