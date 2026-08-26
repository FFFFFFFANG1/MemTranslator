import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_cli_bootstrap_recovers_when_editable_pth_is_skipped(tmp_path):
    project_root = Path(__file__).parents[1]
    bootstrap_source = project_root / "src" / "memtranslator_bootstrap.py"
    site_packages = tmp_path / "site-packages"
    source_root = tmp_path / "checkout" / "src"
    package = source_root / "memtranslator"
    site_packages.mkdir()
    package.mkdir(parents=True)
    shutil.copy2(bootstrap_source, site_packages / bootstrap_source.name)
    (site_packages / "_editable_impl_memtranslator.pth").write_text(
        str(source_root))
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text(
        "def main():\n"
        "    print('bootstrap-ok')\n"
        "    return 0\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(site_packages)
    result = subprocess.run(
        [sys.executable, "-S", "-c",
         "import memtranslator_bootstrap as b; raise SystemExit(b.main())"],
        env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bootstrap-ok"
