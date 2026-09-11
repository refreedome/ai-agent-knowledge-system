"""
通过 nginx（前端容器）验证 SSE 真流式：证明反向代理没有把流攒成一次性返回。

用法：等 docker compose 起好之后
    python evaluation/verify_nginx_sse.py
"""

import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8090"
QUESTION = "这款扫地机器人的吸力是多少帕？"


def get(path, timeout=10):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def main():
    print("=== 1. 前端静态页面（nginx 托管）===")
    try:
        status, body = get("/")
        has_root = '<div id="root">' in body or "root" in body
        print(f"  GET /  -> HTTP {status} | 含 SPA 挂载点: {has_root} | 长度 {len(body)}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return 1

    print("\n=== 2. /api 反代是否通（nginx -> api:8000）===")
    try:
        status, body = get("/api/health")
        print(f"  GET /api/health -> HTTP {status} | {body.strip()[:80]}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return 1

    print("\n=== 3. 经 nginx 的 SSE 流式（关键：验证 proxy_buffering off 生效）===")
    body = json.dumps({"query": QUESTION, "user_id": "admin"}).encode()
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=body,
        headers={"Content-Type": "application/json", "X-User-Id": "admin"},
    )
    t0 = time.time()
    last = t0
    gaps = []
    tokens = 0
    tools = []
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            for raw in r:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except Exception:
                    continue
                now = time.time()
                if ev.get("type") == "token":
                    tokens += 1
                    gaps.append(now - last)
                    last = now
                elif ev.get("type") == "tool":
                    tools.append(ev.get("name"))
    except Exception as e:
        print(f"  ❌ 请求失败: {e}")
        return 1

    total = time.time() - t0
    if not gaps:
        print("  ❌ 没收到 token 事件")
        return 1

    g = sorted(gaps)
    print(f"  token 事件数: {tokens}")
    print(f"  工具调用    : {tools or '无'}")
    print(f"  总耗时      : {total:.1f}s")
    print(f"  分片间隔    : 最小 {min(gaps)*1000:.0f}ms | 中位 {g[len(g)//2]*1000:.0f}ms | 最大 {max(gaps)*1000:.0f}ms")
    print(f"  首片延迟    : {gaps[0]*1000:.0f}ms")

    ok = tokens >= 15 and g[len(g) // 2] < 500
    print("\n结论:", "✅ 经 nginx 仍是逐 token 流式（代理未缓冲）" if ok else "⚠️ 分片太少或间隔过大，代理可能仍在缓冲")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
