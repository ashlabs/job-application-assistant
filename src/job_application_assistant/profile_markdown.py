"""Convert career profiles to and from a defined Markdown format."""

import re

from job_application_assistant.models import CareerProfile


_HEADER = "# Career Profile\n\n"

_PROFILE_BLOCK = re.compile(
    r"\A# Career Profile\n\n"
    r"```json\n"
    r"(?P<payload>.*?)"
    r"\n```\n?\Z",
    flags=re.DOTALL,
)


def profile_to_markdown(profile: CareerProfile) -> str:
    """Validate the current records and serialize them as Markdown."""
    validated = CareerProfile.model_validate(
        profile.model_dump(mode="json")
    )
    payload = validated.model_dump_json(indent=2)

    return f"{_HEADER}```json\n{payload}\n```\n"


def profile_from_markdown(markdown: str) -> CareerProfile:
    """Load a profile, rejecting unsupported structure or invalid data."""
    normalized = markdown.replace("\r\n", "\n")
    match = _PROFILE_BLOCK.fullmatch(normalized)

    if match is None:
        raise ValueError(
            "Expected a '# Career Profile' heading followed by "
            "one JSON code block."
        )

    return CareerProfile.model_validate_json(match.group("payload"))