"""Application entrypoint for running the simulation stack."""

import os

from WorldEngine.env_loader import load_env
from WorldEngine.world_orchistration import run_decision_action_layers


def main() -> None:
    """Starts the simulation application and runs the decision pipeline."""
    load_env()

    display_mode = os.getenv("DISPLAY_MODE", "short").strip().lower()
    if display_mode == "full":
        print("Initializing  ...  [DISPLAY_MODE=full — full agent pipeline]")
    else:
        print("Initializing  ...  [DISPLAY_MODE=short — country narrative]")

    rounds_env = os.getenv("SIM_ROUNDS", "2")
    try:
        rounds = int(rounds_env)
    except ValueError:
        rounds = 2

    scenario_file = os.getenv("SCENARIO_FILE")
    if scenario_file:
        run_decision_action_layers(rounds=rounds, scenario_file=scenario_file)
    else:
        run_decision_action_layers(rounds=rounds)


if __name__ == "__main__":
    main()
