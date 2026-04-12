"""
Build data-driven strategic penalty circuit rankings from official weekend data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


INPUT_PATH = Path("circuit_weekend_results_2026.csv")
OUTPUT_PATH = Path("strategic_circuit_rankings_2026.json")


def load_weekend_results(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["field_size"] = df.groupby(["season", "round"])["driver"].transform("count")
    df["effective_finish_position"] = df["finish_position"].fillna(df["field_size"] + 1)
    df["positions_gained"] = df["grid_position"] - df["effective_finish_position"]
    df["back_half_starter"] = df["grid_position"] > (df["field_size"] / 2)
    df["points_finish"] = df["finish_position"].fillna(999) <= 10
    df["top10_grid"] = df["grid_position"] <= 10
    df["fell_out_of_points"] = df["top10_grid"] & ~df["points_finish"]
    return df


def score_circuit(group: pd.DataFrame) -> dict:
    field_size = int(group["field_size"].iloc[0])
    back_half = group[group["back_half_starter"]]
    top10 = group[group["top10_grid"]]

    avg_gain = round(group["positions_gained"].mean(), 2)
    back_half_avg_gain = round(back_half["positions_gained"].mean(), 2) if not back_half.empty else 0.0
    back_half_points = int(back_half["points_finish"].sum())
    top10_dropouts = int(top10["fell_out_of_points"].sum())
    completion_rate = round(float((group["status"] == "classified").mean()), 3)

    score = round(
        (back_half_avg_gain * 2.2)
        + (back_half_points * 2.5)
        + (completion_rate * 8.0)
        - (top10_dropouts * 1.4),
        2,
    )

    expected_positions_lost = max(3, round((field_size / 3) - max(back_half_avg_gain, 0)))

    return {
        "circuit": group["circuit"].iloc[0],
        "grand_prix": group["grand_prix"].iloc[0],
        "round": int(group["round"].iloc[0]),
        "score": score,
        "reason": "",
        "expected_positions_lost": expected_positions_lost,
        "metrics": {
            "avg_positions_gained": avg_gain,
            "back_half_avg_gain": back_half_avg_gain,
            "back_half_points_finishers": back_half_points,
            "top10_dropouts": top10_dropouts,
            "completion_rate": completion_rate,
        },
        "sources": {
            "starting_grid": group["grid_source_url"].iloc[0],
            "race_result": group["race_source_url"].iloc[0],
        },
    }


def build_rankings(df: pd.DataFrame) -> dict:
    ranked = [
        score_circuit(group)
        for _, group in df.groupby(["season", "round", "grand_prix", "circuit"], sort=True)
    ]
    ranked.sort(key=lambda item: item["score"], reverse=True)

    if len(ranked) >= 4:
        split = max(2, len(ranked) // 2)
        best = ranked[:split]
        worst = list(reversed(ranked[-split:]))
    else:
        best = ranked[:2]
        worst = list(reversed(ranked[-1:]))

    for entry in best:
        entry["reason"] = (
            f"Better recovery than the other sampled 2026 circuits: back-half starters gained "
            f"{entry['metrics']['back_half_avg_gain']:+.1f} places on average and "
            f"{entry['metrics']['back_half_points_finishers']} still scored points."
        )

    for entry in worst:
        entry["reason"] = (
            f"More track-position sensitive than the other sampled 2026 circuits: back-half starters gained "
            f"{entry['metrics']['back_half_avg_gain']:+.1f} places on average and "
            f"{entry['metrics']['back_half_points_finishers']} reached the points."
        )

    return {
        "season": int(df["season"].max()),
        "generated_from": str(INPUT_PATH),
        "generated_rounds": sorted(df["round"].unique().tolist()),
        "methodology": {
            "summary": "Circuits are ranked by how recoverable poor starting positions were in official 2026 race weekends.",
            "inputs": [
                "Official starting grid",
                "Official race result",
            ],
            "scoring_factors": [
                "Average positions gained",
                "Average positions gained by back-half starters",
                "Back-half starters reaching the points",
                "Top-10 starters falling out of the points",
                "Classification rate",
            ],
        },
        "best_for_penalties": best,
        "worst_for_penalties": worst,
    }


def main():
    df = load_weekend_results(INPUT_PATH)
    rankings = build_rankings(df)
    OUTPUT_PATH.write_text(json.dumps(rankings, indent=2))
    print(f"Wrote {OUTPUT_PATH} using {len(df)} race-weekend rows from {INPUT_PATH}")


if __name__ == "__main__":
    main()
