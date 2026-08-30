import shutil
import subprocess
import sys


MIN_COMMITS = 3
MIN_OBJS = 10


def fail(message: str, code: int) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def main() -> None:
    gitleaks = shutil.which("gitleaks")
    if gitleaks is None:
        fail("gitleaks binary not found in PATH", 127)
    log = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
    )
    if log.returncode != 0:
        fail(log.stderr, log.returncode)
    commits = int(log.stdout.strip())
    if commits == 0:
        fail("history scan invalid: 0 commits reachable from HEAD", 2)
    if commits < MIN_COMMITS:
        fail(f"history scan invalid: only {commits} commits reachable", 2)
    cat = subprocess.run(
        ["git", "rev-list", "--objects", "HEAD"],
        capture_output=True,
    )
    if cat.returncode != 0:
        fail(cat.stderr.decode(errors="replace"), cat.returncode)
    objs = len([ln for ln in cat.stdout.decode(errors="replace").splitlines() if ln.strip()])
    if objs < MIN_OBJS:
        fail(f"history scan invalid: only {objs} objects enumerated", 2)
    pack = subprocess.run(
        ["git", "pack-objects", "--stdout", "--revs"],
        input=b"HEAD\n",
        capture_output=True,
    )
    if pack.returncode != 0:
        fail(pack.stderr.decode(errors="replace"), pack.returncode)
    if len(pack.stdout) == 0:
        fail("history scan invalid: empty packfile for reachable history", 2)
    scan = subprocess.run(
        [gitleaks, "git", "--config", ".gitleaks.toml", "--redact", "--no-banner"],
        input=pack.stdout,
        capture_output=True,
    )
    if scan.returncode not in (0, 1):
        fail(scan.stderr.decode(errors="replace"), scan.returncode)
    label = "clean" if scan.returncode == 0 else "LEAKS DETECTED"
    print(
        f"history secret scan: {label} "
        f"(commits={commits} objects={objs} pack_bytes={len(pack.stdout)})"
    )
    raise SystemExit(scan.returncode)


if __name__ == "__main__":
    main()
