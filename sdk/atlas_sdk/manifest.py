"""Plugin manifest validation for the SDK.

Mirrors the fields the Atlas runtime's ``PluginManifest`` actually consumes, so
``atlas validate`` enforces build == runtime strictness. Kept standalone (no
backend import) but field-compatible; the richer ``atlas_protocol.CapabilityManifest``
is the forward contract SDK authors can migrate to.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class ResourceRequirements(BaseModel):
    min_vram_mb: int = 0
    min_ram_mb: int = 0
    gpu_required: bool = False
    recommended_vram_mb: int = 0
    exclusive_gpu: bool = False


class AssetRefModel(BaseModel):
    """A content-addressed external asset (fat model / native lib)."""

    model_config = ConfigDict(protected_namespaces=())

    name: str
    sha256: str
    size: int = 0
    sources: List[str] = Field(default_factory=list)
    mode: str = "required"  # required | optional


class PluginManifest(BaseModel):
    """Validated plugin manifest matching what the Atlas runtime loads."""

    model_config = ConfigDict(protected_namespaces=())

    schema_version: str = "1.0"
    name: str
    version: str = "0.1.0"
    description: str
    entry_point: str = "wrapper.py"
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 50
    tags: List[str] = Field(default_factory=list)
    runtime: str = "python"  # python | gguf | onnx | native | generic
    license: str = ""
    optional_dependencies: List[str] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)          # small embedded files
    assets: List[AssetRefModel] = Field(default_factory=list)   # large content-addressed refs
    resource_requirements: ResourceRequirements = Field(default_factory=ResourceRequirements)
    self_test: str = ""
    fallback_used: str = ""
    to_model_projection: Dict[str, Any] = Field(default_factory=dict)
