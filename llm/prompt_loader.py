"""Prompt file loader for narrow task prompts stored under prompts/."""

from __future__ import annotations

from pathlib import Path

from llm.errors import LLMAdapterError, LLMErrorCode, LLMErrorDetail

DEFAULT_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


class PromptLoader:
    """Load markdown prompts by name while preventing path traversal."""

    def __init__(self, base_dir: Path | str = DEFAULT_PROMPT_DIR) -> None:
        self.base_dir = Path(base_dir)

    def load(self, prompt_name: str) -> str:
        """Load a prompt by name, accepting names with or without .md suffix."""

        normalized_name = self._normalize_prompt_name(prompt_name)
        prompt_path = (self.base_dir / normalized_name).resolve()
        base_dir = self.base_dir.resolve()
        if not prompt_path.is_relative_to(base_dir):
            raise LLMAdapterError(
                LLMErrorDetail(
                    code=LLMErrorCode.PROMPT_NAME_INVALID,
                    message=f"Prompt name is not allowed: {prompt_name}",
                    details={"prompt_name": prompt_name},
                )
            )
        if not prompt_path.exists() or not prompt_path.is_file():
            raise LLMAdapterError(
                LLMErrorDetail(
                    code=LLMErrorCode.PROMPT_NOT_FOUND,
                    message=f"Prompt file not found: {normalized_name}",
                    details={"prompt_name": prompt_name, "path": str(prompt_path)},
                )
            )
        return prompt_path.read_text(encoding="utf-8")

    @staticmethod
    def _normalize_prompt_name(prompt_name: str) -> str:
        """Return a sanitized prompt filename."""

        normalized_name = prompt_name if prompt_name.endswith(".md") else f"{prompt_name}.md"
        if Path(normalized_name).name != normalized_name:
            raise LLMAdapterError(
                LLMErrorDetail(
                    code=LLMErrorCode.PROMPT_NAME_INVALID,
                    message=f"Prompt name is not allowed: {prompt_name}",
                    details={"prompt_name": prompt_name},
                )
            )
        return normalized_name
