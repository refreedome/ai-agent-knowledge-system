"""
RAGAS 生成质量评测：忠实度（Faithfulness）+ 答案相关性（Answer Relevancy）

前置条件：
    1. pip install -r requirements-eval.txt
    2. 设置 DASHSCOPE_API_KEY（RAGAS 底层调用 LLM 与 Embedding 打分）
    3. 知识库已向量化入库（python -c "from rag.vector_store import VectorStoreService; VectorStoreService().load_document()"）

用法：
    python evaluation/evaluate_ragas.py --sample 10

说明：
    - 从固定测试集抽样 N 题，走线上混合检索 + 生成回答
    - 用 RAGAS 计算：faithfulness（回答是否忠于检索到的资料）、
      answer_relevancy（回答是否紧扣问题）
    - 输出每题分数与平均值，用于对比「改版前 vs 改版后」的生成质量
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datasets import Dataset

from utils.path_tool import get_abs_path
from rag.rag_service import RagSummarizeService
from utils.logger_handler import logger


def load_test_set(path: str = None) -> list:
    path = path or get_abs_path("data/eval/test_set.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_dataset(rag: RagSummarizeService, test_set: list) -> Dataset:
    """对每道题跑线上链路，构造 RAGAS 需要的 (question, answer, contexts)"""
    rows = []
    for item in test_set:
        query = item["query"]
        docs = [doc for doc, _ in rag.hybrid_search.search_with_scores(query, k=3)]
        contexts = [d.page_content for d in docs]
        answer = rag.rag_summarize(query)
        rows.append({"question": query, "answer": answer, "contexts": contexts})
        print(f"  [eval] #{item['id']} {query} -> 回答 {len(answer)} 字")
    return Dataset.from_list(rows)


def main():
    parser = argparse.ArgumentParser(description="RAGAS 生成质量评测")
    parser.add_argument("--sample", type=int, default=10, help="抽样题数")
    args = parser.parse_args()

    try:
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy
    except ImportError:
        print("缺少 ragas，请先执行: pip install -r requirements-eval.txt")
        return 1

    test_set = load_test_set()[: args.sample]
    print(f"RAGAS 评测：抽样 {len(test_set)} 题")

    rag = RagSummarizeService()
    dataset = build_dataset(rag, test_set)

    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy],
    )
    df = result.to_pandas()
    print("\n" + "=" * 60)
    print(df[["question", "faithfulness", "answer_relevancy"]].to_string(index=False))
    print("=" * 60)
    print(f"平均 faithfulness:        {df['faithfulness'].mean():.3f}")
    print(f"平均 answer_relevancy:    {df['answer_relevancy'].mean():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
