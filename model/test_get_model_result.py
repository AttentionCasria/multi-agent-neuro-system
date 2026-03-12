import concurrent.futures
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app, resources


class StubModel:
    def __init__(self, answer_text):
        self.answer_text = answer_text

    def run_clinical_reasoning(self, case_text: str, all_info: str = "", report_mode: str = "emergency", show_thinking: bool = True):
        if self.answer_text:
            yield {"type": "result", "content": self.answer_text}


class StubNamingModel:
    def run_naming(self, question: str):
        return "测试咨询"


class StubContextSummary:
    def __init__(self, score=0.8, updated_all_info="更新后的all_info"):
        self.score = score
        self.updated_all_info = updated_all_info

    def update_all_info(self, previous_all_info: str, question: str, answer: str, threshold: float = 0.4):
        return {
            "score": self.score,
            "reason": "stub summary",
            "is_valuable": self.score > threshold,
            "updated_all_info": self.updated_all_info if self.score > threshold else previous_all_info
        }


class TestGetModelResult(unittest.TestCase):
    def setUp(self):
        resources["executor"] = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        resources["naming_model"] = StubNamingModel()
        self.client = TestClient(app)

    def tearDown(self):
        if resources["executor"]:
            resources["executor"].shutdown(wait=True)
        resources["model"] = None
        resources["naming_model"] = None
        resources["executor"] = None
        resources["context_summary"] = None

    @patch("main.verify_token")
    def test_done_event_carries_summary_and_name_when_turn_is_valuable(self, mock_verify_token):
        answer = "建议尽快复查头颅影像并监测血压，存在卒中进展风险。"
        summary = "1. 高血压\n2. 建议复查影像"
        resources["model"] = StubModel(answer)
        resources["context_summary"] = StubContextSummary(score=0.9, updated_all_info=summary)

        response = self.client.post(
            "/model/get_result",
            json={
                "question": "患者后续需要注意什么？",
                "round": 2,
                "all_info": "既往高血压",
                "token": "test-token",
                "report_mode": "emergency",
                "show_thinking": False
            }
        )

        self.assertEqual(response.status_code, 200)
        lines = [json.loads(line) for line in response.text.strip().splitlines()]
        self.assertEqual(lines[0]["result"], answer)
        self.assertEqual(lines[-2]["meta"]["all_info_update"]["summary"], summary)
        self.assertEqual(lines[-1]["type"], "done")
        self.assertEqual(lines[-1]["result"], answer)
        self.assertEqual(lines[-1]["summary"], summary)
        self.assertEqual(lines[-1]["name"], "测试咨询")
        self.assertEqual(lines[-1]["all_info"], summary)
        mock_verify_token.assert_called_once_with("test-token")

    @patch("main.verify_token")
    def test_done_event_keeps_original_summary_when_turn_not_valuable(self, mock_verify_token):
        answer = "建议继续观察。"
        resources["model"] = StubModel(answer)
        resources["context_summary"] = StubContextSummary(score=0.2, updated_all_info="不会被采用")

        response = self.client.post(
            "/model/get_result",
            json={
                "question": "还有别的注意事项吗？",
                "round": 2,
                "all_info": "原始摘要",
                "token": "test-token",
                "report_mode": "emergency",
                "show_thinking": False
            }
        )

        self.assertEqual(response.status_code, 200)
        lines = [json.loads(line) for line in response.text.strip().splitlines()]
        self.assertFalse(lines[-2]["meta"]["all_info_update"]["is_valuable"])
        self.assertEqual(lines[-1]["type"], "done")
        self.assertEqual(lines[-1]["result"], answer)
        self.assertEqual(lines[-1]["summary"], "原始摘要")
        self.assertEqual(lines[-1]["name"], "测试咨询")
        mock_verify_token.assert_called_once_with("test-token")

    @patch("main.verify_token")
    def test_done_event_handles_empty_final_answer(self, mock_verify_token):
        resources["model"] = StubModel("")
        resources["context_summary"] = StubContextSummary(score=0.9, updated_all_info="新摘要")

        response = self.client.post(
            "/model/get_result",
            json={
                "question": "空回答场景",
                "round": 1,
                "all_info": "历史摘要",
                "token": "test-token",
                "report_mode": "emergency",
                "show_thinking": False
            }
        )

        self.assertEqual(response.status_code, 200)
        lines = [json.loads(line) for line in response.text.strip().splitlines()]
        self.assertEqual(lines[-2]["meta"]["all_info_update"]["reason"], "no final answer")
        self.assertEqual(lines[-1]["type"], "done")
        self.assertEqual(lines[-1]["result"], "")
        self.assertEqual(lines[-1]["summary"], "历史摘要")
        self.assertEqual(lines[-1]["name"], "测试咨询")
        mock_verify_token.assert_called_once_with("test-token")


if __name__ == "__main__":
    unittest.main()
