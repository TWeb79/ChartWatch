"""Tests for chartwatch ollama_client, nvidia_client and llm_client modules."""

from unittest.mock import MagicMock, patch

import pytest

from chartwatch import llm_client, nvidia_client, ollama_client


class TestOllamaClientAnalyze:
    def test_analyze_returns_dict(self):
        mock_response = MagicMock()
        mock_response.__getitem__.return_value.__getitem__.return_value = (
            '{"assessment": "test", "trend_10min": "up", "confidence": 0.5, '
            '"open_position_action": null, "new_trade": null}'
        )

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response

        mock_client_cls = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        with patch("chartwatch.ollama_client.ollama.Client", mock_client_cls):
            with patch("chartwatch.ollama_client._encode_image") as mock_encode:
                mock_encode.return_value = "base64data"
                result = ollama_client.analyze(
                    screenshot_path="/tmp/test.png",
                    position_context=None,
                    model="qwen3.5:9b",
                    host="http://localhost:11434",
                )

        assert isinstance(result, dict)
        assert result["assessment"] == "test"
        assert result["trend_10min"] == "up"

    def test_analyze_passes_timeout_to_client_constructor_not_chat(self):
        """Regression: timeout must go to Client() constructor, not chat()."""
        mock_response = MagicMock()
        mock_response.__getitem__.return_value.__getitem__.return_value = (
            '{"assessment": "test", "trend_10min": "up", "confidence": 0.5, '
            '"open_position_action": null, "new_trade": null}'
        )

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response

        mock_client_cls = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        with patch("chartwatch.ollama_client.ollama.Client", mock_client_cls):
            with patch("chartwatch.ollama_client._encode_image") as mock_encode:
                mock_encode.return_value = "base64data"
                ollama_client.analyze(
                    screenshot_path="/tmp/test.png",
                    position_context=None,
                    model="qwen3.5:9b",
                    host="http://localhost:11434",
                )

        # Client constructor should receive timeout
        _, client_kwargs = mock_client_cls.call_args
        assert client_kwargs.get("timeout") == 120.0

        # chat() should NOT receive timeout
        _, chat_kwargs = mock_client_instance.chat.call_args
        assert "timeout" not in chat_kwargs

    def test_analyze_includes_balance_in_prompt(self):
        """Verify account_balance is included in the LLM prompt."""
        mock_response = MagicMock()
        mock_response.__getitem__.return_value.__getitem__.return_value = (
            '{"assessment": "test", "trend_10min": "up", "confidence": 0.5, '
            '"open_position_action": null, "new_trade": null}'
        )

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response

        mock_client_cls = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        with patch("chartwatch.ollama_client.ollama.Client", mock_client_cls):
            with patch("chartwatch.ollama_client._encode_image") as mock_encode:
                mock_encode.return_value = "base64data"
                ollama_client.analyze(
                    screenshot_path="/tmp/test.png",
                    position_context=None,
                    model="qwen3.5:9b",
                    host="http://localhost:11434",
                    account_balance={"balance": 1000.0, "currency": "EUR"},
                )

        _, chat_kwargs = mock_client_instance.chat.call_args
        messages = chat_kwargs.get("messages", [])
        user_msg = next(m for m in messages if m["role"] == "user")
        content = user_msg["content"]
        assert "1000.0" in content
        assert "EUR" in content

    def test_analyze_raises_on_empty_response(self):
        mock_response = MagicMock()
        mock_response.__getitem__.return_value.__getitem__.return_value = ""

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response

        mock_client_cls = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        with patch("chartwatch.ollama_client.ollama.Client", mock_client_cls):
            with patch("chartwatch.ollama_client._encode_image") as mock_encode:
                mock_encode.return_value = "base64data"
                with pytest.raises(ValueError, match="empty response"):
                    ollama_client.analyze(
                        screenshot_path="/tmp/test.png",
                        position_context=None,
                        model="qwen3.5:9b",
                        host="http://localhost:11434",
                    )

    def test_analyze_raises_on_invalid_json(self):
        mock_response = MagicMock()
        mock_response.__getitem__.return_value.__getitem__.return_value = "not json"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response

        mock_client_cls = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        with patch("chartwatch.ollama_client.ollama.Client", mock_client_cls):
            with patch("chartwatch.ollama_client._encode_image") as mock_encode:
                mock_encode.return_value = "base64data"
                with pytest.raises(ValueError, match="did not return valid JSON"):
                    ollama_client.analyze(
                        screenshot_path="/tmp/test.png",
                        position_context=None,
                        model="qwen3.5:9b",
                        host="http://localhost:11434",
                    )


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

    def test_analyze_uses_openai_image_format(self):
        """Verify NVIDIA uses OpenAI-compatible content array with image_url,
        not the Ollama-style 'images' key."""
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

        _, create_kwargs = mock_client_instance.chat.completions.create.call_args
        messages = create_kwargs.get("messages", [])
        user_msg = next(m for m in messages if m["role"] == "user")
        content = user_msg["content"]
        # Content must be an array (OpenAI format), not a plain string
        assert isinstance(content, list)
        # Must contain a text block
        text_block = next(c for c in content if c["type"] == "text")
        assert "Current position context" in text_block["text"]
        # Must contain an image_url block (not an "images" key)
        image_block = next(c for c in content if c["type"] == "image_url")
        assert "data:image/png;base64," in image_block["image_url"]["url"]
        assert "images" not in user_msg  # Ollama-style key must NOT exist

    def test_analyze_includes_balance_in_prompt(self):
        """Verify account_balance appears in the NVIDIA prompt."""
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
                nvidia_client.analyze(
                    screenshot_path="/tmp/test.png",
                    position_context=None,
                    model="thinkingmachines/inkling",
                    api_key="test-key",
                    base_url="https://integrate.api.nvidia.com/v1",
                    temperature=1,
                    top_p=0.95,
                    max_tokens=8192,
                    account_balance={"balance": 1000.0, "currency": "EUR"},
                )

        _, create_kwargs = mock_client_instance.chat.completions.create.call_args
        messages = create_kwargs.get("messages", [])
        user_msg = next(m for m in messages if m["role"] == "user")
        content = user_msg["content"]
        text_block = next(c for c in content if c["type"] == "text")
        assert "1000.0" in text_block["text"]
        assert "EUR" in text_block["text"]

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
        with patch("chartwatch.ollama_client.analyze") as mock_analyze:
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
        with patch("chartwatch.nvidia_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "down", "confidence": 0.8}
            result = llm_client.analyze("/tmp/test.png", None, cfg)
            mock_analyze.assert_called_once()
            assert result["trend_10min"] == "down"

    def test_default_provider_is_ollama(self):
        cfg = {}
        with patch("chartwatch.ollama_client.analyze") as mock_analyze:
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
        with patch("chartwatch.ollama_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            llm_client.analyze("/tmp/test.png", None, cfg)
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
        with patch("chartwatch.nvidia_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            llm_client.analyze("/tmp/test.png", None, cfg)
            call_kwargs = mock_analyze.call_args
            assert call_kwargs.kwargs.get("model") == "custom-nvidia-model"

    def test_unknown_provider_raises(self):
        cfg = {"provider": "unknown"}
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            llm_client.analyze("/tmp/test.png", None, cfg)

    def test_nvidia_uses_nvidia_model_not_ollama_model(self):
        """Verify NVIDIA provider gets the nvidia model, not the ollama model."""
        cfg = {
            "provider": "nvidia",
            "ollama": {"model": "qwen3.5:9b", "host": "http://localhost:11434"},
            "nvidia": {
                "model": "thinkingmachines/inkling",
                "api_key": "test-key",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "temperature": 1,
                "top_p": 0.95,
                "max_tokens": 8192,
            },
        }
        with patch("chartwatch.nvidia_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            llm_client.analyze("/tmp/test.png", None, cfg)
            call_kwargs = mock_analyze.call_args
            assert call_kwargs.kwargs.get("model") == "thinkingmachines/inkling"

    def test_timeout_passed_to_ollama_from_config(self):
        """Verify timeout from config is forwarded to the ollama client."""
        cfg = {
            "provider": "ollama",
            "ollama": {"model": "qwen3.5:9b", "host": "http://localhost:11434", "timeout": 45.0},
        }
        with patch("chartwatch.ollama_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            llm_client.analyze("/tmp/test.png", None, cfg)
            call_kwargs = mock_analyze.call_args
            assert call_kwargs.kwargs.get("timeout") == 45.0

    def test_timeout_passed_to_nvidia_from_config(self):
        """Verify timeout from config is forwarded to the nvidia client."""
        cfg = {
            "provider": "nvidia",
            "nvidia": {
                "model": "thinkingmachines/inkling",
                "api_key": "test-key",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "temperature": 1,
                "top_p": 0.95,
                "max_tokens": 8192,
                "timeout": 60.0,
            },
        }
        with patch("chartwatch.nvidia_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            llm_client.analyze("/tmp/test.png", None, cfg)
            call_kwargs = mock_analyze.call_args
            assert call_kwargs.kwargs.get("timeout") == 60.0

    def test_instruction_file_passed_to_nvidia(self):
        """Verify instruction_file from nvidia config is forwarded."""
        cfg = {
            "provider": "nvidia",
            "nvidia": {
                "model": "thinkingmachines/inkling",
                "api_key": "test-key",
                "base_url": "https://integrate.api.nvidia.com/v1",
                "temperature": 1,
                "top_p": 0.95,
                "max_tokens": 8192,
                "instruction_file": "tradingview.md",
            },
        }
        with patch("chartwatch.nvidia_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            llm_client.analyze("/tmp/test.png", None, cfg)
            call_kwargs = mock_analyze.call_args
            assert call_kwargs.kwargs.get("instruction_file") == "tradingview.md"

    def test_account_balance_passed_to_ollama(self):
        """Verify account_balance is forwarded to the ollama client."""
        cfg = {
            "provider": "ollama",
            "ollama": {"model": "qwen3.5:9b", "host": "http://localhost:11434"},
        }
        balance = {"balance": 1000.0, "currency": "EUR"}
        with patch("chartwatch.ollama_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "up", "confidence": 0.5}
            llm_client.analyze("/tmp/test.png", None, cfg, account_balance=balance)
            call_kwargs = mock_analyze.call_args
            assert call_kwargs.kwargs.get("account_balance") == balance

    def test_account_balance_passed_to_nvidia(self):
        """Verify account_balance is forwarded to the nvidia client."""
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
        balance = {"balance": 500.0, "currency": "USD"}
        with patch("chartwatch.nvidia_client.analyze") as mock_analyze:
            mock_analyze.return_value = {"assessment": "test", "trend_10min": "down", "confidence": 0.8}
            llm_client.analyze("/tmp/test.png", None, cfg, account_balance=balance)
            call_kwargs = mock_analyze.call_args
            assert call_kwargs.kwargs.get("account_balance") == balance
