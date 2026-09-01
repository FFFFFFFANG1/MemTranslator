"""Console-entry bootstrap resilient to skipped editable ``.pth`` files."""
from __future__ import annotations

import json
import os
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse


def _editable_roots():
    try:
        direct_url = distribution("memtranslator").read_text("direct_url.json")
    except PackageNotFoundError:
        direct_url = None
    if direct_url:
        try:
            metadata = json.loads(direct_url)
            parsed = urlparse(metadata.get("url", ""))
            if metadata.get("dir_info", {}).get("editable") and parsed.scheme == "file":
                yield Path(unquote(parsed.path)) / "src"
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    site_packages = Path(__file__).resolve().parent
    for pth in site_packages.glob("*memtranslator*.pth"):
        for raw in pth.read_text(errors="ignore").splitlines():
            value = raw.strip()
            if not value or value.startswith("import "):
                continue
            path = Path(value).expanduser()
            yield path if path.is_absolute() else site_packages / path


def _load_cli_main():
    try:
        from memtranslator.cli import main
        return main
    except ModuleNotFoundError as exc:
        if exc.name not in {"memtranslator", "memtranslator.cli"}:
            raise

    for root in _editable_roots():
        root = root.resolve()
        if not (root / "memtranslator" / "cli.py").is_file():
            continue
        value = str(root)
        if value not in sys.path:
            sys.path.insert(0, value)
        inherited = os.environ.get("PYTHONPATH", "")
        paths = [part for part in inherited.split(os.pathsep) if part]
        if value not in paths:
            os.environ["PYTHONPATH"] = os.pathsep.join([value, *paths])
        package = sys.modules.get("memtranslator")
        if package is not None and getattr(package, "__file__", None) is None:
            sys.modules.pop("memtranslator", None)
        break

    from memtranslator.cli import main
    return main


def main() -> int:
    return _load_cli_main()()


if __name__ == "__main__":
    raise SystemExit(main())
