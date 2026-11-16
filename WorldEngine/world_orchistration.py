import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents_des.board_agent_model import BoardAgentModel, BoardEvaluation
from agents_des.country_agent_model import CountryAgentConfig, CountryAgentModel
from agents_des.secretary_agent_model import SecretaryAgentModel
from WorldEngine.action_registry import ACTION_REGISTRY
from WorldEngine.engine import SimulationEngine
from WorldEngine.iron_ledger import IronLedger
from WorldEngine.world_state import CountryProfile, WorldState

# Optional Pygame GUI
_GUI_AVAILABLE = False
try:
    import pygame
    from GUI.pygame_ui import close_gui, get_gui, init_gui
    _GUI_AVAILABLE = True
except ImportError:
    pygame = None

    def init_gui(scenario_file: str = "") -> Optional[Any]:
        return None

    def get_gui() -> Optional[Any]:
        return None

    def close_gui() -> None:
        return None


DEFAULT_SCENARIO_FILE = "initial_context_balkan_wars_scenario_2.json"

# Orchistratior of World Simiulation


def _process_gui_events() -> None:
    """
    Process GUI events without rendering to keep window responsive during LLM calls.
    Call this periodically during long-running operations.
    """
    if not _GUI_AVAILABLE:
        return
    gui = get_gui()
    if gui and hasattr(gui, 'process_events_only'):
        gui.process_events_only()


DEFAULT_ACTION_GOAL_ALIGNMENT: Dict[str, Dict[str, float]] = {
    "request_military_alliance": {"alliance_cohesion": 0.9, "deterrence": 0.5, "de_escalation": 0.2},
    "publish_military_alliance": {"alliance_cohesion": 1.0, "deterrence": 0.6},
    "declare_war": {"deterrence": 0.8, "territorial_gain": 0.7, "de_escalation": -0.8},
    "sanction": {"deterrence": 0.5, "economic_stability": -0.3},
    "trade_agreement": {"economic_stability": 0.8, "de_escalation": 0.5},
    "present_peace_agreement": {"de_escalation": 1.0, "economic_stability": 0.3},
    "accept_request": {"alliance_cohesion": 0.7, "de_escalation": 0.4},
    "reject_request": {"alliance_cohesion": -0.5, "deterrence": 0.2},
}

DEFAULT_DECISION_WEIGHTS: Dict[str, float] = {
    "goal_alignment": 0.35,
    "situation_fit": 0.35,
    "relationship_fit": 0.2,
    "constraint_compliance": 0.1,
}

SECRETARY_AGENT = SecretaryAgentModel.from_env()
BOARD_AGENT = BoardAgentModel.from_env()


def _refresh_runtime_agents() -> None:
    """
    Rebuilds runtime agent singletons from current environment variables.
    This is required because module import can happen before .env is loaded.
    """
    global SECRETARY_AGENT, BOARD_AGENT
    SECRETARY_AGENT = SecretaryAgentModel.from_env()
    BOARD_AGENT = BoardAgentModel.from_env()


def _print_agent_runtime_diagnostics() -> None:
    """
    Prints a compact, non-secret runtime status line for each agent.
    """
    country_cfg = CountryAgentModel.from_env().config
    secretary_cfg = SECRETARY_AGENT.config
    board_cfg = BOARD_AGENT.config

    country_key_ok = bool(country_cfg.api_key)
    secretary_key_ok = bool(secretary_cfg.api_key)
    board_key_ok = bool(board_cfg.api_key)

    print("[AGENTS] Runtime configuration:")
    print(
        "  - Country: "
        f"enabled={country_cfg.enabled} "
        f"backend={country_cfg.backend} "
        f"api_key={'set' if country_key_ok else 'missing'}"
    )
    print(
        "  - Secretary: "
        f"enabled={secretary_cfg.enabled} "
        f"provider={secretary_cfg.provider} "
        f"api_key={'set' if secretary_key_ok else 'missing'}"
    )
    print(
        "  - Board: "
        f"enabled={board_cfg.enabled} "
        f"llm_enabled={board_cfg.llm_enabled} "
        f"provider={board_cfg.provider} "
        f"api_key={'set' if board_key_ok else 'missing'}"
    )


def _agent_debug_enabled() -> bool:
    """
    Returns whether per-country agent mapping debug logs are enabled.
    """
    return os.getenv("AGENT_DEBUG", "0").strip().lower() in {"1", "true", "yes"}


def _all_agents_use_api() -> bool:
    """
    Checks if all agents (Country, Secretary, Board) are configured to use API (not local/ollama).
    Returns True only if all agents are using remote API endpoints.
    GUI should only be enabled when this returns True to avoid performance issues.
    """
    # Check Country Agent backend
    country_backend = os.getenv("COUNTRY_AGENT_BACKEND", "hf_api").strip().lower()
    country_enabled = os.getenv("COUNTRY_AGENT_ENABLED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
    
    if country_enabled and country_backend not in {"hf_api", "groq_api", "groq", "openrouter_api", "openrouter"}:
        # Country agent is using local backend (ollama)
        return False
    
    # Secretary and Board agents always use API when enabled, so no additional checks needed
    # (They use remote API providers: OpenAI, Groq, or OpenRouter)
    
    return True


def _log_agent_registry(country_agents: Dict[str, CountryAgentModel]) -> None:
    """
    Prints current country-to-agent instance mapping for runtime verification.
    """
    if not _agent_debug_enabled():
        return

    print("[AGENT_DEBUG] Country agent mapping initialized:")
    for country_name in sorted(country_agents.keys()):
        print(f"[AGENT_DEBUG] {country_name} -> instance_id={id(country_agents[country_name])}")


def build_country_agents(engine: SimulationEngine) -> Dict[str, CountryAgentModel]:
    """
    Builds one CountryAgentModel instance per country for multi-agent orchestration.
    """
    template = CountryAgentModel.from_env().config
    agents: Dict[str, CountryAgentModel] = {}

    for country in engine.world_state.country_profiles:
        agents[country.name] = CountryAgentModel(
            CountryAgentConfig(
                backend=template.backend,
                enabled=template.enabled,
                api_key=template.api_key,
                model=template.model,
                temperature=template.temperature,
                timeout_seconds=template.timeout_seconds,
                ollama_url=template.ollama_url,
                ollama_model=template.ollama_model,
                max_output_tokens=template.max_output_tokens,
                max_candidate_actions=template.max_candidate_actions,
                max_relationship_rows=template.max_relationship_rows,
                max_country_profiles=template.max_country_profiles,
                max_global_logs=template.max_global_logs,
                max_inbox_events=template.max_inbox_events,
            )
        )

    _log_agent_registry(agents)
    return agents


def load_initial_context(filename: str = DEFAULT_SCENARIO_FILE) -> Dict[str, Any]:
    """
    Loads an initial scenario context JSON file from the project root.
    """
    project_root = Path(__file__).resolve().parent.parent
    scenario_path = project_root / filename
    with open(scenario_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _profile_for_actor(name: str, risk_tolerance: str) -> CountryProfile:
    """
    Builds a deterministic CountryProfile for an actor using risk posture presets.
    """
    base_population = 6_000_000
    base_army = 300_000
    morale = 0.72
    national_unity = 0.68
    equipment_quality = 0.65

    if risk_tolerance == "high":
        morale = 0.78
        equipment_quality = 0.72
    elif risk_tolerance == "low":
        morale = 0.68
        national_unity = 0.74

    return CountryProfile(
        name,
        population=base_population,
        army_size=base_army,
        morale=morale,
        national_unity=national_unity,
        equipment_quality=equipment_quality,
    )


def build_default_engine(initial_context: Dict[str, Any]) -> SimulationEngine:
    """
    Creates the world engine from scenario context and seeds baseline relationships.
    """
    actors = initial_context.get("actors", {})
    profiles: List[CountryProfile] = []
    for actor_name, actor_meta in actors.items():
        risk = actor_meta.get("risk_tolerance", "medium")
        profiles.append(_profile_for_actor(actor_name, risk))

    world = WorldState(profiles, global_context=initial_context)
    engine = SimulationEngine(world_state=world)

    relationship_baseline = initial_context.get("relationship_baseline", {})
    for pair, weight in relationship_baseline.items():
        names = pair.split("-", 1)
        if len(names) != 2:
            continue
        left = names[0]
        right = names[1]
        if world.diplomacy_graph.has_node(left) and world.diplomacy_graph.has_node(right):
            world.diplomacy_graph.add_edge(left, right, weight=float(weight))

    world.update_dataframe()
    return engine


def _all_other_actors(engine: SimulationEngine, actor: str) -> List[str]:
    """
    Returns all actor names except the current actor.
    """
    return [cp.name for cp in engine.world_state.country_profiles if cp.name != actor]


def _recent_private_outgoing_actions(engine: SimulationEngine, actor: str, lookback: int = 20) -> List[Dict[str, Any]]:
    """
    Collects recent private actions authored by actor from all country inboxes.
    """
    found: List[Dict[str, Any]] = []
    for inbox_events in engine.world_state.country_inboxes.values():
        if not isinstance(inbox_events, list):
            continue
        for event in inbox_events:
            if not isinstance(event, dict):
                continue
            action = event.get("action")
            if not isinstance(action, dict):
                continue
            if action.get("actor") == actor:
                found.append(action)

    if lookback <= 0:
        return found
    return found[-lookback:]


def _edge_weight(engine: SimulationEngine, actor: str, target: str) -> float:
    """
    Gets current diplomacy weight between two actors.
    """
    edge_data = engine.world_state.diplomacy_graph.get_edge_data(actor, target, default={"weight": 0.0})
    if isinstance(edge_data, dict):
        return float(edge_data.get("weight", 0.0))
    return 0.0


def _situation_tags(engine: SimulationEngine, actor: str) -> List[str]:
    """
    Derives lightweight situation tags from relationship posture and inbox pressure.
    """
    others = _all_other_actors(engine, actor)
    if not others:
        return ["isolated"]

    weights = [_edge_weight(engine, actor, target) for target in others]
    avg_weight = sum(weights) / len(weights)
    tags: List[str] = []
    if avg_weight <= -0.4:
        tags.append("front_pressure_high")
    elif avg_weight >= 0.4:
        tags.append("alliance_momentum_high")
    else:
        tags.append("balance_uncertain")

    inbox = engine.world_state.country_inboxes.get(actor, [])
    if inbox:
        tags.append("incoming_requests_present")
    return tags


def _goal_tags_for_actor(initial_context: Dict[str, Any], actor: str) -> Dict[str, float]:
    """
    Returns weighted goal tags for an actor from context or fallback defaults.
    """
    goal_model = initial_context.get("goal_model", {})
    actor_goals = goal_model.get("actors", {}).get(actor, {}).get("goal_tags")
    if isinstance(actor_goals, dict):
        return {str(k): float(v) for k, v in actor_goals.items()}
    return {
        "deterrence": 0.35,
        "alliance_cohesion": 0.25,
        "economic_stability": 0.2,
        "de_escalation": 0.2,
    }


def build_agent_input_packet(
    engine: SimulationEngine,
    initial_context: Dict[str, Any],
    actor: str,
    round_number: int,
) -> Dict[str, Any]:
    """
    Builds the structured, prompt-light input packet consumed by decision logic.
    """
    actor_meta = initial_context.get("actors", {}).get(actor, {})
    others = _all_other_actors(engine, actor)

    # Relationship snapshot: all known pairs and their current edge weights
    relationship_snapshot = []
    for target in others:
        relationship_snapshot.append({"target": target, "weight": _edge_weight(engine, actor, target)})

    # Country profiles snapshot: public metrics for every actor
    # Should this be public knowledge ? 
    country_profiles_snapshot: List[Dict[str, Any]] = []
    for _, row in engine.world_state.df.iterrows():
        country_profiles_snapshot.append(
            {
                "name": row["name"],
                "army_size": row["army_size"],
                "combat_power": row["combat_power"],
                "morale": row["morale"],
                "national_unity": row["national_unity"],
                "stability_index": row["stability_index"],
            }
        )

    # Private inbox: messages and requests addressed only to this actor
    private_inbox = engine.world_state.country_inboxes.get(actor, [])
    private_outgoing_history = _recent_private_outgoing_actions(engine, actor, lookback=20)

    return {
        # WHO I AM
        "agent_identity": {
            "name": actor,
            "risk_tolerance": actor_meta.get("risk_tolerance", "medium"),
            "doctrine": actor_meta.get("doctrine", "general"),
        },
        # HOW I DECIDE
        "goals": {
            "goal_tags": _goal_tags_for_actor(initial_context, actor),
        },
        # WHAT I KNOW (World)
        "world_knowledge": {
            "round": round_number,
            "country_profiles": country_profiles_snapshot,
            "relationship_snapshot": relationship_snapshot,
            "global_logs": engine.world_state.global_logs[-20:],  # last 20 events to keep packet compact
            "private_outgoing_history": private_outgoing_history,
        },
        # WHAT I RECEIVED (Private)
        "private_inbox": private_inbox,
        # WHAT I CAN DO
        "capabilities": {
            "allowed_actions": initial_context.get("rules_brief", {}).get("allowed_actions", []),
            "weight_effects": initial_context.get("rules_brief", {}).get("weight_effects", {}),
            "situation_tags": _situation_tags(engine, actor),
        },
        # LEGACY: keep current_situation key so _build_candidate_actions still resolves correctly
        "current_situation": {
            "round": round_number,
            "inbox": private_inbox,
            "relationship_snapshot": relationship_snapshot,
            "situation_tags": _situation_tags(engine, actor),
        },
        "rules": {
            "allowed_actions": initial_context.get("rules_brief", {}).get("allowed_actions", []),
            "weight_effects": initial_context.get("rules_brief", {}).get("weight_effects", {}),
        },
        "decision_weights": initial_context.get("goal_model", {}).get("decision_weights", DEFAULT_DECISION_WEIGHTS),
    }


def _build_candidate_actions(packet: Dict[str, Any], actor: str) -> List[Dict[str, Any]]:
    """
    Builds candidate actions from rules, inbox, and known relationship targets.
    """
    allowed_actions = set(packet.get("rules", {}).get("allowed_actions", []))
    relation_rows = packet.get("current_situation", {}).get("relationship_snapshot", [])
    inbox = packet.get("current_situation", {}).get("inbox", [])

    candidates: List[Dict[str, Any]] = []

    for event in inbox:
        request_id = event.get("request_id")
        origin_action = event.get("action", {}) if isinstance(event.get("action", {}), dict) else {}
        origin_actor = origin_action.get("actor")
        if not request_id or not origin_actor:
            continue
        if "accept_request" in allowed_actions:
            candidates.append({"type": "accept_request", "actor": actor, "target": origin_actor, "request_id": request_id})
        if "reject_request" in allowed_actions:
            candidates.append({"type": "reject_request", "actor": actor, "target": origin_actor, "request_id": request_id})

    for rel in relation_rows:
        target = rel.get("target")
        weight = float(rel.get("weight", 0.0))
        if not target:
            continue

        if "sanction" in allowed_actions and weight <= 0.3:
            candidates.append({"type": "sanction", "actor": actor, "target": target})
        if "declare_war" in allowed_actions and weight <= -0.45:  # Lowered from -0.55 to enable war with strong hostility
            candidates.append({"type": "declare_war", "actor": actor, "target": target})
        if "trade_agreement" in allowed_actions and weight >= -0.2:
            candidates.append({"type": "trade_agreement", "actor": actor, "target": target})
        if "request_military_alliance" in allowed_actions and weight >= -0.1:
            candidates.append(
                {
                    "type": "request_military_alliance",
                    "actor": actor,
                    "target": target,
                    "content": f"{actor} proposes coordinated security with {target}.",
                }
            )
        if "present_peace_agreement" in allowed_actions and weight <= -0.4:
            candidates.append(
                {
                    "type": "present_peace_agreement",
                    "actor": actor,
                    "target": target,
                    "content": f"{actor} proposes de-escalation terms to {target}.",
                }
            )

    if candidates:
        return candidates

    if relation_rows:
        target = relation_rows[0].get("target", actor)
        return [{"type": "send_message", "actor": actor, "target": target, "content": "Monitoring current situation."}]
    return []


def _goal_alignment_score(action_type: str, goal_tags: Dict[str, float], initial_context: Dict[str, Any]) -> float:
    """
    Scores an action by weighted overlap between actor goals and action-goal map.
    """
    model_alignment = initial_context.get("goal_model", {}).get("action_goal_alignment")
    action_alignment = model_alignment.get(action_type) if isinstance(model_alignment, dict) else None
    if not isinstance(action_alignment, dict):
        action_alignment = DEFAULT_ACTION_GOAL_ALIGNMENT.get(action_type, {})

    score = 0.0
    for goal_tag, goal_weight in goal_tags.items():
        score += float(goal_weight) * float(action_alignment.get(goal_tag, 0.0))
    return score


def _situation_fit_score(
    action_type: str,
    situation_tags: List[str],
    risk_tolerance: str,
) -> float:
    """
    Scores action suitability against dynamic situation tags and risk posture.
    """
    score = 0.0
    if "front_pressure_high" in situation_tags and action_type in {"declare_war", "sanction", "request_military_alliance"}:
        score += 0.25
    if "alliance_momentum_high" in situation_tags and action_type in {"trade_agreement", "publish_military_alliance"}:
        score += 0.2
    if "incoming_requests_present" in situation_tags and action_type in {"accept_request", "reject_request"}:
        score += 0.35

    # Enhanced risk-tolerance bonuses to promote strategic diversity
    if risk_tolerance == "high" and action_type in {"declare_war", "sanction"}:
        score += 0.25  # Increased from 0.15
    if risk_tolerance == "medium" and action_type in {"request_military_alliance", "trade_agreement", "declare_war"}:
        score += 0.12  # Added declare_war as viable for medium risk
    if risk_tolerance == "low" and action_type in {"present_peace_agreement", "trade_agreement"}:
        score += 0.15
    return score


def _relationship_fit_score(action_type: str, target_weight: float) -> float:
    """
    Scores whether the chosen action is coherent with relationship polarity.
    """
    if action_type in {"declare_war", "sanction"}:
        return max(0.0, -target_weight)
    if action_type in {"trade_agreement", "request_military_alliance", "publish_military_alliance", "accept_request"}:
        return max(0.0, target_weight)
    if action_type in {"present_peace_agreement", "reject_request"}:
        return max(0.0, abs(target_weight) * 0.5)
    return 0.1


def _add_action_metadata(action: Dict[str, Any], reason: str, tone_default: str) -> Dict[str, Any]:
    """
    Adds UI-friendly metadata for deck narration and traceability.
    """
    enriched = dict(action)
    enriched["rationale_code"] = reason
    enriched["tone"] = tone_default
    enriched["content_key"] = f"{action.get('type', 'action')}_v1"
    return enriched


def _repeat_action_penalty(packet: Dict[str, Any], candidate: Dict[str, Any]) -> float:
    """
    Penalizes repeated action-target loops for the same actor in recent global logs.
    """
    actor = str(candidate.get("actor", ""))
    action_type = str(candidate.get("type", ""))
    target = str(candidate.get("target", ""))
    if not actor or not action_type or not target:
        return 0.0

    recent_logs = list(packet.get("world_knowledge", {}).get("global_logs", []))[-10:]
    private_outgoing = list(packet.get("world_knowledge", {}).get("private_outgoing_history", []))[-10:]
    repeat_hits = 0
    for event in recent_logs:
        if not isinstance(event, dict):
            continue
        action = event.get("action")
        if not isinstance(action, dict):
            continue
        if action.get("actor") != actor:
            continue
        if action.get("type") == action_type and action.get("target") == target:
            repeat_hits += 1

    for action in private_outgoing:
        if not isinstance(action, dict):
            continue
        if action.get("actor") != actor:
            continue
        if action.get("type") == action_type and action.get("target") == target:
            repeat_hits += 1

    # Soft pressure against loops, capped to avoid overpowering contextual fit.
    return min(0.30, 0.06 * float(repeat_hits))


def _known_targets_from_packet(packet: Dict[str, Any]) -> set:
    """
    Collects valid target names from relationship snapshot and inbox origins.
    """
    targets: set = set()
    for row in packet.get("current_situation", {}).get("relationship_snapshot", []):
        if not isinstance(row, dict):
            continue
        target = row.get("target")
        if isinstance(target, str) and target.strip():
            targets.add(target.strip())

    for event in packet.get("private_inbox", []):
        if not isinstance(event, dict):
            continue
        action = event.get("action")
        if not isinstance(action, dict):
            continue
        origin = action.get("actor")
        if isinstance(origin, str) and origin.strip():
            targets.add(origin.strip())
    return targets


def _valid_request_events(packet: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Returns inbox request events keyed by request_id for causality checks.
    """
    events: Dict[str, Dict[str, Any]] = {}
    for event in packet.get("private_inbox", []):
        if not isinstance(event, dict):
            continue
        request_id = event.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            continue
        events[request_id] = event
    return events


def _recent_actor_actions(packet: Dict[str, Any], actor: str, lookback: int = 12) -> List[Dict[str, Any]]:
    """
    Returns recent global-log actions for this actor.
    """
    actions: List[Dict[str, Any]] = []
    for event in list(packet.get("world_knowledge", {}).get("global_logs", []))[-lookback:]:
        if not isinstance(event, dict):
            continue
        action = event.get("action")
        if not isinstance(action, dict):
            continue
        if action.get("actor") == actor:
            actions.append(action)

    for action in list(packet.get("world_knowledge", {}).get("private_outgoing_history", []))[-lookback:]:
        if not isinstance(action, dict):
            continue
        if action.get("actor") == actor:
            actions.append(action)
    return actions


def _fails_loop_or_diversity_check(packet: Dict[str, Any], action: Dict[str, Any]) -> Optional[str]:
    """
    Detects repeated action-target loops and low-diversity cycles.
    """
    actor = str(action.get("actor", "")).strip()
    action_type = str(action.get("type", "")).strip()
    target = str(action.get("target", "")).strip()
    if not actor or not action_type or not target:
        return "missing_signature_fields"

    recent_actions = _recent_actor_actions(packet, actor, lookback=12)
    if not recent_actions:
        return None

    signature = (action_type, target)
    recent_signatures = [(str(a.get("type", "")), str(a.get("target", ""))) for a in recent_actions]

    # Hard stop for immediate short-loop streaks.
    tail = recent_signatures[-2:]
    if len(tail) == 2 and tail[0] == signature and tail[1] == signature:
        return "loop_streak_detected"

    repeated_hits = sum(1 for sig in recent_signatures if sig == signature)
    if repeated_hits >= 3:
        return "repeat_pattern_detected"

    # Low-diversity cycle: too few distinct moves in recent history, candidate repeats one of them.
    if len(recent_signatures) >= 4:
        unique_count = len(set(recent_signatures))
        diversity = float(unique_count) / float(len(recent_signatures))
        if diversity < 0.45 and repeated_hits >= 1:
            return "low_diversity_cycle"

    return None


def _is_escalatory(action_type: str) -> bool:
    """
    Returns whether an action is escalatory towards a target.
    """
    return action_type in {"declare_war", "sanction"}


def _is_alliance_or_peace(action_type: str) -> bool:
    """
    Returns whether an action signals alliance/de-escalatory intent.
    """
    return action_type in {"request_military_alliance", "publish_military_alliance", "present_peace_agreement"}


def _has_recent_justification(packet: Dict[str, Any], target: str) -> bool:
    """
    Allows contradictory diplomacy only if recent inbox events justify a policy pivot.
    """
    for event in list(packet.get("private_inbox", []))[-6:]:
        if not isinstance(event, dict):
            continue
        request_id = event.get("request_id")
        action = event.get("action")
        if not isinstance(request_id, str) or not isinstance(action, dict):
            continue
        origin = str(action.get("actor", "")).strip()
        origin_type = str(action.get("type", "")).strip()
        if origin != target:
            continue
        if origin_type in {"request_military_alliance", "present_peace_agreement", "send_message"}:
            return True
    return False


def _fails_alliance_coherence_check(packet: Dict[str, Any], action: Dict[str, Any]) -> Optional[str]:
    """
    Rejects contradictory diplomacy against same target unless justified by recent context.
    """
    actor = str(action.get("actor", "")).strip()
    action_type = str(action.get("type", "")).strip()
    target = str(action.get("target", "")).strip()
    if not actor or not action_type or not target:
        return None

    recent_actions = _recent_actor_actions(packet, actor, lookback=10)
    if not recent_actions:
        return None

    target_history = [
        str(prev.get("type", "")).strip()
        for prev in recent_actions
        if str(prev.get("target", "")).strip() == target
    ]
    if not target_history:
        return None

    has_recent_escalation = any(_is_escalatory(prev_type) for prev_type in target_history[-4:])
    has_recent_alliance = any(_is_alliance_or_peace(prev_type) for prev_type in target_history[-4:])
    justified = _has_recent_justification(packet, target)

    if _is_alliance_or_peace(action_type) and has_recent_escalation and not justified:
        return "alliance_after_recent_escalation"
    if _is_escalatory(action_type) and has_recent_alliance and not justified:
        return "escalation_after_recent_alliance"
    return None


def _fails_logical_validation(packet: Dict[str, Any], action: Dict[str, Any]) -> Optional[str]:
    """
    Runs deterministic legal/target/request-causality/context checks.
    """
    actor = str(packet.get("agent_identity", {}).get("name", "")).strip()
    action_type = action.get("type")
    target = action.get("target")

    if not isinstance(action_type, str):
        return "invalid_action_type"
    if action_type not in set(packet.get("rules", {}).get("allowed_actions", [])):
        return "action_not_allowed"
    if action_type not in ACTION_REGISTRY:
        return "action_not_registered"

    if not isinstance(target, str):
        return "invalid_target"
    if target not in _known_targets_from_packet(packet):
        return "target_not_in_recent_context"
    if action.get("actor") != actor:
        return "actor_mismatch"

    action_def = ACTION_REGISTRY[action_type]
    if action_def.input_type == "target_and_message":
        content = action.get("content")
        if not isinstance(content, str) or not content.strip():
            return "missing_required_content"

    valid_request_events = _valid_request_events(packet)
    if action_type in {"accept_request", "reject_request"}:
        request_id = action.get("request_id")
        if not isinstance(request_id, str) or request_id not in valid_request_events:
            return "invalid_request_id"

        # Causality: request must originate from selected target.
        event = valid_request_events[request_id]
        origin = ""
        if isinstance(event.get("action"), dict):
            origin = str(event.get("action", {}).get("actor", "")).strip()
        if origin != str(target).strip():
            return "request_target_causality_mismatch"

    loop_flag = _fails_loop_or_diversity_check(packet, action)
    if loop_flag:
        return loop_flag

    alliance_flag = _fails_alliance_coherence_check(packet, action)
    if alliance_flag:
        return alliance_flag

    return None


def _evaluate_with_board_agent(
    packet: Dict[str, Any],
    action: Dict[str, Any],
    initial_context: Dict[str, Any],
) -> Tuple[bool, BoardEvaluation]:
    """
    Runs the Board Agent math-first evaluation and optional LLM interpretation.
    Returns (approved, evaluation).
    """
    evaluation = BOARD_AGENT.evaluate(packet, action, initial_context)
    return evaluation.approved, evaluation


def _validate_action_with_rules(
    packet: Dict[str, Any],
    proposed_action: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Runs secretary and deterministic validations; returns normalized action or None.
    """
    secretary_checked = _validate_action_with_secretary_agent(packet, proposed_action, candidates)
    if not secretary_checked:
        return None

    failure = _fails_logical_validation(packet, secretary_checked)
    if failure:
        return None
    return secretary_checked


def _choose_action_with_country_agent(
    country_agent: CountryAgentModel,
    packet: Dict[str, Any],
    initial_context: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Attempts to get one validated action from the HF-backed country agent module.
    Returns None when disabled, unavailable, or invalid.
    """
    return country_agent.propose_action(packet, initial_context, candidates)


def _validate_action_with_secretary_agent(
    packet: Dict[str, Any],
    proposed_action: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Runs the OpenAI-backed secretary validator over a proposed action.
    """
    validated = SECRETARY_AGENT.validate_action(packet, proposed_action, candidates)
    if not validated:
        return None

    annotated = dict(validated)

    if not SECRETARY_AGENT.config.enabled or not SECRETARY_AGENT.config.api_key:
        annotated["secretary_status"] = "bypassed"
        annotated["secretary_note"] = "Secretary agent is disabled; deterministic legal checks now govern execution."
        return annotated

    changed_fields: List[str] = []
    for key in ("type", "target", "request_id", "content"):
        if proposed_action.get(key) != validated.get(key):
            changed_fields.append(key)

    if changed_fields:
        changed_text = ", ".join(changed_fields)
        annotated["secretary_status"] = "corrected"
        annotated["secretary_note"] = (
            f"Secretary corrected {changed_text} to satisfy legal form, target validity, and request causality."
        )
    else:
        annotated["secretary_status"] = "approved"
        annotated["secretary_note"] = "Secretary approved the action unchanged after legality and causality review."

    return annotated


def choose_action_for_agent(
    country_agent: CountryAgentModel,
    packet: Dict[str, Any],
    initial_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Chooses the highest-scoring action using weighted goal/situation/relationship logic.
    """
    actor = packet.get("agent_identity", {}).get("name")
    if not actor:
        return None

    candidates = _build_candidate_actions(packet, actor)
    if not candidates:
        return None

    tone_default = initial_context.get("agent_policy", {}).get("tone_default", "neutral")

    # Give the country model first say when it returns a valid and coherent action.
    llm_action = _choose_action_with_country_agent(country_agent, packet, initial_context, candidates)
    _process_gui_events()  # Keep GUI responsive after LLM call
    if llm_action:
        llm_validated = _validate_action_with_rules(packet, llm_action, candidates)
        _process_gui_events()  # Keep GUI responsive after secretary validation
        if llm_validated:
            board_approved, board_eval = _evaluate_with_board_agent(packet, llm_validated, initial_context)
            _process_gui_events()  # Keep GUI responsive after board evaluation
            if board_approved:
                enriched = _add_action_metadata(llm_validated, "country_agent_llm", tone_default)
                enriched["board_utility"] = round(board_eval.utility, 4)
                enriched["board_reason"] = board_eval.override_reason
                return enriched
            # Board rejected — log reason and fall through to fallback.
            if _agent_debug_enabled():
                print(f"[BOARD] {actor}: LLM action rejected — {board_eval.override_reason}")

    goal_tags = packet.get("goals", {}).get("goal_tags", {})
    situation_tags = packet.get("current_situation", {}).get("situation_tags", [])
    relation_map = {
        row.get("target"): float(row.get("weight", 0.0))
        for row in packet.get("current_situation", {}).get("relationship_snapshot", [])
    }
    risk_tolerance = packet.get("agent_identity", {}).get("risk_tolerance", "medium")

    weights = packet.get("decision_weights", DEFAULT_DECISION_WEIGHTS)
    wg = float(weights.get("goal_alignment", DEFAULT_DECISION_WEIGHTS["goal_alignment"]))
    ws = float(weights.get("situation_fit", DEFAULT_DECISION_WEIGHTS["situation_fit"]))
    wr = float(weights.get("relationship_fit", DEFAULT_DECISION_WEIGHTS["relationship_fit"]))
    wc = float(weights.get("constraint_compliance", DEFAULT_DECISION_WEIGHTS["constraint_compliance"]))

    allowed_actions = set(packet.get("rules", {}).get("allowed_actions", []))

    best_total = float("-inf")
    best_action: Optional[Dict[str, Any]] = None
    best_reason = "balanced_strategy"

    for candidate in candidates:
        action_type = str(candidate.get("type", ""))
        if action_type not in allowed_actions:
            continue

        if _fails_logical_validation(packet, candidate):
            continue

        target = candidate.get("target")
        target_weight = float(relation_map.get(target, 0.0))

        goal_score = _goal_alignment_score(action_type, goal_tags, initial_context)
        situation_score = _situation_fit_score(action_type, situation_tags, risk_tolerance)
        relation_score = _relationship_fit_score(action_type, target_weight)
        constraint_score = 1.0
        repeat_penalty = _repeat_action_penalty(packet, candidate)

        total = (wg * goal_score) + (ws * situation_score) + (wr * relation_score) + (wc * constraint_score) - repeat_penalty

        if total > best_total:
            best_total = total
            best_action = candidate
            if goal_score >= situation_score and goal_score >= relation_score:
                best_reason = "goal_alignment"
            elif situation_score >= relation_score:
                best_reason = "situation_response"
            else:
                best_reason = "relationship_management"

    if best_action is None:
        return None

    fallback_validated = _validate_action_with_rules(packet, best_action, candidates)
    _process_gui_events()  # Keep GUI responsive after fallback validation
    if fallback_validated:
        board_approved, board_eval = _evaluate_with_board_agent(packet, fallback_validated, initial_context)
        _process_gui_events()  # Keep GUI responsive after fallback board evaluation
        if board_approved:
            enriched = _add_action_metadata(fallback_validated, best_reason, tone_default)
            enriched["board_utility"] = round(board_eval.utility, 4)
            enriched["board_reason"] = board_eval.override_reason
            return enriched
        if _agent_debug_enabled():
            print(f"[BOARD] {actor}: fallback action rejected — {board_eval.override_reason}")
    return None


def _stream_action_live(round_number: int, action: Dict[str, Any]) -> None:
    """
    Prints a compact live trace for one resolved action in full display mode.
    Flushed immediately so output appears in real time during slow model calls.
    Also feeds to Pygame GUI if enabled.
    """
    actor = action.get("actor", "?")
    target = action.get("target", "?")
    action_type = action.get("type", "?").replace("_", " ")
    rationale_code = action.get("rationale_code", "")
    thought = action.get("thought_summary", "").strip()
    selected_rationale = action.get("selected_rationale", "").strip()
    strategic_options = action.get("strategic_options", [])
    ally_candidates = action.get("ally_candidates", [])
    enemy_candidates = action.get("enemy_candidates", [])
    secretary_status = str(action.get("secretary_status", "approved")).strip().lower()
    secretary_note = action.get("secretary_note", "").strip()
    board_reason = action.get("board_reason", "").strip()
    board_utility = action.get("board_utility")
    public_message = action.get("public_message", "").strip()
    private_intent = action.get("private_intent", "").strip()

    source = "LLM" if "llm" in rationale_code else "fallback"

    display_mode = os.getenv("DISPLAY_MODE", "short").strip().lower()

    # Terminal output
    if display_mode == "full":
        print(f"\n  ↳ R{round_number} | {actor} → {target}  [{action_type}]  ({source})")
        print("    Country:")
        if thought:
            print(f"      Thought: {thought}")
        if selected_rationale:
            print(f"      Rationale: {selected_rationale}")
        if isinstance(strategic_options, list) and strategic_options:
            options_text = " / ".join(str(item) for item in strategic_options[:3])
            print(f"      4-step planning options: {options_text}")
        if isinstance(ally_candidates, list) and ally_candidates:
            print(f"      Ally candidates: {', '.join(str(item) for item in ally_candidates[:3])}")
        if isinstance(enemy_candidates, list) and enemy_candidates:
            print(f"      Enemy candidates: {', '.join(str(item) for item in enemy_candidates[:3])}")
        if not thought and not selected_rationale:
            print("      Thought: Deterministic fallback selected due to model unavailability or validation path.")

        print("    Secretary:")
        if secretary_status == "corrected":
            print("      Status: Corrected and approved")
        elif secretary_status == "bypassed":
            print("      Status: Bypassed")
        else:
            print("      Status: Approved")
        if secretary_note:
            print(f"      Why: {secretary_note}")

        print("    Council:")
        if board_reason:
            print(f"      Political brief: {board_reason}")
        if board_utility is not None:
            try:
                print(f"      Utility score: {float(board_utility):.3f}")
            except (TypeError, ValueError):
                pass

        if public_message:
            print(f"    Public line: {public_message}")
        if private_intent:
            print(f"    Private intent: {private_intent}")
        sys.stdout.flush()
    elif display_mode == "short":
        headline = str(action.get("headline", "")).strip()
        if headline:
            print(f"  {actor} → {target} | {headline}")
        else:
            print(f"  {actor} → {target} | {action_type}")
        sys.stdout.flush()

    # GUI update (only if all agents use API)
    if _GUI_AVAILABLE and _all_agents_use_api() and os.getenv("GUI_ENABLED", "0").strip().lower() in {"1", "true", "yes"}:
        gui = get_gui()
        if gui:
            gui.add_live_action(action)
            gui.update()


def _build_live_result_payload(
    initial_context: Dict[str, Any],
    engine: SimulationEngine,
    rounds_payload: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Builds a partial result payload so the GUI can render before the simulation finishes."""
    diplomacy_edges: List[Dict[str, Any]] = []
    for edge in engine.world_state.diplomacy_graph.edges(data=True):
        node_a = edge[0]
        node_b = edge[1]
        payload = edge[2] if len(edge) > 2 else {}
        weight = payload.get("weight", 0.0) if isinstance(payload, dict) else 0.0
        diplomacy_edges.append({"a": node_a, "b": node_b, "weight": weight})

    current_state: List[Dict[str, Any]] = []
    for _, row in engine.world_state.df.iterrows():
        current_state.append(
            {
                "name": row["name"],
                "army_size": row["army_size"],
                "morale": row.get("morale", 0.0),
                "national_unity": row.get("national_unity", 0.0),
                "stability_index": row["stability_index"],
            }
        )

    return {
        "scenario": {
            "scenario_id": initial_context.get("scenario_id"),
            "scenario_title": initial_context.get("scenario_title"),
            "timeframe": initial_context.get("timeframe"),
        },
        "initial_state": current_state,
        "final_state": current_state,
        "rounds": rounds_payload,
        "final_diplomacy_edges": diplomacy_edges,
        "evaluation": {},
    }


def _stream_round_start(round_number: int) -> None:
    """Prints a round header before actions are computed."""
    display_mode = os.getenv("DISPLAY_MODE", "short").strip().lower()
    if display_mode == "full":
        print(f"\n{'═' * 56}")
        print(f"  ROUND {round_number} — FULL PROCESS VIEW")
        print(f"{'═' * 56}")
    else:
        print(f"\n━━━━  ROUND {round_number}  ━━━━")
    sys.stdout.flush()


def _stream_thinking_status(round_number: int, actor: str) -> None:
    """Shows live status before a country-agent decision returns in full mode."""
    if os.getenv("DISPLAY_MODE", "short").strip().lower() != "full":
        return
    sys.stdout.write(f"\r  · R{round_number} | {actor} is thinking...")
    sys.stdout.flush()


def _clear_thinking_status() -> None:
    """Clears the transient full-mode thinking status line."""
    if os.getenv("DISPLAY_MODE", "short").strip().lower() != "full":
        return
    sys.stdout.write("\r" + (" " * 120) + "\r")
    sys.stdout.flush()


def decide_round_actions(
    engine: SimulationEngine,
    initial_context: Dict[str, Any],
    country_agents: Dict[str, CountryAgentModel],
    round_number: int,
) -> List[Dict[str, Any]]:
    """
    Builds packets for all actors and returns one selected action per actor.
    """
    actions: List[Dict[str, Any]] = []
    if _agent_debug_enabled():
        print(f"[AGENT_DEBUG] Round {round_number}: assigning country agents")

    _stream_round_start(round_number)

    for country in engine.world_state.country_profiles:
        if _GUI_AVAILABLE and _all_agents_use_api() and os.getenv("GUI_ENABLED", "0").strip().lower() in {"1", "true", "yes"}:
            gui = get_gui()
            if gui and not gui.update():
                break

        _stream_thinking_status(round_number, country.name)

        packet = build_agent_input_packet(engine, initial_context, country.name, round_number)
        assigned_agent = country_agents.get(country.name)
        if assigned_agent is None:
            assigned_agent = CountryAgentModel.from_env()
            country_agents[country.name] = assigned_agent
            if _agent_debug_enabled():
                print(f"[AGENT_DEBUG] {country.name} created late -> instance_id={id(assigned_agent)}")

        if _agent_debug_enabled():
            print(f"[AGENT_DEBUG] {country.name} using instance_id={id(assigned_agent)}")

        chosen = choose_action_for_agent(assigned_agent, packet, initial_context)
        _clear_thinking_status()
        if chosen:
            actions.append(chosen)
            _stream_action_live(round_number, chosen)
    return actions


def run_decision_action_layers(rounds: int = 2, scenario_file: str = DEFAULT_SCENARIO_FILE) -> Dict[str, Any]:
    """
    Runs decision and action layers using structure-first context packets.
    """
    _refresh_runtime_agents()
    _print_agent_runtime_diagnostics()

    initial_context = load_initial_context(scenario_file)
    engine = build_default_engine(initial_context)
    country_agents = build_country_agents(engine)
    iron_ledger = IronLedger(world_state=engine.world_state)

    # Initialize GUI if enabled and all agents use API (not local)
    gui_requested = os.getenv("GUI_ENABLED", "0") == "1"
    all_agents_api = _all_agents_use_api()
    
    if gui_requested and not all_agents_api:
        print("\n" + "="*80)
        print("WARNING: GUI is disabled because local agents are being used.")
        print("GUI only works when ALL agents use API endpoints to avoid performance issues.")
        print("Current configuration:")
        print(f"  - Country Agent Backend: {os.getenv('COUNTRY_AGENT_BACKEND', 'hf_api')}")
        print("\nTo enable GUI:")
        print("  1. Set COUNTRY_AGENT_BACKEND='hf_api' (not 'ollama')")
        print("  2. Ensure all agents have valid API keys")
        print("  3. Use one of the API-enabled run scripts (e.g., mode_run_long_with_gui.ps1)")
        print("="*80 + "\n")
    
    gui_enabled = gui_requested and _GUI_AVAILABLE and all_agents_api
    
    if gui_enabled:
        try:
            print("\n[GUI] Initializing pygame window...")
            gui_instance = init_gui(scenario_file=scenario_file or "")
            if gui_instance:
                gui_instance.set_world_state(engine.world_state)
                gui_instance.set_iron_ledger(iron_ledger)
                # Draw and display the window immediately
                gui_instance.update()
                print("[GUI] ✓ Pygame GUI window initialized and displayed")
                print("[GUI] Window should be visible on your screen")
            else:
                print("[GUI] WARNING: init_gui returned None")
                gui_enabled = False
        except Exception as e:
            print(f"[GUI] ERROR: Failed to initialize GUI: {e}")
            import traceback
            traceback.print_exc()
            gui_enabled = False
    elif gui_requested and not _GUI_AVAILABLE:
        print("\n[GUI] WARNING: GUI requested but pygame is not available")
        print("[GUI] Install pygame: pip install pygame")
    elif gui_requested and not all_agents_api:
        print("\n[GUI] GUI disabled due to local agent configuration (see warning above)")
    else:
        print("\n[GUI] GUI disabled (GUI_ENABLED=0)")

    initial_state: List[Dict[str, Any]] = []
    for _, row in engine.world_state.df.iterrows():
        initial_state.append(
            {
                "name": row["name"],
                "army_size": row["army_size"],
                "combat_power": row["combat_power"],
                "stability_index": row["stability_index"],
            }
        )

    rounds_payload: List[Dict[str, Any]] = []
    if gui_enabled:
        gui = get_gui()
        if gui:
            gui.set_result(_build_live_result_payload(initial_context, engine, rounds_payload))
            gui.update()

    for round_number in range(1, rounds + 1):
        round_actions = decide_round_actions(engine, initial_context, country_agents, round_number)
        engine.apply_actions(round_actions)
        iron_ledger.apply_round_consequences(round_actions, round_number)
        engine.advance_rounds()

        # Update GUI if enabled
        if gui_enabled:
            try:
                gui = get_gui()
                if gui and not gui.update():
                    # User closed the window
                    close_gui()
                    gui_enabled = False
            except Exception as e:
                print(f"Warning: GUI update failed: {e}")

        round_state_after: List[Dict[str, Any]] = []
        for _, row in engine.world_state.df.iterrows():
            round_state_after.append(
                {
                    "name": row["name"],
                    "army_size": row["army_size"],
                    "morale": row["morale"],
                    "national_unity": row["national_unity"],
                    "stability_index": row["stability_index"],
                }
            )

        round_metrics = iron_ledger.round_metrics[-1] if iron_ledger.round_metrics else {}
        rounds_payload.append(
            {
                "round": round_number,
                "actions": round_actions,
                "metrics": round_metrics,
                "state_after_round": round_state_after,
            }
        )

        if gui_enabled:
            gui = get_gui()
            if gui:
                gui.set_result(_build_live_result_payload(initial_context, engine, rounds_payload))
                gui.update()

    diplomacy_edges: List[Dict[str, Any]] = []
    for edge in engine.world_state.diplomacy_graph.edges(data=True):
        node_a = edge[0]
        node_b = edge[1]
        payload = edge[2] if len(edge) > 2 else {}
        weight = payload.get("weight", 0.0) if isinstance(payload, dict) else 0.0
        diplomacy_edges.append({"a": node_a, "b": node_b, "weight": weight})

    final_state: List[Dict[str, Any]] = []
    for _, row in engine.world_state.df.iterrows():
        final_state.append(
            {
                "name": row["name"],
                "army_size": row["army_size"],
                "morale": row["morale"],
                "national_unity": row["national_unity"],
                "stability_index": row["stability_index"],
            }
        )

    evaluation = iron_ledger.final_report()

    # Finalize GUI if enabled
    if gui_enabled:
        try:
            gui = get_gui()
            if gui:
                gui.set_simulation_complete(True)
                gui.update()  # Final render
                # Keep window open until user closes it or 10 seconds pass
                import time
                end_time = time.time() + 10
                while gui.is_running() and time.time() < end_time:
                    if not gui.update():
                        break
                close_gui()
        except Exception as e:
            print(f"Warning: GUI finalization failed: {e}")

    return {
        "scenario": {
            "scenario_id": initial_context.get("scenario_id"),
            "scenario_title": initial_context.get("scenario_title"),
            "timeframe": initial_context.get("timeframe"),
        },
        "initial_state": initial_state,
        "final_state": final_state,
        "rounds": rounds_payload,
        "final_diplomacy_edges": diplomacy_edges,
        "evaluation": evaluation,
    }


def run_test() -> Dict[str, Any]:
    """
    Backward-compatible test entry point.
    """
    return run_decision_action_layers()


if __name__ == "__main__":
    result = run_test()
    print(result)
