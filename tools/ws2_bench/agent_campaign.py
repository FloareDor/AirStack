"""Run no-noise WS2 random, search, or agent-guided adaptive campaigns."""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import math
from pathlib import Path
import time

from agent_policies import policy_from_name
from agent_schema import ACTION_SCHEMA_VERSION, action_to_episode, validate_action
from campaign import clean_twin, verdict
from conditions import PATCH_POLICY
from episode import RUNTIME, atomic, fingerprint, resolved, run_episode
from feedback import summary
from mission import defaults
from operator_control import UserStop, wait_between_trials
from vulnerability_report import write_report


BACKEND_LABELS = {
    "random": "Seeded random sampling (no noise)",
    "search": "Deterministic result-guided search (no noise)",
    "agent_search": "Agent-guided deterministic search (no noise)",
}


def _config(policy_name, budget, seed, planner, retries, record_bags, timeout, goal_distance):
    mission = defaults(planner)
    if timeout is not None:
        mission["timeout"] = timeout
    if goal_distance is not None:
        mission["goal_distance"] = goal_distance
    return {
        "backend": policy_name,
        "label": BACKEND_LABELS[policy_name],
        "action_schema": ACTION_SCHEMA_VERSION,
        "profile": "delay_patch",
        "noise": "disabled",
        "budget": budget,
        "seed": seed,
        "planners": [planner],
        "retries": retries,
        "record_bags": record_bags,
        "mission": mission,
        "patch_policy": PATCH_POLICY,
    }


def _candidate(decision, config, index):
    action = validate_action(decision["action"])
    raw = action_to_episode(action, config["planners"][0], config["seed"],
                            f"{config['backend']} round {index + 1} {config['planners'][0]}", config["mission"])
    candidate = resolved(raw)
    decision = dict(decision)
    decision.update(condition=candidate["condition"], patch_start_s=candidate["patch_start_s"],
                    patch_duration_s=candidate["patch_duration_s"])
    return decision, candidate


def _load_json(path):
    return json.loads(path.read_text())


def run_adaptive_campaign(output, policy_name, budget=8, seed=42, planner="mononav", retries=1,
                          record_bags=False, pause_seconds=5, timeout=None, goal_distance=None,
                          provider=None):
    """Run one planner's paired campaign. Scheduled budget counts flights, not retries."""
    if policy_name not in BACKEND_LABELS:
        raise ValueError("policy must be random, search, or agent_search")
    if planner not in ("mononav", "kim"):
        raise ValueError("planner must be mononav or kim")
    if budget < 2 or budget % 2:
        raise ValueError("budget must be even: one clean/attack pair needs two flights")
    if retries not in (0, 1, 2):
        raise ValueError("retries must be 0, 1, or 2")
    if not 0 <= pause_seconds <= 60 or not math.isfinite(pause_seconds):
        raise ValueError("pause_seconds must be 0..60")

    root = Path(output).resolve()
    root.relative_to(RUNTIME.resolve())
    root.mkdir(parents=True, exist_ok=True)
    config = _config(policy_name, budget, seed, planner, retries, record_bags, timeout, goal_distance)
    resolved({"planner": planner, **config["mission"]})
    config_path = root / "config.json"
    if config_path.exists() and _load_json(config_path) != config:
        raise ValueError("resume configuration changed")
    atomic(config_path, config)

    global_lock = (RUNTIME / "adaptive.lock").open("w")
    fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    lock = (root / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    control_path = root / "operator_control.json"
    atomic(control_path, {"action": "run"})
    history_path = root / "history.json"
    history = _load_json(history_path) if history_path.exists() else []
    if len(history) > budget // 2:
        raise ValueError("saved history exceeds the configured budget")
    policy = policy_from_name(policy_name, seed, provider)
    completed = len(history) * 2
    actual_attempts = 0
    live_rows = []

    def publish(phase, decision=None, trial=None):
        value = {
            "backend": BACKEND_LABELS[policy_name],
            "target_planner": planner,
            "phase": phase,
            "budget": budget,
            "completed": completed,
            "actual_attempts": actual_attempts,
            "decision": decision,
            "trial": trial,
            "history": summary(history, live_rows),
            "output": str(root),
            "wall_time": time.time(),
            "mission": config["mission"],
            "profile": "delay_patch",
        }
        atomic(root / "presentation.json", value)
        atomic(RUNTIME / "live_campaign.json", value)

    def finish(phase, decision=None):
        report = write_report(root, history, live_rows, config, phase)
        table = summary(history, live_rows)
        atomic(root / "report.json", dict(table, analysis=report, actual_attempts=actual_attempts))
        if table["rows"]:
            with (root / "trials.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(table["rows"][0]))
                writer.writeheader()
                writer.writerows(table["rows"])
        publish(phase, decision)
        lock.close()
        global_lock.close()
        return history

    try:
        for index in range(len(history), budget // 2):
            round_root = root / f"round_{index + 1:02d}"
            round_root.mkdir(exist_ok=True)
            decision_path = round_root / "decision.json"
            if decision_path.exists():
                decision = _load_json(decision_path)
                decision["action"] = validate_action(decision["action"])
            else:
                decision = policy.choose_next(history, budget // 2 - len(history))
                decision["action"] = validate_action(decision["action"])
            decision, candidate = _candidate(decision, config, index)
            if decision_path.exists() and _load_json(decision_path) != decision:
                raise ValueError("saved decision differs from its resolved action")
            if not decision_path.exists():
                atomic(decision_path, decision)
            try:
                wait_between_trials(control_path, lambda phase: publish(phase, decision))
            except UserStop:
                return finish("stopped", decision)
            publish("selecting_configuration", decision)
            pair = {"planner": planner}
            for role, trial in (("clean", clean_twin(candidate)), ("perturbed", candidate)):
                try:
                    wait_between_trials(control_path, lambda phase: publish(phase, decision))
                except UserStop:
                    return finish("stopped", decision)
                attempts = []
                for attempt in range(retries + 1):
                    folder = round_root / planner / role / f"attempt_{attempt}"
                    publish("running", decision, {"planner": planner, "role": role, "round": index + 1,
                                                  "condition": trial["condition"], "directory": str(folder)})
                    if (folder / "result.json").exists():
                        result = _load_json(folder / "result.json")
                        if result["configuration_hash"] != fingerprint(trial):
                            raise ValueError("saved trial config changed")
                    elif folder.exists():
                        result = {"outcome": "infrastructure_error", "metrics": {}, "result_dir": str(folder),
                                  "termination": {"reason": "interrupted attempt"}}
                    else:
                        folder.parent.mkdir(parents=True, exist_ok=True)
                        result = run_episode(trial, folder, record_bag=record_bags, control_path=control_path)
                    attempts.append({"directory": str(folder), "outcome": result["outcome"]})
                    actual_attempts += 1
                    if result["outcome"] != "infrastructure_error":
                        break
                pair[role] = dict(result, attempts=attempts)
                completed += 1
                live_rows.append({"round": index + 1, "planner": planner, "role": role,
                                  "outcome": result["outcome"], **result["metrics"]})
                atomic(round_root / planner / (role + ".json"), pair[role])
                if result["outcome"] == "user_stopped":
                    return finish("stopped", decision)
                publish("trial_complete", decision, {"planner": planner, "role": role, "result": result})
                if pause_seconds:
                    time.sleep(pause_seconds)
            pair["verdict"] = verdict(pair["clean"], pair["perturbed"])
            history.append({"decision": decision, "pairs": [pair]})
            atomic(history_path, history)
            write_report(root, history, live_rows, config, "running")
            publish("complete" if completed == budget else "reviewing_results", decision)
        return finish("complete", history[-1]["decision"] if history else None)
    except Exception:
        lock.close()
        global_lock.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--policy", choices=sorted(BACKEND_LABELS), default="search")
    parser.add_argument("--budget", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--planner", choices=("mononav", "kim"), required=True)
    parser.add_argument("--infrastructure-retries", choices=(0, 1, 2), type=int, default=1)
    parser.add_argument("--record-bags", action="store_true")
    parser.add_argument("--review-seconds", type=float, default=5)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--goal-distance", type=float)
    args = parser.parse_args()
    run_adaptive_campaign(args.output, args.policy, args.budget, args.seed, args.planner,
                          args.infrastructure_retries, args.record_bags, args.review_seconds,
                          args.timeout, args.goal_distance)


if __name__ == "__main__":
    main()
