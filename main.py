# Imports and environment setup
import requests
from datetime import datetime, timedelta
from functools import lru_cache
import time
from collections import defaultdict
import json
from typing import Any
import os

# Environment variables and API base URLs
API_KEY = os.environ["API_KEY"]
BASE = "https://americas.api.riotgames.com"


# Fetch latest patch version
@lru_cache
def get_latest_patch(patch: str) -> str:
    url = "https://ddragon.leagueoflegends.com/api/versions.json"
    res = requests.get(url)
    assert res.status_code == 200, f"Request failed with status code {res.status_code}"
    latest_patch = res.json()[0]
    return latest_patch


# Retrieve and champion data
@lru_cache
def get_champion_data(patch: str) -> dict:
    url = f"https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/champion.json"
    res = requests.get(url)
    assert res.status_code == 200, f"Request failed with status code {res.status_code}"
    data = res.json()["data"]
    champion_data = {}
    for key in data:
        champion_id = int(data[key]["key"])
        champion_name = data[key]["name"]
        champion_image_url = f"https://ddragon.leagueoflegends.com/cdn/15.11.1/img/champion/{data[key]['id']}.png"
        champion_data[champion_id] = {
            "name": champion_name,
            "image_url": champion_image_url,
        }

    return champion_data


# Lookup functions for champion name
def get_champion_name(champion_id: int, patch: str) -> str:
    latest_patch = get_latest_patch(patch)
    champion_data = get_champion_data(latest_patch)
    return (
        "" if champion_id not in champion_data else champion_data[champion_id]["name"]
    )


# Fetch PUUID from name and tag
def get_puuid(name: str, tag: str) -> str:
    url = f"{BASE}/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={API_KEY}"
    res = requests.get(url)
    time.sleep(1)
    assert res.status_code == 200, f"Request failed with status code {res.status_code}"
    puuid = res.json()["puuid"]
    return puuid


# Fetch summoner name from PUUID
def get_summoner_name(puuid: str) -> str:
    url = f"{BASE}/riot/account/v1/accounts/by-puuid/{puuid}?api_key={API_KEY}"
    res = requests.get(url)
    time.sleep(1)
    assert res.status_code == 200, f"Request failed with status code {res.status_code}"
    name = res.json()["gameName"]
    tag = res.json()["tagLine"]
    summoner_name = f"{name}#{tag}"
    return summoner_name


# Fetch summoner rank from PUUID
def get_summoner_rank(puuid: str) -> str:
    url = f"https://na1.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={API_KEY}"
    res = requests.get(url)
    time.sleep(1)
    assert res.status_code == 200, f"Request failed with status code {res.status_code}"
    if len(res.json()) == 0:
        return ""
    data = res.json()[0]
    rank = f"{data['tier']} {data['rank']}"
    return rank


# Retrieve all match IDs from the past year.
def get_match_ids(puuid: str) -> list[str]:
    match_ids = []
    one_year_ago = int((datetime.now() - timedelta(days=365)).timestamp())

    url = f"{BASE}/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={one_year_ago}&type=ranked&start=0&count=100&api_key={API_KEY}"
    res = requests.get(url)
    time.sleep(1)
    assert res.status_code == 200, f"Request failed with status code {res.status_code}"
    last_batch = res.json()

    if last_batch:
        match_ids += last_batch
        last_match_start_time = (
            get_match_data(match_id=last_batch[-1])["info"]["gameStartTimestamp"]
            // 1000
        )

        while last_match_start_time > one_year_ago:
            url = f"{BASE}/lol/match/v5/matches/by-puuid/{puuid}/ids?startTime={one_year_ago}&endTime={last_match_start_time}&type=ranked&start=0&count=100&api_key={API_KEY}"
            res = requests.get(url)
            time.sleep(1)
            assert res.status_code == 200, (
                f"Request failed with status code {res.status_code}"
            )
            last_batch = res.json()
            if not last_batch:
                break

            match_ids += last_batch
            last_match_start_time = (
                get_match_data(match_id=last_batch[-1])["info"]["gameStartTimestamp"]
                // 1000
            )

    return match_ids


# Get match_data
def get_match_data(match_id: str) -> dict:
    url = f"{BASE}/lol/match/v5/matches/{match_id}?api_key={API_KEY}"
    res = requests.get(url)
    time.sleep(1)
    assert res.status_code == 200, f"Request failed with status code {res.status_code}"
    match_data = res.json()
    return match_data


# Formats raw match data into a structured summary
def format_match_data(match_data: dict) -> dict:
    metadata, info = match_data["metadata"], match_data["info"]
    patch = ".".join(info["gameVersion"].split(".")[:2])

    formatted_match_data = {
        "match_id": metadata["matchId"],
        "start_time": datetime.fromtimestamp(info["gameStartTimestamp"] / 1000)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S %Z"),
        "duration": info["gameDuration"] // 60,
        "patch": patch,
        "wining_team": 0 if info["teams"][0]["win"] else 1,
        "teams": [[], []],
    }

    # Loop through all teammates
    for p in info["participants"]:
        # Name fallback if not present
        if "riotIdGameName" not in p or "riotIdTagline" not in p:
            summoner_name = get_summoner_name(puuid=p["puuid"])
        else:
            summoner_name = p["riotIdGameName"] + "#" + p["riotIdTagline"]

        summoner = {
            "puuid": p["puuid"],
            "name": summoner_name,
            "level": p["summonerLevel"],
            "champion": {
                "id": p["championId"],
                "name": get_champion_name(p["championId"], patch),
                "position": "support"
                if p["teamPosition"].lower() == "utility"
                else p["teamPosition"].lower(),
                "level": p["champLevel"],
                "kills": p["kills"],
                "deaths": p["deaths"],
                "assists": p["assists"],
                "gold": p["goldEarned"],
                "cs": p["totalMinionsKilled"] + p["neutralMinionsKilled"],
                "vision_score": p["visionScore"],
                "crowd_control_score": p["timeCCingOthers"],
                "damage_dealt": p["totalDamageDealt"],
                "damage_dealt_to_champions": p["totalDamageDealtToChampions"],
                "damage_taken": p["totalDamageTaken"],
            },
        }

        team = 0 if p["teamId"] == 100 else 1

        formatted_match_data["teams"][team].append(summoner)

    return formatted_match_data


# Aggregates champion performance stats for given matches
def get_match_stats(puuid: str, match_ids: list[str]) -> dict:
    tmp: defaultdict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "wins": 0,
            "matches": 0,
            "kills": 0,
            "deaths": 0,
            "assists": 0,
            "cs": 0,
            "gold_share": [],
            "damage_dealt_to_champions_share": [],
            "damage_taken_share": [],
            "vision_score_share": [],
            "kill_participation": [],
        }
    )

    valid_matches = 0
    print(f"Processing {len(match_ids)} matchs")

    # Loop through each match
    for i, match_id in enumerate(match_ids):
        match_data = get_match_data(match_id)
        match_data = format_match_data(match_data)

        if i == 0:
            end_time = match_data["start_time"]

        if i == len(match_ids) - 1:
            start_time = match_data["start_time"]

        # Skips matches resulted in early surrender
        if match_data["duration"] <= 5:
            continue

        # Find which team this puuid belongs to
        for team_id in range(2):
            for summoner in match_data["teams"][team_id]:
                if summoner["puuid"] == puuid:
                    puuid_team = team_id

        # Team totals for share calculation
        team_gold = 0
        team_damage_dealt_to_champions = 0
        team_damage_taken = 0
        team_vision_score = 0
        team_kills = 0

        for summoner in match_data["teams"][puuid_team]:
            team_gold += summoner["champion"]["gold"]
            team_damage_dealt_to_champions += summoner["champion"][
                "damage_dealt_to_champions"
            ]
            team_damage_taken += summoner["champion"]["damage_taken"]
            team_vision_score += summoner["champion"]["vision_score"]
            team_kills += summoner["champion"]["kills"]

        # Skips matches resulted in early surrender
        if (
            team_damage_dealt_to_champions == 0
            or team_damage_taken == 0
            or team_vision_score == 0
            or team_kills == 0
        ):
            print(f"Skipping match {i}: {match_id} - {match_data['start_time']}")
            continue

        print(f"Processing match {i}: {match_id} - {match_data['start_time']}")
        # match is valid
        valid_matches += 1

        # collect this ppuid's champion stats
        for summoner in match_data["teams"][puuid_team]:
            if summoner["puuid"] == puuid:
                champion_name = summoner["champion"]["name"]

                # Check if this PUUID is on the winning team
                if puuid_team == match_data["wining_team"]:
                    tmp[champion_name]["wins"] += 1

                tmp[champion_name]["matches"] += 1
                tmp[champion_name]["kills"] += summoner["champion"]["kills"]
                tmp[champion_name]["deaths"] += summoner["champion"]["deaths"]
                tmp[champion_name]["assists"] += summoner["champion"]["assists"]
                tmp[champion_name]["cs"] += summoner["champion"]["cs"]
                tmp[champion_name]["gold_share"].append(
                    summoner["champion"]["gold"] / team_gold
                )
                tmp[champion_name]["damage_dealt_to_champions_share"].append(
                    summoner["champion"]["damage_dealt_to_champions"]
                    / team_damage_dealt_to_champions
                )
                tmp[champion_name]["damage_taken_share"].append(
                    summoner["champion"]["damage_taken"] / team_damage_taken
                )
                tmp[champion_name]["vision_score_share"].append(
                    summoner["champion"]["vision_score"] / team_vision_score
                )
                tmp[champion_name]["kill_participation"].append(
                    (summoner["champion"]["kills"] + summoner["champion"]["assists"])
                    / team_kills
                )

    # Format output
    match_stats = defaultdict(dict)

    match_stats["metadata"] = {
        "name": get_summoner_name(puuid),
        "rank": get_summoner_rank(puuid),
        "start_time": start_time,
        "end_time": end_time,
        "unique_champions": len(tmp.keys()),
        "matches": valid_matches,
    }

    for key in tmp:
        match_stats["champions"][key] = {
            "wins": tmp[key]["wins"],
            "matches": tmp[key]["matches"],
            "win_rate": round(tmp[key]["wins"] / tmp[key]["matches"], 2),
            "avg_kills": round(tmp[key]["kills"] / tmp[key]["matches"], 2),
            "avg_deaths": round(tmp[key]["deaths"] / tmp[key]["matches"], 2),
            "avg_assists": round(tmp[key]["assists"] / tmp[key]["matches"], 2),
            "avg_cs": round(tmp[key]["cs"] / tmp[key]["matches"], 2),
            "avg_gold_share": round(
                sum(tmp[key]["gold_share"]) / len(tmp[key]["gold_share"]), 2
            ),
            "avg_damage_dealt_to_champions_share": round(
                sum(tmp[key]["damage_dealt_to_champions_share"])
                / len(tmp[key]["damage_dealt_to_champions_share"]),
                2,
            ),
            "avg_damage_taken_share": round(
                sum(tmp[key]["damage_taken_share"])
                / len(tmp[key]["damage_taken_share"]),
                2,
            ),
            "avg_vision_score_share": round(
                sum(tmp[key]["vision_score_share"])
                / len(tmp[key]["vision_score_share"]),
                2,
            ),
            "avg_kill_participation": round(
                sum(tmp[key]["kill_participation"])
                / len(tmp[key]["kill_participation"]),
                2,
            ),
        }

    # Sort by matches played and wins
    match_stats["champions"] = dict(
        sorted(
            match_stats["champions"].items(),
            key=lambda x: (x[1]["matches"], x[1]["wins"]),
            reverse=True,
        )
    )
    return match_stats


# Save match stats
def save_to_json(data: dict):
    with open("output.json", "w") as f:
        json.dump(data, f)


def analyze_player_match_history(name: str, tag: str):
    puuid = get_puuid(name=name, tag=tag)
    match_ids = get_match_ids(puuid)
    result = get_match_stats(puuid, match_ids)
    save_to_json(result)


analyze_player_match_history(name="AD KING", tag="LYON")
