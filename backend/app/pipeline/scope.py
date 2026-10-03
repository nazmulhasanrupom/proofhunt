"""Which companies a stage works on: all of one run, or an exact list (manual qualify)."""
from ..db import get_db


def chunks(items: list, n: int = 100):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def todo(run_id: str, statuses: list[str], ids: list[str] | None = None) -> list[dict]:
    db = get_db()
    if ids is None:
        return db.table("companies").select("*").eq("run_id", run_id).in_("status", statuses).execute().data
    out = []
    for part in chunks(ids):
        out += db.table("companies").select("*").in_("id", part).in_("status", statuses).execute().data
    return out
