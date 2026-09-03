import argparse
import asyncio
import sys
from datetime import datetime

from app.core.db import dispose_engine, get_session_factory
from app.jobs.daily import run_daily_job


def _parse_today(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cifra daily job (promotion + recurring)")
    parser.add_argument(
        "--today",
        default=None,
        help="ISO datetime override for the job clock (testing/simulation)",
    )
    args = parser.parse_args()

    today = _parse_today(args.today)

    async def _run() -> tuple[int, str]:
        result = await run_daily_job(get_session_factory(), today=today)
        return result.exit_code, result.to_json()

    exit_code, payload = asyncio.run(_run())
    print(payload)
    sys.stdout.flush()
    asyncio.run(dispose_engine())
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
