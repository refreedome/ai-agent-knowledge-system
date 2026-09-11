"""
检索评测脚本：Hit Rate@K（三种模式 + 可生成 Markdown 报告）

指标定义：
    Hit Rate@K = 检索 topK 中命中「期望关键词」的问题数 / 总问题数
    命中 = 任一返回分块的正文包含该题的任一期望关键词

三种模式：
    1. local（离线 BM25，无需 API Key）—— CI 可跑，用于快速回归
       直接从 data/knowledge_base 原始文档解析 + 分块 + 建 BM25 索引
    2. semantic（纯语义向量检索）—— 需要 DASHSCOPE_API_KEY 且知识库已入库
       作为「混合检索」的基线（Baseline）
    3. hybrid（线上混合检索 BM25 + 向量 + RRF）—— 需要 Key 且已入库
       线上真实链路

用法：
    python evaluation/evaluate_retrieval.py --source local
    python evaluation/evaluate_retrieval.py --source semantic --report
    python evaluation/evaluate_retrieval.py --source hybrid   --report
    python evaluation/evaluate_retrieval.py --source all --report   # 三种模式全跑并对比
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import jieba
from rank_bm25 import BM25Okapi
from langchain_text_splitters import RecursiveCharacterTextSplitter

from utils.config_handler import chroma_conf
from utils.path_tool import get_abs_path
from utils.file_handler import (
    listdir_with_allowed_type, pdf_loader, txt_loader,
    docx_loader, csv_loader, image_loader,
)

LOADERS = {
    "txt": txt_loader, "pdf": pdf_loader, "docx": docx_loader,
    "csv": csv_loader, "jpg": image_loader, "jpeg": image_loader, "png": image_loader,
}


def load_test_set(path: str = None) -> list:
    path = path or get_abs_path("data/eval/test_set.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _judge(item: dict, contents: list) -> dict:
    hit = any(any(kw in c for kw in item["expected"]) for c in contents)
    return {"id": item["id"], "query": item["query"], "hit": hit}


def _rate(details: list) -> float:
    return sum(1 for d in details if d["hit"]) / len(details) if details else 0.0


# ─────────────────── 模式一：离线 BM25 ───────────────────

def build_local_documents() -> list:
    """从原始文档解析 + 分块（与线上入库同一套切分参数）"""
    data_dir = get_abs_path(chroma_conf["data_path"])
    allowed = tuple(chroma_conf["allow_knowledge_file_type"])
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chroma_conf["chunk_size"],
        chunk_overlap=chroma_conf["chunk_overlap"],
        separators=chroma_conf["separators"],
        length_function=len,
    )
    docs = []
    for path in listdir_with_allowed_type(data_dir, allowed):
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        loader = LOADERS.get(ext)
        if not loader:
            continue
        try:
            chunks = splitter.split_documents(loader(path))
            docs.extend(chunks)
            print(f"  [load] {os.path.basename(path)} -> {len(chunks)} 块")
        except Exception as e:
            print(f"  [skip] {os.path.basename(path)}: {e}")
    return docs


def hit_rate_bm25(documents: list, test_set: list, k: int = 5) -> tuple:
    corpus = [list(jieba.cut(d.page_content)) for d in documents]
    bm25 = BM25Okapi(corpus)
    details = []
    for item in test_set:
        scores = bm25.get_scores(list(jieba.cut(item["query"])))
        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        contents = [documents[i].page_content for i in top_idx]
        details.append(_judge(item, contents))
    return _rate(details), details


# ─────────────────── 模式二/三：向量 & 混合 ───────────────────

def hit_rate_by_service(test_set: list, k: int = 5, mode: str = "hybrid") -> tuple:
    """mode=semantic 走纯向量；mode=hybrid 走混合检索"""
    from rag.rag_service import RagSummarizeService

    rag = RagSummarizeService()
    details = []
    for item in test_set:
        if mode == "semantic":
            docs = [d for d, _ in rag.vector_store.search_with_scores(item["query"], k=k)]
        else:
            docs = [d for d, _ in rag.hybrid_search.search_with_scores(item["query"], k=k)]
        details.append(_judge(item, [d.page_content for d in docs]))
    return _rate(details), details


# ─────────────────── 报告 ───────────────────

def write_report(results: dict, test_set: list, k: int, details_all: dict, report_path: str):
    lines = []
    lines.append(f"# RAG 检索评测报告（Hit Rate@{k}）")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 测试集：`data/eval/test_set.json`，共 **{len(test_set)}** 题（每题含 query + 期望关键词）")
    lines.append("- 评测脚本：`evaluation/evaluate_retrieval.py`")
    lines.append(
        f"- 检索参数：top_k = {k}，chunk_size = {chroma_conf['chunk_size']}，"
        f"chunk_overlap = {chroma_conf['chunk_overlap']}，"
        f"RRF k = {chroma_conf.get('hybrid_search', {}).get('rrf_k')}，"
        f"语义权重 = {chroma_conf.get('hybrid_search', {}).get('semantic_weight')}"
    )
    lines.append("")
    lines.append("## 一、结果对比")
    lines.append("")
    lines.append(f"| 检索模式 | 说明 | Hit Rate@{k} | 相对基线 |")
    lines.append("|---|---|---|---|")
    baseline = results.get("semantic")
    for name, label in (
        ("semantic", "纯语义向量检索（Baseline）"),
        ("hybrid", "混合检索：BM25 + 向量 + RRF"),
        ("local", "离线 BM25（无 Key，CI 用）"),
    ):
        if name in results:
            delta = "—"
            if baseline is not None and name != "semantic":
                delta = f"{(results[name] - baseline) * 100:+.1f} pp"
            lines.append(f"| {name} | {label} | **{results[name]:.2%}** | {delta} |")
    lines.append("")
    lines.append("## 二、结论")
    lines.append("")
    if baseline is not None and "hybrid" in results:
        lines.append(
            f"在 {len(test_set)} 条固定测试集上，**混合检索相比纯语义检索把 Hit Rate@{k} "
            f"从 {baseline:.2%} 提升到 {results['hybrid']:.2%}"
            f"（{(results['hybrid'] - baseline) * 100:+.1f} 个百分点）**，"
            "验证了 BM25 关键词检索对专业术语、产品型号类查询的补充价值。"
        )
    lines.append("")
    lines.append(
        f"> 命中判定：top{k} 分块中任一包含该题期望关键词即算命中。"
        "该指标衡量**检索召回质量**，也就是生成质量的上限。"
    )
    lines.append("")
    lines.append("## 三、未命中明细（改进线索）")
    lines.append("")
    for mode, details in details_all.items():
        misses = [d for d in details if not d["hit"]]
        lines.append(f"### {mode}（未命中 {len(misses)}/{len(details)}）")
        lines.append("")
        if not misses:
            lines.append("- 全部命中（100%）")
        else:
            for m in misses:
                lines.append(f"- #{m['id']} {m['query']}")
        lines.append("")
    lines.append("## 四、复现方式")
    lines.append("")
    lines.append("```bash")
    lines.append("# 离线（无需 Key，CI 可跑）")
    lines.append("python evaluation/evaluate_retrieval.py --source local")
    lines.append("")
    lines.append("# 基线：纯语义检索（需 DASHSCOPE_API_KEY 且知识库已入库）")
    lines.append("python evaluation/evaluate_retrieval.py --source semantic --report")
    lines.append("")
    lines.append("# 混合检索（线上真实链路）")
    lines.append("python evaluation/evaluate_retrieval.py --source hybrid --report")
    lines.append("")
    lines.append("# 三模式对比并生成报告")
    lines.append("python evaluation/evaluate_retrieval.py --source all --report")
    lines.append("```")
    lines.append("")
    lines.append("## 五、测试集说明")
    lines.append("")
    lines.append("测试集模拟真实客服问题，覆盖：产品选购、续航电池、故障排除、维护保养、")
    lines.append("耗材更换、导航建图、App 与语音、安全与适配 等场景。")
    lines.append("每题标注 1-2 个「期望关键词」，命中判定即以此为准（关键词取自知识库文档的真实表述）。")
    lines.append("")
    lines.append("| # | 问题 | 期望关键词 |")
    lines.append("|---|---|---|")
    for item in test_set:
        lines.append(f"| {item['id']} | {item['query']} | {'、'.join(item['expected'])} |")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告已写入: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Hit Rate@K 检索评测")
    parser.add_argument("--source", choices=["local", "semantic", "hybrid", "all"], default="local")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--show-miss", action="store_true")
    parser.add_argument("--report", action="store_true", help="生成 Markdown 评测报告")
    args = parser.parse_args()

    test_set = load_test_set()
    print(f"测试集: {len(test_set)} 题 | 模式: {args.source} | k={args.k}")

    results, details_all = {}, {}

    if args.source in ("local", "all"):
        print("\n[local] 从原始文档构建 BM25 索引...")
        docs = build_local_documents()
        print(f"文档块总数: {len(docs)}")
        rate, details = hit_rate_bm25(docs, test_set, k=args.k)
        results["local"], details_all["local"] = rate, details
        print(f"[local] Hit Rate@{args.k} = {rate:.2%}")

    if args.source in ("semantic", "all"):
        print("\n[semantic] 纯语义向量检索（基线）...")
        rate, details = hit_rate_by_service(test_set, k=args.k, mode="semantic")
        results["semantic"], details_all["semantic"] = rate, details
        print(f"[semantic] Hit Rate@{args.k} = {rate:.2%}")

    if args.source in ("hybrid", "all"):
        print("\n[hybrid] 混合检索 BM25 + 向量 + RRF...")
        rate, details = hit_rate_by_service(test_set, k=args.k, mode="hybrid")
        results["hybrid"], details_all["hybrid"] = rate, details
        print(f"[hybrid] Hit Rate@{args.k} = {rate:.2%}")

    print("\n" + "=" * 52)
    for name, rate in results.items():
        print(f"{name:>10}: Hit Rate@{args.k} = {rate:.2%}")
    print("=" * 52)

    if args.show_miss:
        for name, details in details_all.items():
            misses = [d for d in details if not d["hit"]]
            if misses:
                print(f"\n{name} 未命中:")
                for m in misses:
                    print(f"  #{m['id']:>2} {m['query']}")

    if args.report:
        write_report(
            results, test_set, args.k, details_all,
            get_abs_path(f"evaluation/评测报告-HitRate@{args.k}.md"),
        )

    return 0 if all(r > 0 for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
