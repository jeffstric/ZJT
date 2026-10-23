# MR 大模型代码审查

Merge Request Pipeline 会跑 `ai_code_review`：用本地 git 取本次 MR 的 diff，调用内网 vLLM，把审查意见写到 MR 评论。审查失败或超时不会把流水线打红（`allow_failure: true`）。

## 模型路由

审查不直连某一张卡，而是走 jeffS7 上的会话路由器。路由器把无会话键的请求平滑加权轮询到两台在线后端，模型名都是 `qwen3.8:27b`，上下文上限 204800。

| 角色 | 地址 | 说明 |
|------|------|------|
| 入口 | `http://192.168.10.112:4000` | jeffS7 `vllm-session-router`，CI 默认 `VLLM_BASE_URL` |
| 后端 | `http://192.168.10.112:8000` | jeffS7，A6000，Qwen3.8-27B-W4A16-AWQ |
| 后端 | `http://192.168.10.243:8000` | jeffS10，Definitive FP8，Qwen3.8-27B-FP8 |
| 兜底 | `http://192.168.10.108:8000` | jeffS3，平时停机，路由器仅在前两台都不可用时尝试 |

档案在 `G:/code/system_config/servers/jeffS7.md` 与 `jeffS10.md`。这套地址只给 CI 审查用。应用进程的 `llm.vllm.base_url` 仍是独立配置，不要为了审查去改它。

Runner 必须能访问 `192.168.10.112:4000`。脚本对 vLLM 请求不走 `HTTP(S)_PROXY`。

## 流水线行为

- 只在 `CI_PIPELINE_SOURCE == merge_request_event` 时运行。
- `stage: review`，并设置 `needs: []`，因此和 lint 同时开始，不等待、也不拦住 `test` / `e2e`。
- `timeout: 20m`。vLLM 用流式补全，单次读超时默认 120 秒。路由器一直不回包时，改直连 jeffS7:8000，再不行直连 jeffS10:8000。
- 同一 commit 已有带标记的审查评论时跳过，避免重跑流水线刷屏。
- 锁文件、二进制、`bin/`、`node_modules` 不送进模型。文本 diff 默认最多 40 个文件、共 8 万字符。

评论是参考意见。合并是否通过仍由原有 lint、单元测试和 E2E 决定。

## 发表评论的令牌

diff 不走 GitLab `/diffs` 接口。GitLab 18 的 `CI_JOB_TOKEN` 只能读取 MR 本体和评论，访问 `/merge_requests/:iid/diffs` 会返回 `404 Project Not Found`。作业检出仓库后用 `git diff $CI_MERGE_REQUEST_DIFF_BASE_SHA $CI_COMMIT_SHA`。`python:3.10-slim` 没有 git，`before_script` 会安装。

发表评论仍要令牌，按这个顺序取：

1. CI/CD Variable `AI_REVIEW_GITLAB_TOKEN`（`PRIVATE-TOKEN`）
2. 流水线自带的 `CI_JOB_TOKEN`（先 `JOB-TOKEN`，401/403/404 时再试 `PRIVATE-TOKEN`）

`CI_JOB_TOKEN` 不能创建 MR note，接口同样返回 `404 Project Not Found`。要在 MR 里看到评论，在项目 **Settings → CI/CD → Variables** 增加：

| 变量 | 值 |
|------|----|
| `AI_REVIEW_GITLAB_TOKEN` | 项目 Access Token，角色 Developer，范围勾选 `api` |

令牌勾选 Masked。不要写进仓库。

可选覆盖：

| 变量 | 默认 | 含义 |
|------|------|------|
| `VLLM_BASE_URL` | `http://192.168.10.112:4000` | 路由器地址 |
| `VLLM_MODEL` | `qwen3.8:27b` | `--served-model-name` |
| `AI_REVIEW_PROBE_TIMEOUT` | `15` | 调用前探测 `/v1/models` 的超时（秒），连不上就失败，不再空等补全超时 |
| `AI_REVIEW_VLLM_TIMEOUT` | `120` | 流式补全时，两次读之间的超时（秒）。整段生成可以更长 |
| `AI_REVIEW_LLM_ATTEMPTS` | `3` | 依次尝试的地址数：路由器、jeffS7:8000、jeffS10:8000 |
| `AI_REVIEW_MAX_TOKENS` | `4096` | 审查输出上限 |
| `AI_REVIEW_MAX_DIFF_CHARS` | `80000` | 送进模型的 diff 总字符 |
| `AI_REVIEW_MAX_FILES` | `40` | 送进模型的文件数 |
| `AI_REVIEW_TEMPERATURE` | `0.3` | 采样温度 |

思考模式在审查请求里关闭（`chat_template_kwargs.enable_thinking=false`），避免思维链占满输出预算、拖长 MR 评论等待。

## 本地检查

路由健康检查：

```bash
curl http://192.168.10.112:4000/v1/models
```

应返回 `id` 为 `qwen3.8:27b`。脚本逻辑单测：

```bash
python -m pytest tests/scripts/test_ai_code_review.py
```
