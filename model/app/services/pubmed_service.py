
import logging
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

_EVIDENCE_RANK: Dict[str, int] = {
    "Practice Guideline": 0,
    "Guideline": 1,
    "Meta-Analysis": 2,
    "Systematic Review": 3,
    "Randomized Controlled Trial": 4,
    "Clinical Trial": 5,
    "Review": 6,
    "Case Reports": 7,
}

_PUBMED_TOOL = "synapse_md"
_PUBMED_EMAIL = "sophronm91@gmail.com"

PUBMED_API_KEY = "0d747a8e235b8974d2b05d74312446f72f08"


class PubMedService:

    _BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, api_key: str = PUBMED_API_KEY):
        self.api_key = api_key

    def _common_params(self) -> Dict[str, str]:
        params: Dict[str, str] = {
            "tool": _PUBMED_TOOL,
            "email": _PUBMED_EMAIL,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    async def search_papers(
        self,
        query: str,
        max_results: int = 5,
        years: int = 3,
    ) -> List[Dict[str, Any]]:
        try:
            pmids = await self._esearch(
                query, retmax=max_results * 3, reldays=years * 365
            )
            if not pmids:
                logger.info(f"PubMed 无结果: query={query!r}")
                return []

            papers = await self._efetch(pmids[:15])

            papers.sort(key=lambda p: self._evidence_rank(p.get("pub_type", [])))
            return papers[:max_results]

        except Exception as e:
            logger.error(f"PubMed 检索异常: {e}")
            return []

    async def _esearch(self, query: str, retmax: int, reldays: int) -> List[str]:
        params = {
            **self._common_params(),
            "db": "pubmed",
            "term": query,
            "retmax": str(retmax),
            "sort": "relevance",
            "retmode": "json",
            "datetype": "pdat",
            "reldate": str(reldays),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._BASE}/esearch.fcgi", params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("esearchresult", {}).get("idlist", [])

    async def _efetch(self, pmids: List[str]) -> List[Dict[str, Any]]:
        if not pmids:
            return []
        params = {
            **self._common_params(),
            "db": "pubmed",
            "id": ",".join(pmids),
            "rettype": "xml",
            "retmode": "xml",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{self._BASE}/efetch.fcgi", params=params)
            resp.raise_for_status()
            return self._parse_xml(resp.text)

    def _parse_xml(self, xml_text: str) -> List[Dict[str, Any]]:
        papers: List[Dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"PubMed XML 解析失败: {e}")
            return []

        for article_elem in root.findall(".//PubmedArticle"):
            paper = self._parse_article(article_elem)
            if paper:
                papers.append(paper)
        return papers

    def _parse_article(self, elem) -> Optional[Dict[str, Any]]:
        try:
            pmid = elem.findtext(".//PMID", "").strip()

            title_elem = elem.find(".//ArticleTitle")
            title = (
                "".join(title_elem.itertext()).strip()
                if title_elem is not None
                else ""
            )

            abstract_parts: List[str] = []
            for ab in elem.findall(".//AbstractText"):
                label = ab.get("Label", "")
                text = "".join(ab.itertext()).strip()
                if not text:
                    continue
                abstract_parts.append(f"{label}: {text}" if label else text)
            full_abstract = " ".join(abstract_parts)
            abstract = full_abstract[:500] + ("..." if len(full_abstract) > 500 else "")

            author_elems = elem.findall(".//Author")
            names: List[str] = []
            for au in author_elems[:3]:
                last = au.findtext("LastName", "")
                initials = au.findtext("Initials", "")
                if last:
                    names.append(f"{last} {initials}".strip())
            author_str = ", ".join(names)
            if len(author_elems) > 3:
                author_str += " et al."

            journal = (
                elem.findtext(".//Journal/Title")
                or elem.findtext(".//Journal/ISOAbbreviation")
                or ""
            ).strip()

            pd_elem = elem.find(".//PubDate")
            if pd_elem is not None:
                year = pd_elem.findtext("Year", "")
                month = pd_elem.findtext("Month", "")
                pub_date = f"{year} {month}".strip()
            else:
                pub_date = ""

            pub_types = [
                pt.text.strip()
                for pt in elem.findall(".//PublicationType")
                if pt.text
            ]

            if not pmid or not title:
                return None

            return {
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "authors": author_str,
                "journal": journal,
                "pub_date": pub_date,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "pub_type": pub_types,
            }

        except Exception as e:
            logger.error(f"解析单篇文章失败: {e}")
            return None

    def _evidence_rank(self, pub_types: List[str]) -> int:
        return min(
            (_EVIDENCE_RANK.get(pt, 8) for pt in pub_types),
            default=8,
        )
