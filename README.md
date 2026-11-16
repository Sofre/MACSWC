# MACSWC

MACSWC is a multi-agent geopolitical simulation project focused on modeling conflict, diplomacy, and strategic decision-making in a Balkan war scenario. The system combines world-state tracking, AI-driven country agents, and orchestration logic to simulate how nations react to events, alliances, threats, and requests over time.

## Project Overview

The project is designed to:

- simulate countries as autonomous agents
- track diplomatic and military state over time
- evaluate actions with strategic reasoning
- support API-based and local-model execution
- provide a visual GUI and terminal-based run modes

## Main Components

- `WorldEngine/` - simulation engine, world state, orchestration, and game logic
- `agents_des/` - country, board, and secretary agent models
- `GUI/` - Pygame-based visualization interface
- `engine_tune/` - run scripts and environment configuration templates
- `initial_context_*.json` - scenario setup data for simulations

## Features

- Multi-country decision simulation
- Action registry and validation
- Dynamic world-state updates
- AI-powered country actions using LLM backends
- API and Ollama/local support
- Scenario-driven execution with JSON input files
- GUI and console output modes

## Setup

1. Create and activate a Python environment.
2. Install dependencies from the project requirements if available.
3. Configure your `.env` file using one of the provided templates in `engine_tune/`.
4. Run the project using the matching script in `engine_tune/`.

## Run Examples

```powershell
# API with GUI
.\engine_tune\run_api_gui_long.ps1

# API without GUI
.\engine_tune\run_api_long.ps1

# Local Ollama mode
.\engine_tune\run_local_long.ps1
```

## Important Notes

- Do not commit real API keys.
- Use `.env` template files for configuration.
- GUI mode is intended for API-based runs and is automatically disabled for local LLM setups.

## Version Control

Use the following commit message for the initial project upload:

```bash
git add .
git commit -m "Whole project commit"
```

## License

This project is for academic and simulation-development use unless otherwise specified by the repository owner.
