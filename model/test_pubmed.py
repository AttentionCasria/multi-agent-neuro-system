import asyncio
from services.pubmed_service import PubMedService

async def main():
    svc = PubMedService()

    print("=== 搜索测试 ===")
    results = await svc.search_papers("stroke rehabilitation", max_results=3)

    print(f"共返回 {len(results)} 篇\n")
    for i, p in enumerate(results, 1):
        print(f"[{i}] PMID: {p['pmid']}")
        print(f"    标题: {p['title'][:60]}...")
        print(f"    期刊: {p['journal']}")
        print(f"    类型: {p['pub_type']}")
        print()

asyncio.run(main())