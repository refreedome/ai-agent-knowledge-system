# -*- coding: utf-8 -*-
"""流式验证：测每个 SSE chunk 的到达时刻，判断是真流式还是"整段到达" """
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
body = json.dumps({"query": "小户型适合哪些扫地机器人？", "user_id": "guest"}).encode("utf-8")
req = urllib.request.Request(
    BASE + "/api/chat", data=body,
    headers={"Content-Type": "application/json", "X-User-Id": "guest"},
)

t0 = time.perf_counter()
prev = 0.0
n = 0
total_chars = 0
print(f"{'到达时刻':>9} {'间隔':>8} {'#':>3} {'类型':>6} {'长度':>5}  内容预览")
print("-" * 78)
with urllib.request.urlopen(req, timeout=180) as r:
    for raw in r:  # 逐行读，读到就打印（不缓存整个响应）
        line = raw.decode("utf-8", "ignore").strip()
        if not line.startswith("data:"):
            continue
        try:
            d = json.loads(line[5:].strip())
        except Exception:
            continue
        dt = time.perf_counter() - t0
        gap = dt - prev
        prev = dt
        n += 1
        c = d.get("content", "") or ""
        total_chars += len(c)
        print(f"{dt:8.2f}s {gap:7.2f}s {n:3} {d.get('type',''):>6} {len(c):5}  {c[:36]!r}")

print("-" * 78)
print(f"总 chunk 数: {n}   总字符: {total_chars}   总耗时: {prev:.2f}s")
print()
if n <= 6:
    print("❌ 判定：不是 token 级流式——chunk 数极少（每个 AI 消息一次），用户看到的是「一块一块」出现")
else:
    print("✅ 判定：疑似 token 级流式（chunk 数较多）")
