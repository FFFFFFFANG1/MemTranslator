"""Deterministically insert OASST1 noise between authored E1 turns."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from pathlib import Path

from bench.suites.build_noise_pool import SOURCE_REVISION, SOURCE_URL

DEFAULT_SEED = 20260820


def _episode_language(episode: dict) -> str:
    text = "".join(turn["user_input"] for turn in episode["user_turns"])
    cjk = sum("\u3400" <= character <= "\u9fff" for character in text)
    return "zh" if cjk / max(1, len(text)) >= 0.2 else "en"


def _rng(seed: int, episode_id: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{episode_id}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def expand_episode(episode: dict, noise_by_language: dict[str, list[dict]], *,
                   seed: int = DEFAULT_SEED, min_noise: int = 5,
                   max_noise: int = 10) -> tuple[dict, dict]:
    if not 0 <= min_noise <= max_noise:
        raise ValueError("noise bounds must satisfy 0 <= min <= max")
    original_turns = episode["user_turns"]
    language = _episode_language(episode)
    rng = _rng(seed, episode["id"])
    gap_sizes = [rng.randint(min_noise, max_noise)
                 for _ in range(max(0, len(original_turns) - 1))]
    needed = sum(gap_sizes)
    pool = [row for row in noise_by_language.get(language, [])
            if row["text"] not in {
                turn["user_input"] for turn in original_turns}]
    if needed > len(pool):
        raise ValueError(
            f"{episode['id']} needs {needed} unique {language} noise prompts, "
            f"pool has {len(pool)}")
    sampled = rng.sample(pool, needed)

    turns, old_to_new, cursor = [], {}, 0
    for index, source_turn in enumerate(original_turns):
        authored = copy.deepcopy(source_turn)
        authored["seq"] = len(turns) + 1
        old_to_new[source_turn["seq"]] = authored["seq"]
        turns.append(authored)
        if index >= len(gap_sizes):
            continue
        for row in sampled[cursor:cursor + gap_sizes[index]]:
            turns.append({"seq": len(turns) + 1,
                          "user_input": row["text"]})
        cursor += gap_sizes[index]

    expanded = copy.deepcopy(episode)
    expanded["user_turns"] = turns
    for effect in expanded["ground_truth"]["lifecycle"]:
        effect["seq"] = old_to_new[effect["seq"]]
    expanded["ground_truth"]["state_checkpoints"] = [
        old_to_new[seq]
        for seq in expanded["ground_truth"]["state_checkpoints"]]
    manifest = {
        "episode": episode["id"], "language": language,
        "original_turns": len(original_turns), "noise_turns": needed,
        "expanded_turns": len(turns), "gap_min": min(gap_sizes, default=0),
        "gap_max": max(gap_sizes, default=0),
    }
    return expanded, manifest


def _load_pool(path: Path) -> dict[str, list[dict]]:
    by_language: dict[str, list[dict]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        by_language.setdefault(row["lang"], []).append(row)
    return by_language


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes-dir", type=Path, required=True)
    parser.add_argument("--noise-pool", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--min-noise", type=int, default=5)
    parser.add_argument("--max-noise", type=int, default=10)
    args = parser.parse_args()
    pool = _load_pool(args.noise_pool)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifests = []
    for path in sorted(args.episodes_dir.glob("e-*.json")):
        episode = json.loads(path.read_text())
        expanded, manifest = expand_episode(
            episode, pool, seed=args.seed,
            min_noise=args.min_noise, max_noise=args.max_noise)
        (args.output_dir / path.name).write_text(
            json.dumps(expanded, ensure_ascii=False, indent=1) + "\n")
        manifests.append(manifest)
    pool_hash = hashlib.sha256(args.noise_pool.read_bytes()).hexdigest()
    (args.output_dir / "noise_manifest.json").write_text(json.dumps({
        "source": "OpenAssistant/oasst1",
        "source_url": SOURCE_URL,
        "source_revision": SOURCE_REVISION,
        "license": "Apache-2.0",
        "noise_pool": str(args.noise_pool),
        "noise_pool_sha256": pool_hash,
        "seed": args.seed,
        "min_noise": args.min_noise,
        "max_noise": args.max_noise,
        "episodes": manifests,
    }, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(manifests, ensure_ascii=False))


if __name__ == "__main__":
    main()
