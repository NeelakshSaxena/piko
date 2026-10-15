"""Minimal path guard. Does not install or modify anything."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PATHS = [
    ROOT / ".venv",
    ROOT / ".tools",
    ROOT / ".cache",
    ROOT / ".data",
    ROOT / ".tmp",
    ROOT / "artifacts",
    ROOT / ".gradle-home",
]

def main() -> int:
    print(f"Project root: {ROOT}")
    failures = []
    for path in PATHS:
        resolved = path.resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            failures.append(str(path))
        print(f"{'OK' if path.resolve().is_relative_to(ROOT) else 'FAIL'}  {path} -> {resolved}")
    if failures:
        print("FAIL: one or more project-managed paths resolve outside root.")
        return 1
    print("PASS: declared project-managed paths resolve beneath root.")
    print("Note: this checks declared paths, not every process/tool cache. Verify environment variables separately.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
