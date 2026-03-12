import concurrent.futures
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app, resources


class StubModel:
    def analyze_patient_risk(self, patient_text: str, all_info: str = ""):
        return {
            "riskLevel": "高风险",
            "suggestion": f"建议进一步评估：{patient_text[:8]}",
            "analysisDetails": f"测试分析完成，补充信息：{all_info or '无'}"
        }


class TestAiAnalyze(unittest.TestCase):
    def setUp(self):
        resources["model"] = StubModel()
        resources["executor"] = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.client = TestClient(app)

    def tearDown(self):
        if resources["executor"]:
            resources["executor"].shutdown(wait=True)
        resources["model"] = None
        resources["executor"] = None

    @patch("main.verify_token")
    def test_ai_analyze_success_response_shape(self, mock_verify_token):
        response = self.client.post(
            "/ai/analyze",
            json={
                "patientId": 1,
                "data": "患者突发头晕伴右侧肢体乏力",
                "all_info": "既往高血压",
                "token": "test-token"
            }
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["code"], 1)
        self.assertEqual(payload["msg"], "success")
        self.assertEqual(payload["data"]["riskLevel"], "高风险")
        self.assertIn("suggestion", payload["data"])
        self.assertIn("analysisDetails", payload["data"])
        mock_verify_token.assert_called_once_with("test-token")

    @patch("main.verify_token")
    def test_ai_analyze_blank_data_returns_422(self, mock_verify_token):
        response = self.client.post(
            "/ai/analyze",
            json={
                "patientId": 2,
                "data": "   ",
                "all_info": "",
                "token": "test-token"
            }
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "data cannot be empty")
        mock_verify_token.assert_called_once_with("test-token")


if __name__ == "__main__":
    unittest.main()

