#!/usr/bin/env python3
"""Build dist/coeos-memory.mcpb, the desktop extension for the Claude app.

An .mcpb file is a zip archive: the manifest, the server, and the
`coeos_memory` package the server imports.

    python3 scripts/build_extension.py
"""

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    namespace: dict = {}
    exec((ROOT / "coeos_memory" / "__init__.py").read_text(encoding="utf-8"), namespace)
    if manifest["version"] != namespace["__version__"]:
        raise SystemExit(f"version mismatch: manifest {manifest['version']}, "
                         f"package {namespace['__version__']}")

    target = ROOT / "dist" / "coeos-memory.mcpb"
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / "extension" / "manifest.json", "manifest.json")
        archive.write(ROOT / "extension" / "server" / "memory_server.py",
                      "server/memory_server.py")
        for source in sorted((ROOT / "coeos_memory").glob("*.py")):
            archive.write(source, f"server/coeos_memory/{source.name}")
    print(f"{target.relative_to(ROOT)} ({target.stat().st_size} bytes, version {manifest['version']})")


if __name__ == "__main__":
    main()
