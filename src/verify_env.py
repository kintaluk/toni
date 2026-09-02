"""Confirm the environment is wired up: core packages import cleanly and
API keys are loaded from .env. Never prints any key material."""

import os
import sys
from dotenv import load_dotenv


def main():
    load_dotenv()

    try:
        import parallel  # noqa: F401
        print("parallel-web package: imported OK")
    except ImportError:
        print("parallel-web package: FAILED to import")
        sys.exit(1)

    keys = ["PARALLEL_API_KEY", "WATCHMODE_API_KEY", "TMDB_API_KEY"]
    for key_name in keys:
        key_val = os.environ.get(key_name)
        if not key_val:
            print(f"{key_name}: NOT set (check your local .env file)")
        else:
            print(f"{key_name}: Loaded OK")


if __name__ == "__main__":
    main()
