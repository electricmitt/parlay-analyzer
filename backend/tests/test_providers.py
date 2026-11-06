from courtside.names import match_player, norm_name, norm_team
from courtside.providers.espn import ESPNClient, parse_box_stats
from courtside.providers.odds_api import parse_event_props

KEYS = ['minutes', 'points', 'fieldGoalsMade-fieldGoalsAttempted',
        'threePointFieldGoalsMade-threePointFieldGoalsAttempted', 'freeThrowsMade-freeThrowsAttempted', 'rebounds',
        'assists', 'turnovers', 'steals', 'blocks', 'offensiveRebounds', 'defensiveRebounds', 'fouls', 'plusMinus']


def test_parse_box_stats():
    out = parse_box_stats(KEYS, ['34', '32', '8-19', '1-5', '15-17', '4', '7', '4', '0', '2', '1', '3', '0', '+7'])
    assert out["minutes"] == 34 and out["pts"] == 32 and out["fg3m"] == 1 and out["fta"] == 17
    assert out["plus_minus"] == 7


def test_parse_box_stats_dashes():
    out = parse_box_stats(KEYS, ['--', '0', '0-0', '0-0', '0-0', '0', '0', '0', '0', '0', '0', '0', '0', '0'])
    assert out["minutes"] == 0 and out["pts"] == 0


def test_parse_event_iso_without_seconds():
    g = ESPNClient._parse_event({
        "id": "1", "date": "2026-11-01T20:30Z", "season": {"year": 2027, "type": 2},
        "status": {"type": {"name": "STATUS_FINAL"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": "97", "team": {"id": "19", "abbreviation": "ORL", "displayName": "Orlando Magic"}},
            {"homeAway": "away", "score": "108", "team": {"id": "2", "abbreviation": "BOS", "displayName": "Boston Celtics"}},
        ]}]})
    assert g.start_time.hour == 20 and g.home_score == 97 and g.away.abbr == "BOS"


def test_names():
    assert norm_name("Luka Dončić") == "luka doncic"
    assert norm_name("Jaren Jackson Jr.") == "jaren jackson"
    assert norm_team("Los Angeles Clippers") == norm_team("LA Clippers")
    cands = {"1": "Luka Dončić", "2": "Jaren Jackson Jr.", "3": "Jalen Williams", "4": "Jaylin Williams"}
    assert match_player("Luka Doncic", cands) == "1"
    assert match_player("Jaren Jackson", cands) == "2"
    assert match_player("J. Williams", cands) is None  # ambiguous -> never guess


def test_parse_event_props_pairs_sides():
    data = {"id": "ev1", "bookmakers": [{"key": "hardrockbet", "last_update": "2026-11-02T15:00:00Z", "markets": [
        {"key": "player_points", "last_update": "2026-11-02T15:00:00Z", "outcomes": [
            {"name": "Over", "description": "Jayson Tatum", "price": -115, "point": 27.5},
            {"name": "Under", "description": "Jayson Tatum", "price": -105, "point": 27.5},
            {"name": "Over", "description": "Jaylen Brown", "price": 100, "point": 22.5},
        ]},
        {"key": "unknown_market", "outcomes": []},
    ]}]}
    qs = {q.player_name: q for q in parse_event_props(data)}
    assert qs["Jayson Tatum"].over_price == -115 and qs["Jayson Tatum"].under_price == -105
    assert qs["Jayson Tatum"].market == "pts" and qs["Jayson Tatum"].book == "hardrockbet"
    assert qs["Jaylen Brown"].under_price is None
