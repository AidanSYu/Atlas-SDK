"""ModelDescriptor — the model-agnostic brain socket.

This replaces every filename heuristic (the `'*Orchestrator*.gguf'` glob, the
`tool_format()`/`wants_no_think()` guesses, the hardcoded default). A brain is
selected by an explicit descriptor; Qwen-4B today, Atlas's own foundation
models tomorrow, a researcher's local model — the same socket. The core never
selects a cloud model; offline is a protocol-level guarantee.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .enums import Backend


class ModelDescriptor(BaseModel):
    """Everything the kernel needs to drive a brain, declared not inferred."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    backend: Backend
    model_id: str
    context_length: int
    dialect: str  # name of the registered wire-format Dialect (e.g. "qwen_chatml")
    supports_thinking: bool = False
    recommended_kv_quant: str = ""
    role_default: Literal["reason", "translate"] = "reason"
