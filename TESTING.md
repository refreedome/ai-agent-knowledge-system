# 测试与评测文档（TESTING）

> 本文件说明本项目的**测试策略**与**评测体系**：怎么测、指标怎么算、结果在哪、CI 怎么门禁。
> 配套脚本：`tests/`（单元测试）、`evaluation/`（评测）、`.github/workflows/ci.yml`（CI）。

---

## 一、测试分层总览

| 层级 | 覆盖范围 | 工具 | 命令 | 需要 API Key |
|---|---|---|---|---|
| **单元测试** | 工具层 / 注册表 / 会话管理 / 混合检索 / RAG 链 | pytest + `unittest.mock` | `pytest tests/ -q` | ❌ 不需要（全 Mock，离线可跑） |
| **检索评测** | RAG 召回质量（Hit Rate@K） | 自研脚本 `evaluate_retrieval.py` | 见下 | local 模式不需要 / semantic·hybrid 需要 |
| **生成评测** | 忠实度、答案相关性 | RAGAS | `python evaluation/evaluate_ragas.py --sample 10` | ✅ 需要 |
| **服务健康** | 服务可用性 | FastAPI healthcheck | `curl http://localhost:8000/api/health` | ❌ |
| **权限回归** | 多用户隔离与角色权限 | 接口测试（见第五节） | 见下 | ❌ |
| **流式验证** | SSE 是否真·token 级流式 | `evaluation/stream_check.py` | `python evaluation/stream_check.py` | ✅ 需要 |

---

## 二、单元测试（42 个，全部离线可跑）

```bash
DASHSCOPE_API_KEY=sk-test-dummy pytest tests/ -q   # 占位 Key 即可，测试不发起真实调用
```

| 文件 | 覆盖内容 |
|---|---|
| `tests/test_agent.py` | `ToolResult`（成功/失败/序列化）、`ToolRegistry`（注册/权限判定/单例/重复注册）、`SessionManager`（创建/裁剪/TTL 过期/SQLite 恢复） |
| `tests/test_rag.py` | `HybridSearchService`（索引构建、空文档、关闭开关、BM25 不可用降级、RRF 融合排序、中文分词、增量添加）、`RagSummarizeService`（链式调用、检索层 Mock） |

**设计原则**：外部依赖（LLM、Embedding、向量库）**全部 Mock 隔离** —— 测试 2 秒内跑完、结果确定、无网络、无需真实密钥。

---

## 三、检索评测：Hit Rate@K

### 指标定义

```
Hit Rate@K = topK 分块中命中「期望关键词」的问题数 / 总问题数
命中判定  = 任一返回分块的正文包含该题的任一期望关键词
```

衡量的是**检索召回质量**——它是生成质量的上限（检索不到，模型再强也答不对）。

### 三种评测模式

| 模式 | 说明 | 用途 |
|---|---|---|
| `local` | 从 `data/knowledge_base` 原始文档直接解析 + 分块 + 建 BM25 索引 | **离线基线 / CI 回归**（不需要 Key） |
| `semantic` | 纯语义向量检索（走 ChromaDB + DashScope Embedding） | **混合检索的对照组（Baseline）** |
| `hybrid` | 线上真实链路：BM25 + 向量 + RRF 融合 | 线上效果验证 |

### 复现命令

```bash
# 离线（CI 可跑）
python evaluation/evaluate_retrieval.py --source local

# 基线 vs 混合，并生成 Markdown 报告
python evaluation/evaluate_retrieval.py --source all --report --show-miss
```

### 评测参数（与线上一致）

`top_k = 5`、`chunk_size = 200`、`chunk_overlap = 20`、`RRF k = 60`、`语义权重 = 0.5`。

---

## 四、实测结果

> 完整报告见 `evaluation/评测报告-HitRate@5.md`（脚本自动生成，含逐题明细）。

| 检索模式 | Hit Rate@5 | 相对基线 |
|---|---|---|
| 纯语义向量检索（Baseline） | **96.00%** | — |
| **混合检索（BM25 + 向量 + RRF）** | **98.00%** | **+2.0 个百分点** |
| 离线 BM25（CI 用） | 96.00% | +0.0 |

**未命中明细（改进线索）**：

- 通用未命中：`#21 扫地机器人的爬坡能力`（三模式都未命中 → 知识库对该主题覆盖不足）
- 仅语义未命中：`#28 机器人迷路到处乱转`（BM25 救回）
- 仅离线 BM25 未命中：`#32 保修期`（语义救回）

**结论**：两种检索各有所长——BM25 救回术语类查询，语义救回表述差异大的查询，融合后取并集收益。

---

## 五、权限回归测试（多用户隔离）

```bash
# 1) 普通用户越权查询他人会话 → 应 403
curl -H "X-User-Id: bob" "http://localhost:8000/api/sessions?user_id=alice"
# 2) 普通用户上传文档 → 应 403
curl -H "X-User-Id: alice" -F "file=@data/knowledge_base/维护保养.txt" \
     http://localhost:8000/api/upload/file
# 3) 管理员查询全部会话 → 应 200
curl -H "X-User-Id: admin" "http://localhost:8000/api/sessions"
```

用户与角色配置见 `config/users.yml`（`admin` / `alice` / `bob` / `guest`）。权限判定实现见 `utils/permission.py`。

---

## 六、CI 门禁

`.github/workflows/ci.yml`（push / PR 触发）：

1. **单元测试**：`pytest tests/ -q` —— **失败即阻断合并**（质量门禁）
2. **离线检索评测**：`python evaluation/evaluate_retrieval.py --source local` —— 信息性检查（`continue-on-error`，不阻断）
3. CI 中使用占位密钥（`sk-ci-dummy`），**严禁在 CI 配置真实密钥**

---

## 七、已知局限与改进方向（诚实清单）

1. **命中判定偏松**：用关键词包含判定，对 BM25 略有利。更严谨的做法是**人工标注每题的相关文档 ID**，用 NDCG@K / MRR 评估排序质量。
2. **测试集规模偏小**：50 题覆盖有限，应扩到 100-200 题并覆盖多轮对话、边界问法（口语化、错别字、超长问题）。
3. **RAGAS 未进 CI**：需要真实 Key 与 Token 成本，当前只作为人工触发的质量抽查。
4. **缺少多轮与会话级评测**：现有测试集均为单轮问答，多轮指代消解（「它呢？」）的效果未量化。
5. **权限测试未自动化**：目前是手工接口验证，应补成 pytest 用例进 CI。

---

## 八、流式输出验证（重要：防止「假流式」）

**为什么要专门测**：SSE 接口「能分块推」不等于「逐 token 流式」。我踩过的坑——接口确实是 SSE、确实在分块推，但**只有 2 个内容块、间隔 7 秒**，用户看到的是「一整块蹦出来」。

**根因有两个（都在配置层，不在前端）**：
1. `stream_mode="values"` 只在**节点结束时**吐完整快照，LLM 节点要等整段生成完才结束；
2. **`ChatTongyi` 默认 `streaming=False`**，模型层根本没走流式请求。

**修法**：① 多模式订阅 `stream_mode=["messages", "values"]`（`messages` 拿 token 增量、`values` 取最终答案）；② 模型工厂里显式 `ChatTongyi(..., streaming=True)`。

**验证方式（可复现）**：
```bash
python evaluation/stream_check.py
# 期望：chunk 数很多（几十~上百），到达间隔 30-200ms，每片 1~10 字
# 异常：chunk 数 ≤ 6、间隔数秒 → 说明是「整段到达」，检查上面两个配置
```

**实测对比**：
| 状态 | chunk 数 | 到达间隔 | 结论 |
|---|---|---|---|
| 修复前 | 2 | 7.13s | ❌ 假流式（整块到达） |
| 修复后 | 30+ | 30-200ms | ✅ 真·token 级流式 |
