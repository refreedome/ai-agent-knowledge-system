"""
并发实测：验证「同步业务跑在线程池里，事件循环不被阻塞」。

思路：
  1) 单请求基线：记录耗时 T1；
  2) 并发 3 个请求（不同用户 + 不同问题）：记录整批墙钟 T3；
  3) 判断标准用「加速比 = 串行总和 / 并发墙钟」——
       1.0x 表示完全串行；接近 3.0x 表示完美并发。
     （注意别拿 T3 直接跟 T1 比：并发时每个请求会变慢，那是**模型侧并发限流**，
       不是服务端把请求串行化了。）

★ 防缓存污染：热点问题缓存会直接回放答案（0.1s 级），让测量失去意义。
  所以这里 ① 每轮从题库里随机挑题，② 跑完对比 /api/cache 的命中次数增量，
  一旦发现命中就明确警告「本次数据不可用于判断并发能力」。

用法（服务已启动即可，默认打容器前端 8090 这一跳）：
    python evaluation/concurrency_check.py
"""

import asyncio
import json
import random
import sys
import threading
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8090"
TIMEOUT = 180

# 题库：每轮随机抽 4 道（1 基线 + 3 并发），降低与历史缓存撞车的概率
POOL = [
    "小户型适合哪种扫地机器人",
    "扫地机器人电池续航一般多久",
    "机器人卡在门槛上不去怎么办",
    "如何清理滚刷上缠绕的毛发",
    "水箱里的水多久换一次",
    "滤网需要多久更换一次",
    "机器工作时噪音太大怎么办",
    "边刷磨损了要不要更换",
    "家里养宠物适合买扫地机器人吗",
    "拖布用完之后怎么清洗",
    "机器突然不充电了是什么原因",
    "激光导航和视觉导航哪个更好",
    "扫地机器人的保修期是多久",
    "机器人迷路到处乱转是怎么回事",
]
USERS = ["admin", "alice", "bob", "guest"]


def cache_hits() -> int:
    try:
        with urllib.request.urlopen(BASE + "/api/cache", timeout=10) as r:
            return int(json.loads(r.read().decode()).get("hits", 0))
    except Exception:
        return -1


def ask(user: str, question: str) -> float:
    """发一次流式对话，返回耗时（秒）"""
    body = json.dumps({"query": question, "user_id": user}).encode()
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=body,
        headers={"Content-Type": "application/json", "X-User-Id": user},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        for raw in r:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            if line[5:].strip() == "[DONE]":
                break
    return time.time() - t0


async def _probe_limiter() -> int:
    """在事件循环内读取 anyio 默认线程限制器上限"""
    import anyio.to_thread

    return anyio.to_thread.current_default_thread_limiter().total_tokens


def main():
    picks = random.sample(POOL, 4)
    plan = [
        ("admin", picks[0]),
        ("alice", picks[1]),
        ("bob", picks[2]),
        ("guest", picks[3]),
    ]

    hits_before = cache_hits()
    print("=== 0. 环境 ===")
    print(f"  缓存命中次数(开始): {hits_before}")

    print("\n=== 1. 单请求基线 ===")
    base_user, base_q = plan[0]
    print(f"  {base_user}: {base_q}")
    t1 = ask(base_user, base_q)
    print(f"  耗时: {t1:.1f}s")

    print("\n=== 2. 并发 3 个请求（不同用户 + 不同问题）===")
    jobs = plan[1:]
    results = {}
    lock = threading.Lock()

    def worker(user, q):
        d = ask(user, q)
        with lock:
            results[user] = (d, q)

    threads = [threading.Thread(target=worker, args=j) for j in jobs]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0

    print("  各请求耗时:")
    for u, (d, q) in results.items():
        print(f"    {u:6} {d:5.1f}s   {q}")
    serial = sum(d for d, _ in results.values())
    print(f"  整批墙钟: {wall:.1f}s | 若串行: {serial:.1f}s")

    speedup = serial / wall if wall else 0

    print("\n=== 3. 线程池上限（anyio 默认限制器）===")
    try:
        print(f"  anyio 默认线程上限: {asyncio.run(_probe_limiter())}")
    except Exception as e:
        print(f"  探测失败: {e}")

    hits_after = cache_hits()
    used_cache = hits_after > hits_before if (hits_after >= 0 and hits_before >= 0) else None
    print("\n=== 4. 缓存污染检查 ===")
    print(f"  缓存命中次数(结束): {hits_after}"
          + ("  → 本轮有命中，数据偏乐观" if used_cache else "  → 本轮无命中，数据可用于判断并发"))

    print("\n=== 结论 ===")
    print(f"  加速比 = 串行总和 / 并发墙钟 = {speedup:.2f}x（1.0x=完全串行，3.0x=完美并发）")
    if used_cache:
        print("  ⚠️ 本轮测量包含缓存命中，请换个题库再跑一次以得到干净数据")
    elif speedup >= 1.5:
        print("  ✅ 请求并发推进：同步业务被丢进线程池，事件循环没被阻塞")
        print("     单个请求变慢主要来自模型侧并发限流（上游瓶颈），不是服务端排队")
    else:
        print("  ⚠️ 加速比接近 1，存在串行化：检查全局锁范围、线程池是否打满、或上游强制串行")


if __name__ == "__main__":
    main()
