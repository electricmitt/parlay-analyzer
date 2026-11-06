"""Identity resolution helpers. Matching is conservative: ambiguous names return None."""
from __future__ import annotations

import re
import unicodedata

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")

# Sportsbook / odds-feed team names that differ from ESPN display names.
TEAM_ALIASES = {
    "los angeles clippers": "la clippers",
    "la clippers": "la clippers",
}


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace(".", "").replace("'", "").replace("-", " ")
    s = _SUFFIX.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_team(name: str) -> str:
    n = norm_name(name)
    return TEAM_ALIASES.get(n, n)


def match_player(raw_name: str, candidates: dict[str, str]) -> str | None:
    """candidates: player_id -> display name (players on the two teams in the game).
    Exact normalised match first; then unique last-name + first-initial match."""
    target = norm_name(raw_name)
    exact = [pid for pid, n in candidates.items() if norm_name(n) == target]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    parts = target.split()
    if len(parts) < 2:
        return None
    fuzzy = []
    for pid, n in candidates.items():
        cp = norm_name(n).split()
        if len(cp) >= 2 and cp[-1] == parts[-1] and cp[0][:1] == parts[0][:1]:
            fuzzy.append(pid)
    return fuzzy[0] if len(fuzzy) == 1 else None
