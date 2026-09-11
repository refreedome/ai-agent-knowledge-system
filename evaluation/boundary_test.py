# -*- coding: utf-8 -*-
"""边界 / 上传 / 并发 实测脚本（真跑，不是推断）"""
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def post_chat(query, user="guest", sid=None, timeout=150):
    body = json.dumps({"query": query, "user_id": user, "session_id": sid}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/chat", data=body,
        headers={"Content-Type": "application/json", "X-User-Id": user},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, len(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:120]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def upload(path, user="admin"):
    boundary = "----dshtestboundary"
    with open(path, "rb") as f:
        data = f.read()
    fn = os.path.basename(path)
    body = b"".join([
        ("--" + boundary + "\r\n").encode(),
        ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % fn).encode("utf-8"),
        b"Content-Type: application/octet-stream\r\n\r\n",
        data,
        ("\r\n--" + boundary + "--\r\n").encode(),
    ])
    req = urllib.request.Request(
        BASE + "/api/upload/file", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary, "X-User-Id": user},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode("utf-8", "ignore")[:160]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:160]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


print("=== 1) 输入边界（接口层，绕过前端直接打）===")
for name, q in [("空输入 ''", ""), ("纯空格 '   '", "   "), ("仅换行", "\n"), ("制表符", "\t"),
                ("超长 2001 字", "扫" * 2001), ("2000 字（上限内）", "扫" * 2000)]:
    code, info = post_chat(q)
    print(f"  {name:20} -> HTTP {code}")

code, info = post_chat("'; DROP TABLE sessions; -- 扫' OR 1=1")
print(f"  {'SQL 注入片段':20} -> HTTP {code}（当纯文本处理，返回 {info} 字符）")

print("\n=== 2) 上传边界 ===")
print("  错误后缀 .exe    ->", upload(r"C:\Windows\System32\notepad.exe"))
big = os.path.join(tempfile.gettempdir(), "big_test.txt")
with open(big, "wb") as f:
    f.write(b"x" * 12_000_000)
print("  超大 12MB        ->", upload(big))
empty = os.path.join(tempfile.gettempdir(), "empty_test.txt")
open(empty, "wb").close()
print("  空文件           ->", upload(empty))
uniq = os.path.join(tempfile.gettempdir(), "dshtest_uniq.txt")
with open(uniq, "w", encoding="utf-8") as f:
    f.write("扫地机器人滤网建议每 2-3 个月更换一次。")
print("  首次上传新文件   ->", upload(uniq))
print("  重复上传同一文件 ->", upload(uniq))

print("\n=== 3) 并发：两个用户同时提问（模拟两台电脑）===")
results = {}
lock = threading.Lock()


def ask(user, question):
    res = post_chat(question, user=user)
    with lock:
        results[user] = res


threads = [
    threading.Thread(target=ask, args=("alice", "扫地机器人电池续航一般多久？")),
    threading.Thread(target=ask, args=("bob", "机器人卡在门槛上不上去怎么办？")),
]
for t in threads:
    t.start()
for t in threads:
    t.join()
for u, r in results.items():
    print(f"  {u:6} -> HTTP {r[0]}, 回答 {r[1]} 字符")

print("\n=== 4) 会话隔离校验 ===")
for u in ("alice", "bob"):
    req = urllib.request.Request(BASE + f"/api/sessions?user_id={u}", headers={"X-User-Id": u})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    print(f"  {u:6} -> {d['total']} 个会话 {[s['session_id'] for s in d['sessions']]}")

print("\n=== 5) Metrics（真实数据）===")
with urllib.request.urlopen(BASE + "/api/metrics", timeout=10) as r:
    m = json.loads(r.read())
for k, v in m["stats"].items():
    print(
        f"  {k:14} 请求={v['total_requests']:3} 平均={v['avg_duration_ms']:8.0f}ms "
        f"P50={v['p50_duration_ms']:8.0f}ms P95={v['p95_duration_ms']:8.0f}ms "
        f"tokens={v['total_tokens']:6} 成功率={v['success_rate']}% 失败={v['failed_requests']}"
    )
