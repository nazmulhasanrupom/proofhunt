"""Profile types. 'freelancer' is a CV. 'ima' is an agency brief of an influencer marketing agency: it hunts brands that pay YouTube creators."""
from postgrest.exceptions import APIError

from ..db import get_db

FREELANCER, IMA = "freelancer", "ima"
KINDS = (FREELANCER, IMA)


def kind_of(profile_id: str | None) -> str:
    """The type of a profile. A database without migration 005 has only freelancer profiles."""
    if not profile_id:
        return FREELANCER
    try:
        rows = get_db().table("profiles").select("kind").eq("id", profile_id).execute().data
    except APIError as e:
        if e.code == "42703":  # undefined column: migration 005 has not been run
            return FREELANCER
        raise
    return (rows[0].get("kind") if rows else None) or FREELANCER
