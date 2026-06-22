"""LLM adapter package with fake client and prompt loading helpers."""

from llm.base import LLMClient, LLMMessage, LLMResponse
from llm.config import ModelConfig
from llm.errors import LLMAdapterError, LLMErrorCode, LLMErrorDetail
from llm.fake import FakeLLMClient
from llm.json_utils import extract_json_object
from llm.openai_compatible import OpenAICompatibleClient
from llm.prompt_loader import PromptLoader

__all__ = [
    "FakeLLMClient",
    "LLMAdapterError",
    "LLMClient",
    "LLMErrorCode",
    "LLMErrorDetail",
    "LLMMessage",
    "LLMResponse",
    "ModelConfig",
    "OpenAICompatibleClient",
    "PromptLoader",
    "extract_json_object",
]
