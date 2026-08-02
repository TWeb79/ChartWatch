"""LLM model utilities: vision capability detection and free-model filtering.

Separated from api.py so these functions can be unit-tested without importing
the full FastAPI app (which requires macOS Quartz bindings).

Also includes shared JSON parsing utilities used by both Ollama and NVIDIA
clients to strip markdown code fences that LLMs wrap around JSON output.
"""

from __future__ import annotations

# Patterns that indicate a model supports vision/multimodal input
VISION_MODEL_PATTERNS = (
    "vision", "vlm", "vl", "llava", "mllama", "bakllava", "xplora",
    "qwen-vl", "qwen2-vl", "qwen2.5-vl", "llama-vision", "nemotron-vl",
    "camb-ai", "moondream", "minicpm-v", "deepseek-vl",
)

# Known free (no paid tier) NVIDIA model prefixes — models from these
# organizations are available on the free tier of build.nvidia.com
NVIDIA_FREE_PREFIXES = (
    "meta/llama", "google/gemma", "qwen/", "deepseek-ai/deepseek",
    "mistralai/mistral", "ibm/granite", "microsoft/phi",
    "thamingbirds", "thinkingmachines", "nvidia/nemotron",
    "camb-ai", "abhishek-gpt", "sambanova",
)

# Additional NVIDIA vision model prefixes (models that support vision
# but don't have "vision" in their name). These are free-tier models
# known to be available for chat completions on build.nvidia.com.
# Note: We use name-pattern filtering rather than per-model API probing
# to avoid flooding the provider API (DDOS prevention). Models returned
# by the /v1/models endpoint may include entries that aren't deployable
# for a given account — users should select a model from the dropdown
# and if one fails with a 404, try another.
NVIDIA_VISION_PREFIXES = (
    "nvidia/nemotron-vl", "qwen/qwen2.5-vl", "qwen/qwen2-vl",
    "meta/llama-3.2", "meta/llama-3.3", "deepseek-ai/deepseek-v",
    "google/gemma-3", "camb-ai/",
)


def strip_markdown_code_fence(text: str) -> str:
    """Strip markdown code fences from LLM output before JSON parsing.

    LLMs often wrap their JSON response in markdown code fences like:
        ```json
        {"key": "value"}
        ```

    This function removes the leading and trailing fence delimiters so
    ``json.loads`` can parse the content directly.

    Args:
        text: Raw model response string, possibly wrapped in fences.

    Returns:
        Cleaned string with code fences removed, ready for JSON parsing.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines(keepends=True)
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "".join(lines).strip()
    return cleaned


async def filter_vision_models(models: list[str], provider: str) -> list[str]:
    """Filter a list of model names to only those supporting vision/multimodal input.

    Uses name-pattern matching rather than per-model API probing. This is a
    deliberate design choice to avoid flooding the provider API with test
    requests (DDOS prevention). The dummy test image and dummy.md are available
    for manual verification but are not used in automatic filtering.

    For Ollama: all locally installed models are free; we keep only vision-capable
    models (by name pattern) if any vision models exist, otherwise keep all.
    For NVIDIA: keep only free, vision-capable models (by name/owner patterns).

    Args:
        models: List of model identifier strings from the provider.
        provider: "ollama" or "nvidia".

    Returns:
        Filtered list of model strings, sorted alphabetically.
    """
    if provider == "ollama":
        # All Ollama models are locally installed (free). Keep vision-capable
        # models; if none match the vision pattern, return all (user may have
        # a custom model that supports images).
        vision = [m for m in models if any(p in m.lower() for p in VISION_MODEL_PATTERNS)]
        if vision:
            return sorted(vision)
        return sorted(models)

    if provider == "nvidia":
        # For NVIDIA, filter to free + vision-capable models.
        filtered = []
        for model in models:
            model_lower = model.lower()
            is_free = any(model_lower.startswith(p) for p in NVIDIA_FREE_PREFIXES)
            is_vision = any(p in model_lower for p in VISION_MODEL_PATTERNS)
            # Some vision models don't have "vision" in their name
            if not is_vision and any(model_lower.startswith(p) for p in NVIDIA_VISION_PREFIXES):
                is_vision = True
            if is_free and is_vision:
                filtered.append(model)
        return sorted(filtered)

    return sorted(models)
