from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Set, Tuple

from WorldEngine.world_state import CountryProfile, WorldState


@dataclass
class OutcomeState:
    """Tracks per-country life cycle and scoring state."""

    economic_proxy: float = 1.0
    survival_rounds: int = 0
    alliance_dominance_streak: int = 0
    outcome: str = "active"


class IronLedger:
    """Lightweight consequence engine + evaluation metrics for each simulation run."""

    def __init__(
        self,
        world_state: WorldState,
        stability_threshold: float = 0.25,
        army_exhaustion_threshold: int = 150_000,
        diplomatic_victory_rounds: int = 2,
    ) -> None:
        self.world_state = world_state
        self.stability_threshold = stability_threshold
        self.army_exhaustion_threshold = army_exhaustion_threshold
        self.diplomatic_victory_rounds = diplomatic_victory_rounds

        self.initial_army: Dict[str, int] = {cp.name: int(cp.army_size) for cp in world_state.country_profiles}
        self.country_state: Dict[str, OutcomeState] = {cp.name: OutcomeState() for cp in world_state.country_profiles}

        self.round_metrics: List[Dict[str, Any]] = []
        self.prev_allied_pairs: Set[Tuple[str, str]] = self._allied_pairs()
        self.alliance_churn_total: int = 0

    def apply_round_consequences(self, actions: List[Dict[str, Any]], round_number: int) -> None:
        """Applies lightweight action consequences and computes round-level metrics."""
        total_actions = len(actions)
        war_actions = 0

        for action in actions:
            action_type = str(action.get("type", ""))
            actor_name = action.get("actor")
            target_name = action.get("target")

            actor = self._find_country(actor_name)
            target = self._find_country(target_name)
            if actor is None or target is None:
                continue

            if action_type == "declare_war":
                war_actions += 1
                self._apply_war_damage(actor)
                self._apply_war_damage(target)
            elif action_type == "sanction":
                self._apply_sanction_impact(target)
            elif action_type == "trade_agreement":
                self._apply_trade_benefit(actor)
                self._apply_trade_benefit(target)

        for cp in self.world_state.country_profiles:
            state = self.country_state[cp.name]
            if state.outcome == "active":
                state.survival_rounds += 1

        self._evaluate_outcomes()

        current_allied_pairs = self._allied_pairs()
        alliance_churn = len(current_allied_pairs.symmetric_difference(self.prev_allied_pairs))
        self.alliance_churn_total += alliance_churn
        self.prev_allied_pairs = current_allied_pairs

        escalation_rate = (war_actions / total_actions) if total_actions > 0 else 0.0
        self.round_metrics.append(
            {
                "round": round_number,
                "escalation_rate": round(escalation_rate, 4),
                "alliance_churn": alliance_churn,
                "active_countries": [
                    name for name, state in self.country_state.items() if state.outcome == "active"
                ],
            }
        )

    def final_report(self) -> Dict[str, Any]:
        """Builds final metrics package requested for evaluation."""
        utility_scores = self._compute_final_utility_scores()
        outcomes = {name: state.outcome for name, state in self.country_state.items()}
        survival = {name: state.survival_rounds for name, state in self.country_state.items()}

        return {
            "escalation_rate_per_round": [
                {"round": row["round"], "value": row["escalation_rate"]}
                for row in self.round_metrics
            ],
            "alliance_churn": {
                "per_round": [{"round": row["round"], "value": row["alliance_churn"]} for row in self.round_metrics],
                "total": self.alliance_churn_total,
            },
            "survival_rounds_per_country": survival,
            "final_utility_score": utility_scores,
            "country_outcomes": outcomes,
        }

    def _find_country(self, name: Any) -> CountryProfile | None:
        if not isinstance(name, str):
            return None
        for cp in self.world_state.country_profiles:
            if cp.name == name:
                return cp
        return None

    def _allied_pairs(self) -> Set[Tuple[str, str]]:
        pairs: Set[Tuple[str, str]] = set()
        for edge in self.world_state.diplomacy_graph.edges(data=True):
            if len(edge) < 3:
                continue
            a, b, payload = edge
            weight = float(payload.get("weight", 0.0)) if isinstance(payload, dict) else 0.0
            if weight >= 0.7:
                left, right = sorted((str(a), str(b)))
                pairs.add((left, right))
        return pairs

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))

    def _apply_war_damage(self, cp: CountryProfile) -> None:
        cp.army_size = max(0, int(cp.army_size * 0.94))
        cp.morale = self._clamp01(cp.morale - 0.07)
        cp.national_unity = self._clamp01(cp.national_unity - 0.03)

    def _apply_sanction_impact(self, cp: CountryProfile) -> None:
        state = self.country_state[cp.name]
        state.economic_proxy = self._clamp01(state.economic_proxy - 0.08)
        cp.national_unity = self._clamp01(cp.national_unity - 0.05)
        cp.morale = self._clamp01(cp.morale - 0.02)

    def _apply_trade_benefit(self, cp: CountryProfile) -> None:
        state = self.country_state[cp.name]
        state.economic_proxy = self._clamp01(state.economic_proxy + 0.05)
        cp.national_unity = self._clamp01(cp.national_unity + 0.02)
        cp.morale = self._clamp01(cp.morale + 0.03)

    def _evaluate_outcomes(self) -> None:
        total_countries = max(1, len(self.world_state.country_profiles))
        required_allies = max(1, total_countries // 2)

        for cp in self.world_state.country_profiles:
            state = self.country_state[cp.name]
            if state.outcome != "active":
                continue

            if cp.stability_index < self.stability_threshold:
                state.outcome = "collapse"
                continue

            if cp.army_size < self.army_exhaustion_threshold:
                state.outcome = "military_exhaustion"
                continue

            allied_count = 0
            hostile_count = 0
            for other in self.world_state.country_profiles:
                if other.name == cp.name:
                    continue
                edge = self.world_state.diplomacy_graph.get_edge_data(cp.name, other.name, default={"weight": 0.0})
                weight = float(edge.get("weight", 0.0)) if isinstance(edge, dict) else 0.0
                if weight >= 0.7:
                    allied_count += 1
                if weight <= -0.7:
                    hostile_count += 1

            if allied_count >= required_allies and allied_count > hostile_count:
                state.alliance_dominance_streak += 1
            else:
                state.alliance_dominance_streak = 0

            if state.alliance_dominance_streak >= self.diplomatic_victory_rounds:
                state.outcome = "diplomatic_victory"

    def _compute_final_utility_scores(self) -> Dict[str, float]:
        utility: Dict[str, float] = {}

        for cp in self.world_state.country_profiles:
            state = self.country_state[cp.name]
            initial_army = max(1, self.initial_army.get(cp.name, int(cp.army_size)))
            army_ratio = min(1.0, float(cp.army_size) / float(initial_army))
            morale = self._clamp01(float(cp.morale))
            stability = self._clamp01(float(cp.stability_index))
            economy = self._clamp01(float(state.economic_proxy))

            allies = 0
            hostiles = 0
            others = 0
            for other in self.world_state.country_profiles:
                if other.name == cp.name:
                    continue
                others += 1
                edge = self.world_state.diplomacy_graph.get_edge_data(cp.name, other.name, default={"weight": 0.0})
                weight = float(edge.get("weight", 0.0)) if isinstance(edge, dict) else 0.0
                if weight >= 0.2:
                    allies += 1
                elif weight <= -0.2:
                    hostiles += 1

            if others > 0:
                diplomacy_balance = (allies - hostiles) / float(others)
            else:
                diplomacy_balance = 0.0
            diplomacy_score = self._clamp01((diplomacy_balance + 1.0) / 2.0)

            score = (
                0.30 * army_ratio
                + 0.20 * morale
                + 0.20 * stability
                + 0.20 * economy
                + 0.10 * diplomacy_score
            )
            utility[cp.name] = round(score, 4)

        return utility
