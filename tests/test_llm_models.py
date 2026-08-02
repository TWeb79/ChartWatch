"""Tests for LLM model availability + vision filtering.

These tests verify that the model filtering logic correctly identifies
vision-capable, free models and removes non-qualifying ones.

Import from chartwatch.llm_utils to avoid importing the full FastAPI app
(which requires macOS Quartz bindings).
"""

import json

import pytest

from chartwatch.llm_utils import (
    NVIDIA_FREE_PREFIXES,
    VISION_MODEL_PATTERNS,
    filter_vision_models,
)


class TestVisionModelPatterns:
    """Test that vision model patterns correctly identify vision-capable models."""

    def test_ollama_vision_model_detected(self):
        """Models with vision-related keywords should be identified."""  # Task 6: Vision pattern detection
        models = ["llava:latest", "qwen2.5-vl:latest", "mllama:latest", "bakllava:latest"]
        assert all(any(p in m.lower() for p in VISION_MODEL_PATTERNS) for m in models)

    def test_non_vision_model_not_matched(self):
        """Models without vision keywords should not match."""  # Task 6: Non-vision exclusion
        models = ["qwen2.5:7b", "gemma2:9b", "llama3:8b"]
        assert not any(any(p in m.lower() for p in VISION_MODEL_PATTERNS) for m in models)


class TestNvidiaFreePrefixes:
    """Test that NVIDIA free model prefixes correctly identify free models."""

    def test_known_free_models(self):
        """Known free model prefixes should match."""  # Task 6: Free model prefix detection
        free_models = [
            "meta/llama-3.3-70b-instruct",
            "google/gemma-3-27b",
            "qwen/qwen2.5-vl-7b",
            "thinkingmachines/inkling",
        ]
        assert all(
            any(m.lower().startswith(p) for p in NVIDIA_FREE_PREFIXES)
            for m in free_models
        )


class TestFilterVisionModelsOllama:
    """Test filter_vision_models for Ollama provider."""

    @pytest.mark.asyncio
    async def test_filters_to_vision_only(self):
        """Should return only vision-capable models when vision models are present."""  # Task 6: Ollama vision filtering
        models = ["qwen2.5:7b", "llava:latest", "gemma2:9b", "qwen2.5-vl:latest"]
        result = await filter_vision_models(models, "ollama")
        assert "llava:latest" in result
        assert "qwen2.5-vl:latest" in result
        assert "qwen2.5:7b" not in result
        assert "gemma2:9b" not in result

    @pytest.mark.asyncio
    async def test_returns_all_if_no_vision(self):
        """Should return all models if none match vision patterns."""  # Task 6: Ollama fallback to all models
        models = ["qwen2.5:7b", "gemma2:9b"]
        result = await filter_vision_models(models, "ollama")
        assert sorted(result) == sorted(["qwen2.5:7b", "gemma2:9b"])


class TestFilterVisionModelsNvidia:
    """Test filter_vision_models for NVIDIA provider."""

    @pytest.mark.asyncio
    async def test_filters_free_vision_models(self):
        """Should return only free + vision-capable models."""  # Task 6: NVIDIA free+vision filtering
        models = [
            "meta/llama-3.3-70b-instruct",
            "google/gemma-3-27b-it",
            "nvidia/nemotron-vl-340b",
            "premium/expensive-model",
        ]
        result = await filter_vision_models(models, "nvidia")
        assert "meta/llama-3.3-70b-instruct" in result
        assert "google/gemma-3-27b-it" in result
        assert "nvidia/nemotron-vl-340b" in result
        assert "premium/expensive-model" not in result

    @pytest.mark.asyncio
    async def test_excludes_paid_models(self):
        """Should exclude models from non-free prefixes."""  # Task 6: NVIDIA paid model exclusion
        models = ["premium/model-vision", "paid/enterprise-vision"]
        result = await filter_vision_models(models, "nvidia")
        assert "premium/model-vision" not in result
        assert "paid/enterprise-vision" not in result

    @pytest.mark.asyncio
    async def test_unknown_provider_returns_all(self):
        """Should return all models for unknown provider."""  # Task 6: Unknown provider passthrough
        models = ["model-a", "model-b"]
        result = await filter_vision_models(models, "unknown")
        assert sorted(result) == sorted(["model-a", "model-b"])


class TestMarkdownStripping:
    """Test that LLM responses wrapped in markdown code fences are parsed correctly."""  # Task 6: JSON markdown stripping

    def test_strips_json_code_fence(self):
        """Should strip ```json ... ``` fences and parse inner JSON."""
        from chartwatch.llm_utils import strip_markdown_code_fence
        raw = '```json\n{"key": "value"}\n```'
        cleaned = strip_markdown_code_fence(raw)
        assert json.loads(cleaned) == {"key": "value"}

    def test_strips_generic_code_fence(self):
        """Should strip generic ``` ... ``` fences."""
        from chartwatch.llm_utils import strip_markdown_code_fence
        raw = '```\n{"key": "value"}\n```'
        cleaned = strip_markdown_code_fence(raw)
        assert json.loads(cleaned) == {"key": "value"}

    def test_no_fence_passthrough(self):
        """Should return raw content unchanged if no code fences."""
        from chartwatch.llm_utils import strip_markdown_code_fence
        raw = '{"key": "value"}'
        cleaned = strip_markdown_code_fence(raw)
        assert json.loads(cleaned) == {"key": "value"}

    def test_strips_nested_json_with_markdown(self):
        """Should handle complex JSON wrapped in markdown."""
        from chartwatch.llm_utils import strip_markdown_code_fence
        raw = '```json\n{\n  "assessment": "test",\n  "confidence": 0.5\n}\n```'
        cleaned = strip_markdown_code_fence(raw)
        result = json.loads(cleaned)
        assert result["assessment"] == "test"
        assert result["confidence"] == 0.5
