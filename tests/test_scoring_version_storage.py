"""Preserve legacy matches while preventing stale-policy cache reuse."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest

from test_profile_match_storage import sources
from job_application_assistant.profile_match_storage import load_profile_match, save_profile_match
from job_application_assistant.scoring_rules import SCORING_RULES_VERSION


def legacy_database(database, match):
    data = match.model_dump(mode="json")
    del data["scoring_rules_version"]
    payload = json.dumps(data)
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TABLE profile_matches (
            capture_uuid TEXT NOT NULL, requirements_sha256 TEXT NOT NULL,
            profile_sha256 TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(capture_uuid, requirements_sha256, profile_sha256)
        )""")
        connection.execute("INSERT INTO profile_matches VALUES (?, ?, ?, ?)", (
            str(match.capture_uuid), match.requirements_sha256, match.profile_sha256, payload))
    return payload


def test_legacy_read_is_not_current_and_does_not_migrate(tmp_path, sources):
    profile, requirements, match = sources
    database = tmp_path / "legacy.sqlite"
    payload = legacy_database(database, match)
    assert load_profile_match(database, profile, requirements) is None
    with sqlite3.connect(database) as connection:
        assert "scoring_rules_version" not in {row[1] for row in connection.execute("PRAGMA table_info(profile_matches)")}
        assert connection.execute("SELECT payload FROM profile_matches").fetchone()[0] == payload


def test_explicit_save_migrates_without_losing_legacy_payload(tmp_path, sources):
    profile, requirements, match = sources
    database = tmp_path / "legacy.sqlite"
    payload = legacy_database(database, match)
    assert save_profile_match(database, profile, requirements, match) == match
    assert load_profile_match(database, profile, requirements) == match
    with sqlite3.connect(database) as connection:
        rows = dict(connection.execute("SELECT scoring_rules_version, payload FROM profile_matches"))
    assert set(rows) == {"unversioned", SCORING_RULES_VERSION}
    assert rows["unversioned"] == payload


def test_other_version_retained_without_becoming_current(tmp_path, sources):
    profile, requirements, match = sources
    database = tmp_path / "matches.sqlite"
    save_profile_match(database, profile, requirements, match)
    old = match.model_copy(deep=True)
    old.scoring_rules_version = "documented-alignment-v0"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE profile_matches SET scoring_rules_version=?, payload=?",
                           (old.scoring_rules_version, old.model_dump_json()))
    assert load_profile_match(database, profile, requirements) is None
    with pytest.raises(ValueError, match="Scoring rules changed"):
        save_profile_match(database, profile, requirements, old)
    save_profile_match(database, profile, requirements, match)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM profile_matches").fetchone()[0] == 2


@pytest.mark.parametrize("problem", ["missing", "different"])
def test_version_column_and_payload_must_agree(tmp_path, sources, problem):
    profile, requirements, match = sources
    database = tmp_path / "matches.sqlite"
    save_profile_match(database, profile, requirements, match)
    data = match.model_dump(mode="json")
    if problem == "missing": del data["scoring_rules_version"]
    else: data["scoring_rules_version"] = "tampered-policy"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE profile_matches SET payload=?", (json.dumps(data),))
    with pytest.raises(ValueError, match="inconsistent scoring-rule version"):
        load_profile_match(database, profile, requirements)


def test_migration_rolls_back_on_failure(tmp_path, sources, monkeypatch):
    from job_application_assistant import profile_match_storage as storage
    profile, requirements, match = sources
    database = tmp_path / "legacy.sqlite"
    payload = legacy_database(database, match)
    migrate = storage._versioned_table
    def fail(connection):
        migrate(connection)
        raise sqlite3.OperationalError("simulated write interruption")
    monkeypatch.setattr(storage, "_versioned_table", fail)
    with pytest.raises(sqlite3.OperationalError):
        save_profile_match(database, profile, requirements, match)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT payload FROM profile_matches").fetchone()[0] == payload
        assert "scoring_rules_version" not in {row[1] for row in connection.execute("PRAGMA table_info(profile_matches)")}


def test_concurrent_migration_and_retry_keep_one_current_report(tmp_path, sources):
    profile, requirements, match = sources
    database = tmp_path / "legacy.sqlite"
    legacy_database(database, match)
    def save(_):
        return save_profile_match(database, profile, requirements, match)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert results == [match, match]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM profile_matches").fetchone()[0] == 2
