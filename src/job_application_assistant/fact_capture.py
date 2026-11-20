"""Apply proposed profile facts without changing approved files."""

from typing import Literal
from pydantic import BaseModel, ConfigDict
from job_application_assistant.models import CareerProfile, ProfileFact


class FactUpdate(BaseModel):
    """One new fact or an explicit correction to an existing fact."""

    model_config = ConfigDict(extra="forbid")
    existing_fact_uuid: str | None
    category: Literal["preference", "skill", "project"] | None
    name: str | None
    statement: str | None


def apply_fact_update(profile: CareerProfile, update: FactUpdate) -> CareerProfile:
    """Preserve stable IDs and reject ambiguous implicit replacements."""
    data = profile.model_dump(mode="json")
    changes = update.model_dump(exclude={"existing_fact_uuid"}, exclude_none=True)
    if any(not value.strip() for value in changes.values()):
        raise ValueError("Profile facts cannot be blank.")
    if update.existing_fact_uuid is not None:
        matches = [i for i, fact in enumerate(data["facts"])
                   if fact["fact_uuid"] == update.existing_fact_uuid]
        if len(matches) != 1:
            raise ValueError("Selected profile fact is missing.")
        index = matches[0]
        data["facts"][index].update(changes)
    else:
        fact = ProfileFact.model_validate(changes)
        matches = [
            item for item in profile.facts
            if item.category == fact.category
            and " ".join(item.name.split()).casefold()
            == " ".join(fact.name.split()).casefold()
        ]
        if matches:
            if len(matches) == 1 and matches[0].statement == fact.statement:
                return CareerProfile.model_validate(data)
            raise ValueError("Clarify the existing fact before replacing it.")
        data["facts"].append(fact.model_dump(mode="json"))
    return CareerProfile.model_validate(data)
