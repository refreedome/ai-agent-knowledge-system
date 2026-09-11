"""
审计 requirements.txt：找出「项目实际 import 了、但 requirements 里没写」的依赖。

做法：① AST 解析项目所有 .py 的顶层 import；② 排除标准库与项目内模块；
      ③ 用本地环境的 packages_distributions() 反查每个模块由哪个发行版提供；
      ④ 与 requirements.txt 比对，输出缺失项。

用途：本地能跑、容器里崩（ImportError）的根因基本都是这类漏写。
"""

import ast
import importlib.metadata as md
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(r"D:\Code\projects\ai-agent-knowledge-system")
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "chroma_db", "data", "logs", "dist", ".github"}

# 项目自身的包名（不是第三方依赖）
LOCAL = {
    "agent", "api", "rag", "model", "database", "utils", "infrastructure",
    "config", "evaluation", "tests", "prompts", "app",
}

stdlib = set(sys.stdlib_module_names)

used = {}
for py in ROOT.rglob("*.py"):
    if any(part in SKIP_DIRS for part in py.parts):
        continue
    try:
        tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split(".")[0]
                used.setdefault(top, set()).add(str(py.relative_to(ROOT)))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相对导入，跳过
                continue
            if node.module:
                top = node.module.split(".")[0]
                used.setdefault(top, set()).add(str(py.relative_to(ROOT)))

third_party = {m: f for m, f in used.items() if m not in stdlib and m not in LOCAL and not m.startswith("_")}

# 模块名 → 发行版名
pkg_map = md.packages_distributions()
module_to_dists = {}
for mod in third_party:
    module_to_dists[mod] = pkg_map.get(mod, [])

# requirements.txt 里已声明的
req_file = ROOT / "requirements.txt"
declared = set()
for line in req_file.read_text(encoding="utf-8").splitlines():
    line = line.split("#")[0].strip()
    if line:
        declared.add(line.lower().replace("_", "-"))

print(f"项目里出现的第三方顶层模块：{len(third_party)} 个\n")
print(f"{'模块':<18}{'提供它的发行版':<34}{'requirements 里?':<16}出现位置")
print("-" * 110)
missing = []
for mod, files in sorted(third_party.items()):
    dists = module_to_dists.get(mod) or []
    dist_str = ", ".join(dists) if dists else "(本地找不到该模块!)"
    if dists:
        # 只要任一发行版已声明就算覆盖
        ok = any(d.lower().replace("_", "-") in declared for d in dists)
    else:
        ok = False
    flag = "✅" if ok else "❌ 缺"
    if not ok:
        missing.append((mod, dists))
    sample = sorted(files)[0]
    print(f"{mod:<18}{dist_str:<34}{flag:<16}{sample}")

print("\n" + "=" * 60)
if missing:
    print("需要补进 requirements.txt 的发行版名：")
    for mod, dists in missing:
        if dists:
            print(f"  {dists[0]}        # 提供 {mod}")
        else:
            print(f"  ??? 提供 {mod}（本地环境未安装，需人工确认）")
else:
    print("✅ requirements.txt 已覆盖所有第三方 import")
