import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def fail(message: str, code: int) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def run_gitleaks(gitleaks: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [gitleaks, "dir", "--config", ".gitleaks.toml", "--redact", "--no-banner", *args]
    )


def main() -> None:
    gitleaks = shutil.which("gitleaks")
    if gitleaks is None:
        fail("gitleaks binary not found in PATH", 127)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        capture_output=True,
    )
    if archive.returncode != 0:
        fail(archive.stderr.decode(errors="replace"), archive.returncode)
    with tempfile.TemporaryDirectory(prefix="cifra-secrets-scan-") as tmp:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(tmp, filter="data")
        files = [p for p in Path(tmp).rglob("*") if p.is_file()]
        if len(files) == 0:
            fail("tracked-files scan empty: git archive produced no files", 2)
        total = sum(p.stat().st_size for p in files)
        if total == 0:
            fail("tracked-files scan empty: all extracted files are zero bytes", 2)
        scan = run_gitleaks(gitleaks, [tmp])
        label = "clean" if scan.returncode == 0 else "LEAKS DETECTED"
        print(
            f"tracked-files secret scan: {label} "
            f"(files={len(files)} bytes={total})"
        )
        raise SystemExit(scan.returncode)


if __name__ == "__main__":
    main()
