import unittest
from unittest.mock import MagicMock, patch

import anthropic

from ml.nlg_explainer import ClaudeExplainer, _template_explanation

ARGS = dict(
    target_zone_name="Cầu Giấy",
    target_deficit=3.2,
    driver_id="D0007",
    from_zone_name="Ba Đình",
    distance_m=850.0,
    p_accept=0.72,
)


class NoApiKeyFallbackTest(unittest.TestCase):
    """No ANTHROPIC_API_KEY configured — must fall back to the same template
    string ml/export_demo_data.py used before this module existed."""

    def test_falls_back_to_template(self):
        with patch.dict("os.environ", {}, clear=True):
            explainer = ClaudeExplainer(api_key=None)
            result = explainer.explain_suggestion(**ARGS)
        self.assertEqual(result, _template_explanation(**ARGS))


class ApiFailureFallsBackTest(unittest.TestCase):
    """With a key configured, a network/API failure must not crash the
    caller — falls back exactly like the no-key case."""

    def test_connection_error_falls_back(self):
        explainer = ClaudeExplainer(api_key="fake-key-for-test")
        with patch.object(
            explainer._client.messages,
            "create",
            side_effect=anthropic.APIConnectionError(request=MagicMock()),
        ):
            result = explainer.explain_suggestion(**ARGS)
        self.assertEqual(result, _template_explanation(**ARGS))


class SuccessfulApiCallTest(unittest.TestCase):
    def test_uses_claude_response_text(self):
        explainer = ClaudeExplainer(api_key="fake-key-for-test")
        fake_block = MagicMock(type="text", text="Cầu Giấy đang thiếu xe, di chuyển ngay để đón khách nhé.")
        fake_response = MagicMock(content=[fake_block])
        with patch.object(explainer._client.messages, "create", return_value=fake_response):
            result = explainer.explain_suggestion(**ARGS)
        self.assertEqual(result, "Cầu Giấy đang thiếu xe, di chuyển ngay để đón khách nhé.")


if __name__ == "__main__":
    unittest.main()
