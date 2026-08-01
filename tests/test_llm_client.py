"""Tests for chartwatch nvidia_client and llm_client modules."""

from unittest.mock import MagicMock, patch

import pytest

from chartwatch import llm_client, nvidia_client


class TestNvidiaClientAnalyze:
    def test_analyze_returns_dict(self):
        mock_choice = MagicMock()
        mock_choice.message.content = '{"assessment": "test", "trend_10min": "up", "confidence": 0.5, "open_position_action": null, "new_trade": null}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client_cls = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        with patch("chartwatch.nvidia_client.OpenAI", mock_client_cls):
            with patch("chartwatch.nvidia_client._encode_image") as mock_encode:
                mock_encode.return_value = "base64data"
                result = nvidia_client.analyze(
                    screenshot_path="/tmp/test.png",
                    position_context=None,
                    model="thinkingmachines/inkling",
                    api_key="test-key",
                    base_url="https://integrate.api.nvidia.com/v1",
                    temperature=1,
                    top_p=0.95,
                    max_tokens=8192,
                )

        assert isinstance(result, dict)
        assert result["assessment"] == "test"
        assert result["trend_10min"] == "up"

    def test_analyze_raises_on_empty_response(self):
        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client_cls = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        with patch("chartwatch.nvidia_client.OpenAI", mock_client_cls):
            with patch("chartwatch.nvidia_client._encode_image") as mock_encode:
                mock_encode.return_value = "base64data"
                with pytest.raises(ValueError, match="empty response"):
                    nvidia_client.analyze(
                        screenshot_path="/tmp/test.png",
                        position_context=None,
                        model="thinkingmachines/inkling",
                        api_key="test-key",
                        base_url="https://integrate.api.nvidia.com/v1",
                        temperature=1,
                        top_p=0.95,
                        max_tokens=8192,
                    )

    def test_analyze_raises_on_invalid_json(self):
        mock_choice = MagicMock()
        mock_choice.message.content = "not json"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client_cls = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        with patch("chartwatch.nvidia_client.OpenAI", mock_client_cls):
            with patch("chartwatch.nvidia_client._encode_image") as mock_encode:
                mock_encode.return_value = "base64data"
                with pytest.raises(ValueError, match="did not return valid JSON"):
                    nvidia_client.analyze(
                        screenshot_path="/tmp/test.png",
                        position_context=None,
                        model="thinkingmachines/inkling",
                        api_key="test-key",
                        base_url="https://integrate.api.nvidia.com/v1",
                        temperature=1,
                        top_p=0.95,
                        max_tokens=8192,
                    )


class TestLlmClientDispatch:
    def test_dispatch_to_ollama(self):
        cfg = {
            "provider": "ollama",
            "ollama": {"model": "qwen3.5:9b", "host": "http://localhost:11434"},
        }
        with patch("chartwatch.llm_client.ollama_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            result = llm_client.analyze("/tmp/test.png", None, cfg)
            mock_analyze.assert_called_once()
            assert result["trend_10min"] == "up"

    def test_dispatch_to_nvidia(self):
        cfg = {
            "provider": "nvidia",
            "nvidia": {
                "model": "thinkingmachines/inkling",
                "api_key": "test-key",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "temperature": 1,
                "top_p": 0.95,
                "max_tokens": 8192,
            },
        }
        with patch("chartwatch.llm_client.nvidia_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "down", "confidence": 0.8}
            result = llm_client.analyze("/tmp/test.png", None, cfg)
            mock_analyze.assert_called_once()
            assert result["trend_10min"] == "down"

    def test_unknown_provider_raises(self):
        cfg = {"provider": "unknown"}
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            llm_client.analyze("/tmp/test.png", None, cfg)

    def test_default_provider_is_ollama(self):
        cfg = {}
        with patch("chartwatch.llm_client.ollama_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "sideways", "confidence": 0.5}
            result = llm_client.analyze("/tmp/test.png", None, cfg)
            mock_analyze.assert_called_once()
            assert result["trend_10min"] == "sideways"

    def test_llm_model_overrides_ollama_model(self):
        cfg = {
            "provider": "ollama",
            "llm_model": "custom-model:latest",
            "ollama": {"model": "qwen3.5:9b", "host": "http://localhost:11434"},
        }
        with patch("chartwatch.llm_client.ollama_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            result = llm_client.analyze("/tmp/test.png", None, cfg)
            call_kwargs = mock_analyze.call_args
            assert call_kwargs.kwargs.get("model") == "custom-model:latest"

    def test_nvidia_uses_llm_model_when_set(self):
        cfg = {
            "provider": "nvidia",
            "llm_model": "custom-nvidia-model",
            "nvidia": {
                "model": "thinkingmachines/inkling",
                "api_key": "test-key",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "temperature": 1,
                "top_p": 0.95,
                "max_tokens": 8192,
            },
        }
        with patch("chartwatch.llm_client.nvidia_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            result = llm_client.analyze("/tmp/test.png", None, cfg)
            call_kwargs = mock_analyze.call_args
            assert call_kwargs.kwargs.get("model") == "custom-nvidia-model"