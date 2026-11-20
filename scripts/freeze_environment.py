"""Freeze a verified project environment without local editable paths."""

import argparse
import re
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path


REQUIRED = (
    "langgraph", "langchain-openai", "langgraph-checkpoint-sqlite", "pydantic",
    "python-dotenv", "fastapi", "uvicorn", "python-docx", "reportlab", "pypdf",
    "pytest", "httpx",
)


def validated_pins(text):
    """Accept only portable exact pins; reject URLs, editables, and paths."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", line):
            raise ValueError("The environment includes a nonportable dependency. No file was written.")
        lines.append(line)
    if not lines:
        raise ValueError("The environment has no pinned dependencies.")
    return "\n".join(sorted(lines, key=str.casefold)) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("requirements.txt"))
    args = parser.parse_args()
    for name in REQUIRED:
        distribution(name)
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    frozen = subprocess.run([
        sys.executable, "-m", "pip", "freeze", "--exclude", "job-application-assistant",
    ], check=True, capture_output=True, text=True)
    pins = validated_pins(frozen.stdout)
    args.output.write_text(pins, encoding="utf-8")
    print(f"Saved {len(pins.splitlines())} exact dependency pins to {args.output}.")


if __name__ == "__main__":
    main()
