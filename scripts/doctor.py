"""Read-only preflight; no downloads, installs, or system changes."""
from pathlib import Path
import os
import platform
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    print(f"Piko root: {ROOT}")
    print(f"OS: {platform.platform()}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Python executable: {sys.executable}")
    print(f"Inside project venv: {Path(sys.prefix).resolve().is_relative_to(ROOT)}")
    for name in ("git", "python", "python3", "node", "npm", "java", "adb", "docker"):
        found = shutil.which(name)
        print(f"{name}: {found or 'not found'}")
    for var in ("PIP_CACHE_DIR", "TMPDIR", "TEMP", "TMP", "npm_config_cache",
                "GRADLE_USER_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(var)
        print(f"{var}: {value or '(not set)'}")
    print("This doctor is informational only. It does not install or modify anything.")
    print("Review docs/LOCAL_ONLY_POLICY.md before setup.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
