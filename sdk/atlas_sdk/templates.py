"""Domain-neutral scaffolding templates for each supported .atlas runtime.

No default domain is assumed — the input schema is a generic typed object with a
TODO (the old SMILES/chemistry default is deleted). Model-backed runtimes load
their weights from **content-addressed external assets** (`__atlas_asset_paths__`),
not from inside the container — a fat model never lives in the signed `.atlas`.
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Manifest generation (keyed by runtime)
# ---------------------------------------------------------------------------

_GENERIC_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        # TODO: replace with your real inputs.
        "input": {"type": "object", "description": "TODO: describe this capability's input."},
    },
    "required": ["input"],
}

_RUNTIME_DEFAULTS = {
    "python": {"description": "TODO: describe what this plugin does.", "tags": []},
    "gguf": {"description": "TODO: describe your GGUF model plugin.", "tags": ["llm", "gguf"]},
    "onnx": {"description": "TODO: describe your ONNX model plugin.", "tags": ["ml", "onnx"]},
    "native": {"description": "TODO: describe your native code plugin.", "tags": ["native"]},
    "generic": {"description": "TODO: describe your plugin.", "tags": []},
}

# Runtimes that ship a large model → scaffold a content-addressed asset ref.
_MODEL_RUNTIMES = {
    "gguf": "model.gguf",
    "onnx": "model.onnx",
    "native": "libplugin.so",
}


def get_manifest(name: str, runtime: str) -> str:
    defaults = _RUNTIME_DEFAULTS.get(runtime, _RUNTIME_DEFAULTS["generic"])
    manifest = {
        "schema_version": "1.0",
        "name": name,
        "version": "0.1.0",
        "description": defaults["description"],
        "entry_point": "wrapper.py",
        "priority": 50,
        "tags": defaults["tags"],
        "runtime": runtime,
        "input_schema": _GENERIC_INPUT_SCHEMA,
        "output_schema": {
            "type": "object",
            "properties": {
                "result": {"type": "object"},
                "summary": {"type": "string"},
            },
        },
    }
    if runtime in _MODEL_RUNTIMES:
        # A large model is declared as a content-addressed external asset — the
        # .atlas stays small; `atlas build` fills in the real sha256/size/sources.
        manifest["assets"] = [
            {
                "name": _MODEL_RUNTIMES[runtime],
                "sha256": "TODO_64_hex_sha256_of_the_model_file",
                "size": 0,
                "sources": [
                    "file:///path/to/local/mirror/" + _MODEL_RUNTIMES[runtime],
                    "hf://ORG/REPO/" + _MODEL_RUNTIMES[runtime],
                ],
                "mode": "required",
            }
        ]
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Wrapper templates
# ---------------------------------------------------------------------------

WRAPPER_PYTHON = '''\
"""Atlas plugin wrapper for {name} (runtime: python)."""

from typing import Any, Dict, Optional


class {class_name}:

    async def invoke(
        self,
        arguments: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        args = arguments or {{}}

        # ----- YOUR LOGIC HERE -----
        result = {{"status": "not_implemented", "echo": args}}
        # ---------------------------

        return {{
            "result": result,
            "summary": f"{name} processed {{len(args)}} argument(s)",
        }}


PLUGIN = {class_name}()
'''

WRAPPER_GGUF = '''\
"""Atlas plugin wrapper for {name} (runtime: gguf).

The GGUF weights are a CONTENT-ADDRESSED external asset declared in
manifest.json under "assets" — not embedded in the .atlas. The loader resolves
+ hash-verifies it and injects the local path via ``__atlas_asset_paths__``.
"""

from pathlib import Path
from typing import Any, Dict, Optional


class {class_name}:

    def __init__(self):
        self._llm = None

    def _ensure_loaded(self):
        if self._llm is not None:
            return
        # {{name: verified local path}} — resolved from the manifest's asset refs.
        paths: Dict[str, Path] = __atlas_asset_paths__  # noqa: F821 — injected by loader
        model_path = paths.get("model.gguf")
        if not model_path:
            raise FileNotFoundError("content-addressed asset 'model.gguf' did not resolve")

        from llama_cpp import Llama
        self._llm = Llama(model_path=str(model_path), n_ctx=4096, n_gpu_layers=-1, verbose=False)

    async def invoke(
        self,
        arguments: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        args = arguments or {{}}
        prompt = args.get("prompt", "")
        self._ensure_loaded()
        out = self._llm(prompt, max_tokens=args.get("max_tokens", 256))
        text = out["choices"][0]["text"]
        return {{"result": {{"generated_text": text}}, "summary": f"{name} generated {{len(text)}} chars"}}


PLUGIN = {class_name}()
'''

WRAPPER_ONNX = '''\
"""Atlas plugin wrapper for {name} (runtime: onnx).

The ONNX model is a content-addressed external asset (manifest "assets"),
resolved + hash-verified by the loader and exposed via ``__atlas_asset_paths__``.
"""

from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


class {class_name}:

    def __init__(self):
        self._session = None

    def _ensure_loaded(self):
        if self._session is not None:
            return
        paths: Dict[str, Path] = __atlas_asset_paths__  # noqa: F821 — injected by loader
        model_path = paths.get("model.onnx")
        if not model_path:
            raise FileNotFoundError("content-addressed asset 'model.onnx' did not resolve")
        import onnxruntime as ort
        self._session = ort.InferenceSession(str(model_path))

    async def invoke(
        self,
        arguments: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        args = arguments or {{}}
        input_data = args.get("input", {{}})
        self._ensure_loaded()
        feeds = {{k: np.array(v, dtype=np.float32) for k, v in input_data.items()}}
        outputs = self._session.run(None, feeds)
        result = {{o.name: out.tolist() for o, out in zip(self._session.get_outputs(), outputs)}}
        return {{"result": result, "summary": f"{name} inference complete, {{len(result)}} output(s)"}}


PLUGIN = {class_name}()
'''

WRAPPER_NATIVE = '''\
"""Atlas plugin wrapper for {name} (runtime: native).

The shared library is a content-addressed external asset (manifest "assets"),
resolved + hash-verified by the loader and exposed via ``__atlas_asset_paths__``.
"""

import ctypes
from pathlib import Path
from typing import Any, Dict, Optional


class {class_name}:

    def __init__(self):
        self._lib = None

    def _ensure_loaded(self):
        if self._lib is not None:
            return
        paths: Dict[str, Path] = __atlas_asset_paths__  # noqa: F821 — injected by loader
        lib_path = next((p for p in paths.values() if p), None)
        if not lib_path:
            raise FileNotFoundError("no content-addressed native library resolved")
        self._lib = ctypes.CDLL(str(lib_path))
        # ----- CONFIGURE FUNCTION SIGNATURES HERE -----
        # self._lib.score.argtypes = [ctypes.c_char_p]
        # self._lib.score.restype = ctypes.c_double
        # ----------------------------------------------

    async def invoke(
        self,
        arguments: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        args = arguments or {{}}
        self._ensure_loaded()
        # ----- CALL YOUR NATIVE FUNCTION HERE -----
        result = {{"status": "not_implemented"}}
        # ------------------------------------------
        return {{"result": result, "summary": f"{name} native call complete"}}


PLUGIN = {class_name}()
'''

WRAPPER_GENERIC = '''\
"""Atlas plugin wrapper for {name} (runtime: generic).

Small bundled data files (if any) live under ``__atlas_assets__`` (a directory);
large content-addressed assets resolve into ``__atlas_asset_paths__`` (a map).
"""

from pathlib import Path
from typing import Any, Dict, Optional


class {class_name}:

    async def invoke(
        self,
        arguments: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        args = arguments or {{}}
        assets: Optional[Path] = __atlas_assets__  # noqa: F821 — injected by loader

        # ----- YOUR LOGIC HERE -----
        result = {{"assets_dir": str(assets) if assets else None, "status": "not_implemented"}}
        # ---------------------------

        return {{"result": result, "summary": f"{name} completed"}}


PLUGIN = {class_name}()
'''


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

WRAPPER_TEMPLATES = {
    "python": WRAPPER_PYTHON,
    "gguf": WRAPPER_GGUF,
    "onnx": WRAPPER_ONNX,
    "native": WRAPPER_NATIVE,
    "generic": WRAPPER_GENERIC,
}

SUPPORTED_RUNTIMES = list(WRAPPER_TEMPLATES.keys())


def get_wrapper(name: str, runtime: str) -> str:
    class_name = "".join(word.capitalize() for word in name.split("_")) + "Plugin"
    template = WRAPPER_TEMPLATES.get(runtime, WRAPPER_TEMPLATES["generic"])
    return template.format(name=name, class_name=class_name)
