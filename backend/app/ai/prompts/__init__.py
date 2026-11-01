"""Prompt templates live in Markdown files next to this module.

The first line of each file is ``<!-- version: N -->``. The version is stored with
generated records, so any output can be traced back to the prompt that produced it.
Prompts hold instructions only; task data travels separately as untrusted JSON.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent
_VERSION_LINE = re.compile(r"^<!--\s*version:\s*(\S+)\s*-->\s*\n")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def version_label(self) -> str:
        return f"{self.name}@{self.version}"


@lru_cache
def load_prompt(name: str) -> Prompt:
    raw = (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    match = _VERSION_LINE.match(raw)
    if not match:
        raise ValueError(f"Prompt '{name}' must start with a version comment.")
    return Prompt(name=name, version=match.group(1), text=raw[match.end() :].strip())
