"""Run requirement extraction using the configured model."""

from pathlib import Path

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.job_requirements_agent import (
    create_requirements_extractor
)


ROOT = Path(__file__).resolve().parents[2]


class ExtractionConfigurationError(RuntimeError):
    """Required model settings are missing."""


def extract_capture_requirements(capture: JobCapture) -> JobRequirements:
    """Extract requirements on demand without changing the saved capture."""
    settings = dotenv_values(ROOT / ".env")
    api_key = (settings.get("OPENAI_API_KEY") or "").strip()
    model = (settings.get("OPENAI_MODEL") or "").strip()

    if not api_key or not model:
        raise ExtractionConfigurationError(
            "Set OPENAI_API_KEY and OPENAI_MODEL in the project's .env file."
        )

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        use_responses_api=True,
        timeout=60,
        max_retries=0,
        max_tokens=4096
    )

    extract = create_requirements_extractor(llm)
    return extract(capture)