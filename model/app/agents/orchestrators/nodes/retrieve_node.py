import logging
import asyncio
from typing import Dict
from app.agents.core.schema import ClinicalState
from app.agents.orchestrators.nodes.base import BaseNode
from app.agents.constants import MAX_EVIDENCE_CHARS
from app.agents.utils.text_utils import truncate_text

logger = logging.getLogger(__name__)


class RetrieveNode(BaseNode):
    """证据检索节点"""

    def __init__(self, medical_assistant):
        self.medical_assistant = medical_assistant

    async def run(self, state: ClinicalState) -> Dict:
        evidence = await self.medical_assistant.afast_parallel_retrieve(
            state["clinical_questions"]
        )
        return {"evidence": truncate_text(evidence, MAX_EVIDENCE_CHARS)}