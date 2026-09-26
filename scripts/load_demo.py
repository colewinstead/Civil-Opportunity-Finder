"""Explicitly load fictional listings. Repeat runs update the same records."""
from scripts.scrape import run

if __name__ == "__main__":
    raise SystemExit(run("demo-fixture", allow_demo=True))
