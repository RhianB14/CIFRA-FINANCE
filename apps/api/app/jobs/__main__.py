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


async def main() -> int:
    parser = argparse.ArgumentParser(description="Cifra daily job (promotion + recurring)")
    parser.add_argument(
        "--today",
        default=None,
        help="ISO datetime override for the job clock (testing/simulation)",
    )
    args = parser.parse_args()

    today = _parse_today(args.today)
    result = await run_daily_job(get_session_factory(), today=today)
    print(result.to_json())
    sys.stdout.flush()
    await dispose_engine()
    return result.exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
