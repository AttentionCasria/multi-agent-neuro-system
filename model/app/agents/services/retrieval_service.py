import logging
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio

logger = logging.getLogger(__name__)


class EvidenceRetrievalService:

    def __init__(self, retriever, top_k=3):
        self.retriever = retriever
        self.top_k = top_k

    def retrieve_single(self, query: str) -> str:

        docs = self.retriever.search(query, self.top_k)

        if not docs:
            return ""

        results = []

        for i, doc in enumerate(docs):
            source = doc.metadata.get("source", "未知")
            page = doc.metadata.get("page", "?")
            score = doc.metadata.get("relevance_score", "N/A")

            content = doc.page_content[:500]

            results.append(
                f"【文献{i+1}】"
                f"[来源:{source} p.{page}]"
                f"(相关度:{score})\n"
                f"{content}"
            )

        return "\n\n".join(results)

    async def aretrieve_single(self, query: str) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.retrieve_single, query)

    async def aparallel_retrieve(self, queries: List[str]) -> str:
        import asyncio
        tasks = [self.aretrieve_single(q) for q in queries]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        parts = []
        for i, (q, content) in enumerate(zip(queries, results_list)):
            if isinstance(content, Exception):
                logger.error(f"检索失败 {q}: {content}")
                content = ""
            if content:
                parts.append(f"### 检索维度{i+1}: {q}\n{content}")

        return "\n\n---\n\n".join(parts)

    def parallel_retrieve(self, queries: List[str]) -> str:

        results = {}

        with ThreadPoolExecutor(
            max_workers=min(3, len(queries))
        ) as executor:

            future_map = {
                executor.submit(self.retrieve_single, q): q
                for q in queries
            }

            for future in as_completed(future_map):
                q = future_map[future]

                try:
                    results[q] = future.result()
                except Exception as e:
                    logger.error(f"检索失败 {q}: {e}")
                    results[q] = ""

        parts = []

        for i, q in enumerate(queries):
            content = results.get(q, "")

            if content:
                parts.append(
                    f"### 检索维度{i+1}: {q}\n{content}"
                )

        return "\n\n---\n\n".join(parts)