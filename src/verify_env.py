"""Confirm the environment is wired up: both core packages import cleanly and
PARALLEL_API_KEY is loaded from .env. Never prints the full key."""

from dotenv import load_dotenv
import os


def main():
    load_dotenv()

    import google.cloud.aiplatform  # noqa: F401
    import parallel  # noqa: F401

    print("google-cloud-aiplatform: imported OK")
    print("parallel: imported OK")

    key = os.environ.get("PARALLEL_API_KEY")
    if not key:
        print("PARALLEL_API_KEY: not set (create a local .env from .env.example)")
        return

    print(f"PARALLEL_API_KEY: {key[:4]}...")


if __name__ == "__main__":
    main()
