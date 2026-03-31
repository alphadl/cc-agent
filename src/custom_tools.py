"""Custom tool loader.

Allows users to register additional Tool classes via config without changing core code.

Format:
- "some.module:MyToolClass"
- "some.module" (will load `EXTRA_TOOLS` list from that module if present)
"""
from __future__ import annotations

import importlib
from typing import Iterable

from .tools_impl.base import Tool


def load_tool_specs(specs: Iterable[str]) -> list[type[Tool]]:
    tools: list[type[Tool]] = []
    for spec in specs or []:
        spec = (spec or "").strip()
        if not spec:
            continue
        if ":" in spec:
            mod_name, attr = spec.split(":", 1)
            mod = importlib.import_module(mod_name)
            obj = getattr(mod, attr, None)
            if obj is None:
                raise ImportError(f"Custom tool not found: {spec}")
            if not isinstance(obj, type) or not issubclass(obj, Tool):
                raise TypeError(f"Custom tool must be a Tool subclass: {spec}")
            tools.append(obj)
            continue

        # module-only: expect EXTRA_TOOLS
        mod = importlib.import_module(spec)
        extra = getattr(mod, "EXTRA_TOOLS", None)
        if extra is None:
            raise ImportError(f"Module '{spec}' has no EXTRA_TOOLS; use 'module:ClassName'")
        for obj in list(extra):
            if not isinstance(obj, type) or not issubclass(obj, Tool):
                raise TypeError(f"EXTRA_TOOLS entries must be Tool subclasses: {obj!r}")
            tools.append(obj)

    # De-dup by name (keep first)
    seen: set[str] = set()
    deduped: list[type[Tool]] = []
    for t in tools:
        if getattr(t, "name", "") in seen:
            continue
        seen.add(getattr(t, "name", ""))
        deduped.append(t)
    return deduped

