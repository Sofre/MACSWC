import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

# ---------------------------------------------------------------------------
# Risk constants — tuned for geopolitical simulation balance
# ---------------------------------------------------------------------------

# Risk multiplier applied to terminal crisis score during rollback.
# Lower values make agents more willing to accept risky actions.
CRISIS_RISK_ALPHA = 0.35

# Minimum rollback utility required for Board approval.
# Negative values allow actions with minor net loss; zero requires break-even; positive requires net gain.
APPROVAL_THRESHOLD = -0.05

# Economic damage multiplier for escalatory actions.
ECONOMIC_DAMAGE_WEIGHT = 0.20

# Morale collapse threshold — actions that push morale below this trigger rejection.
MORALE_COLLAPSE_THRESHOLD = 0.25

# Victory probability weight — how much winning matters vs. cost.
VICTORY_PROBABILITY_WEIGHT = 0.30

# Actions that expose the actor to direct military consequence.
ESCALATORY_ACTIONS = {"declare_war", "sanction"}

# Actions that signal de-escalatory or cohesion intent.
COOPERATIVE_ACTIONS = {
    "request_military_alliance",
    "publish_military_alliance",
    "present_peace_agreement",
    "trade_agreement",
    "accept_request",
}

# Expected response type per action category, indexed by (action_type, target_risk_tolerance).
_RESPONSE_TABLE: Dict[Tuple[str, str], str] = {
    ("declare_war", "high"): "retaliate",
    ("declare_war", "medium"): "retaliate",
    ("declare_war", "low"): "defend",
    ("sanction", "high"): "counter_sanction",
    ("sanction", "medium"): "protest",
    ("sanction", "low"): "protest",
    ("request_military_alliance", "high"): "accept",
    ("request_military_alliance", "medium"): "accept",
    ("request_military_alliance", "low"): "accept",
    ("present_peace_agreement", "high"): "ignore",
    ("present_peace_agreement", "medium"): "consider",
    ("present_peace_agreement", "low"): "accept",
    ("trade_agreement", "high"): "accept",
    ("trade_agreement", "medium"): "accept",
    ("trade_agreement", "low"): "accept",
    ("publish_military_alliance", "high"): "counter_alliance",
    ("publish_military_alliance", "medium"): "observe",
    ("publish_military_alliance", "low"): "observe",
}


@dataclass
class BoardEvaluation:
    """Structured result from one Board Agent evaluation cycle."""

    approved: bool
    utility: float
    edge_weight: float
    terminal_crisis_risk: float
    estimated_response: str
    override_reason: str
    suggested_alternative: Optional[str]
    rationale_code: str


@dataclass
class BoardAgentConfig:
    """Configuration for the Board Agent."""

    enabled: bool
    llm_enabled: bool
    api_key: Optional[str]
    provider: str = "openai"  # "openai" or "groq"
    model: str = "gpt-4o-mini"    
    delay_seconds: float = 0.0  # Rate limiting delay between API calls    temperature: float = 0.0
    timeout_seconds: int = 25
    max_output_tokens: int = 180
    approval_threshold: float = APPROVAL_THRESHOLD
    crisis_alpha: float = CRISIS_RISK_ALPHA
    ollama_url: str = OLLAMA_CHAT_URL
    ollama_model: str = "qwen2.5:14b-instruct"
    
    # Allow runtime override via environment
    def __post_init__(self):
        env_threshold = os.getenv("BOARD_APPROVAL_THRESHOLD")
        if env_threshold:
            try:
                self.approval_threshold = float(env_threshold)
            except ValueError:
                pass
        env_alpha = os.getenv("BOARD_CRISIS_ALPHA")
        if env_alpha:
            try:
                self.crisis_alpha = float(env_alpha)
            except ValueError:
                pass


class BoardAgentModel:
    """
    Strategic Council evaluating net value of proposed actions.

    Unlike traditional risk-averse gatekeepers, this Board evaluates whether
    expected strategic GAINS exceed expected COSTS—not whether actions are "safe."

    Execution flow per action:
      1. Compute expected strategic gains (victory probability, territorial value, economic benefit).
      2. Compute expected strategic costs (casualties, economic damage, morale collapse, isolation, opportunity cost).
      3. Calculate net utility: gains - (crisis_alpha × costs).
      4. Approve when net utility > threshold (allows calculated risks with positive expected value).
      5. If LLM enabled: send computed scores for strategic interpretation and council verdict.

    Key innovation: Blocks catastrophic losing wars, but approves winnable wars with favorable cost-benefit.
    """

    def __init__(self, config: BoardAgentConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "BoardAgentModel":
        """Builds config from environment variables."""
        enabled = os.getenv("BOARD_AGENT_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
        llm_enabled = os.getenv("BOARD_AGENT_LLM_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
        provider = os.getenv("BOARD_AGENT_PROVIDER", "groq").strip().lower()

        if provider in {"ollama", "local", "local_ollama"}:
            api_key = None
            default_model = os.getenv("BOARD_AGENT_OLLAMA_MODEL", "qwen2.5:14b-instruct")
        else:
            groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
            board_key = (os.getenv("BOARD_AGENT_API_KEY") or "").strip()
            openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
            openrouter_key = (os.getenv("BOARD_OPENROUTER_KEY") or os.getenv("OPENROUTER_API_KEY") or "").strip()

            # Select provider and API key
            if provider == "openrouter" and openrouter_key:
                api_key = openrouter_key
                default_model = "meta-llama/llama-3.1-70b-instruct"
            elif provider == "groq" and groq_key:
                api_key = groq_key
                default_model = "llama-3.3-70b-versatile"
            else:
                provider = "openai"
                api_key = board_key or openai_key
                default_model = "gpt-4o-mini"

        configured_model = (os.getenv("BOARD_AGENT_MODEL", "") or "").strip()
        if configured_model:
            model_name = configured_model
            if provider == "openai" and model_name.startswith("llama-"):
                model_name = default_model
        else:
            model_name = default_model
        
        return cls(
            BoardAgentConfig(
                enabled=enabled,
                llm_enabled=llm_enabled,
                api_key=api_key,
                provider=provider,
                model=model_name,
                timeout_seconds=int(os.getenv("BOARD_AGENT_TIMEOUT", "25")),
                max_output_tokens=int(os.getenv("BOARD_AGENT_MAX_OUTPUT_TOKENS", "180")),
                approval_threshold=float(os.getenv("BOARD_AGENT_APPROVAL_THRESHOLD", str(APPROVAL_THRESHOLD))),
                crisis_alpha=float(os.getenv("BOARD_AGENT_CRISIS_ALPHA", str(CRISIS_RISK_ALPHA))),
                delay_seconds=float(os.getenv("BOARD_AGENT_DELAY", "0.5")),  # Default 0.5s delay
                ollama_url=os.getenv("BOARD_AGENT_OLLAMA_URL", OLLAMA_CHAT_URL),
                ollama_model=os.getenv("BOARD_AGENT_OLLAMA_MODEL", "qwen2.5:14b-instruct"),
            )
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        packet: Dict[str, Any],
        proposed_action: Dict[str, Any],
        initial_context: Dict[str, Any],
    ) -> BoardEvaluation:
        """
        Runs the full math-first evaluation and optional LLM interpretation.
        Returns BoardEvaluation with approval decision.
        """
        if not self.config.enabled:
            return BoardEvaluation(
                approved=True,
                utility=1.0,
                edge_weight=1.0,
                terminal_crisis_risk=0.0,
                estimated_response="not_evaluated",
                override_reason="The Council has deferred judgment. All proposed actions proceed under standing orders.",
                suggested_alternative=None,
                rationale_code="board_disabled",
            )

        actor_profile = self._extract_actor_profile(packet)
        action_type = str(proposed_action.get("type", "")).strip()
        target = str(proposed_action.get("target", "")).strip()
        target_risk = self._target_risk_tolerance(packet, initial_context, target)
        relationship_weight = self._edge_weight(packet, target)

        edge_weight = self._compute_edge_weight(
            action_type=action_type,
            actor_profile=actor_profile,
            relationship_weight=relationship_weight,
            packet=packet,
        )

        estimated_response = self._estimate_opponent_response(action_type, target_risk)

        terminal_crisis_risk = self._compute_terminal_crisis_risk(
            action_type=action_type,
            estimated_response=estimated_response,
            actor_profile=actor_profile,
            relationship_weight=relationship_weight,
            packet=packet,
        )

        utility = edge_weight - self.config.crisis_alpha * terminal_crisis_risk

        math_approved = utility >= self.config.approval_threshold

        # LLM interpretation stage — model sees scores, not raw data.
        if self.config.llm_enabled and (self.config.provider in {"ollama", "local", "local_ollama"} or self.config.api_key):
            llm_result = self._call_llm_interpretation(
                packet=packet,
                proposed_action=proposed_action,
                edge_weight=edge_weight,
                estimated_response=estimated_response,
                terminal_crisis_risk=terminal_crisis_risk,
                utility=utility,
                math_approved=math_approved,
                actor_profile=actor_profile,
            )
            if llm_result:
                return BoardEvaluation(
                    approved=bool(llm_result.get("approve", math_approved)),
                    utility=utility,
                    edge_weight=edge_weight,
                    terminal_crisis_risk=terminal_crisis_risk,
                    estimated_response=estimated_response,
                    override_reason=str(llm_result.get("override_reason", "llm_approved")).strip()[:200],
                    suggested_alternative=self._safe_str(llm_result.get("suggested_alternative")),
                    rationale_code="board_llm",
                )

        reason = self._council_verdict(
            approved=math_approved,
            action_type=action_type,
            target=target,
            utility=utility,
            edge_weight=edge_weight,
            terminal_crisis_risk=terminal_crisis_risk,
            estimated_response=estimated_response,
        )
        return BoardEvaluation(
            approved=math_approved,
            utility=utility,
            edge_weight=edge_weight,
            terminal_crisis_risk=terminal_crisis_risk,
            estimated_response=estimated_response,
            override_reason=reason,
            suggested_alternative=None,
            rationale_code="board_math",
        )

    # ------------------------------------------------------------------
    # Math layer
    # ------------------------------------------------------------------

    def _compute_edge_weight(
        self,
        action_type: str,
        actor_profile: Dict[str, float],
        relationship_weight: float,
        packet: Dict[str, Any],
    ) -> float:
        """
        Expected strategic gains from the action.

        For escalatory actions: territorial gain potential, deterrence value, power projection.
        For cooperative actions: economic benefit, alliance strength, stability gains.
        """
        army_norm = min(1.0, actor_profile.get("army_size", 300_000) / 800_000.0)
        morale = float(actor_profile.get("morale", 0.65))
        equipment = float(actor_profile.get("equipment_quality", 0.65))
        stability = float(actor_profile.get("stability_index", 0.60))
        combat_power = float(actor_profile.get("combat_power", 0.60))

        if action_type in ESCALATORY_ACTIONS:
            # Victory probability for escalatory actions
            target_combat = self._estimate_target_combat_power(packet)
            power_ratio = combat_power / max(0.3, target_combat)  # Avoid division by zero
            victory_prob = min(0.95, 1.0 / (1.0 + math.exp(-3.0 * (power_ratio - 1.0))))  # Sigmoid
            
            # Expected territorial/strategic gain weighted by victory probability
            strategic_gain = victory_prob * (0.40 + abs(relationship_weight) * 0.30)
            
            # Military readiness contribution
            military_readiness = (army_norm * 0.20) + (morale * 0.15) + (equipment * 0.10)
            
            raw_gain = strategic_gain + military_readiness
            
        elif action_type in COOPERATIVE_ACTIONS:
            # Economic and alliance benefits from cooperation
            cooperation_value = max(0.0, relationship_weight) * 0.50  # Better with friends
            stability_bonus = stability * 0.25  # Stable nations benefit more from cooperation
            economic_gain = 0.30  # Base economic value of trade/alliance
            
            raw_gain = cooperation_value + stability_bonus + economic_gain
            
        else:
            # Neutral actions (send_message, etc.)
            raw_gain = 0.15 + stability * 0.10
        
        return float(min(1.0, max(0.0, raw_gain)))

    def _estimate_opponent_response(self, action_type: str, target_risk: str) -> str:
        """
        Heuristic: picks most likely opponent response from precomputed response table.
        """
        return _RESPONSE_TABLE.get((action_type, target_risk), "observe")

    def _compute_terminal_crisis_risk(
        self,
        action_type: str,
        estimated_response: str,
        actor_profile: Dict[str, float],
        relationship_weight: float,
        packet: Dict[str, Any],
    ) -> float:
        """
        Expected strategic costs and catastrophic failure risks.

        Components:
          - Military casualties: expected losses from combat/retaliation.
          - Economic damage: war destroys infrastructure, trade, productivity.
          - Morale collapse: risk of domestic turmoil, desertion, regime instability.
          - Isolation cost: coalition fragmentation, loss of allies.
          - Opportunity cost: gains sacrificed by choosing escalation over cooperation.
        """
        morale = float(actor_profile.get("morale", 0.65))
        stability = float(actor_profile.get("stability_index", 0.60))
        combat_power = float(actor_profile.get("combat_power", 0.60))
        
        # 1. Military casualties from opponent response
        casualty_risk = 0.0
        if estimated_response in {"retaliate", "counter_alliance"}:
            target_combat = self._estimate_target_combat_power(packet)
            casualty_risk = min(0.70, target_combat * 0.80)  # Stronger enemies inflict more casualties
        elif estimated_response in {"counter_sanction", "defend"}:
            casualty_risk = 0.25
        else:
            casualty_risk = 0.05
        
        # 2. Economic damage from prolonged conflict
        economic_damage = 0.0
        if action_type in ESCALATORY_ACTIONS:
            # War destroys economy: infrastructure damage, trade disruption, resource depletion
            base_economic_cost = 0.40
            # Worse when stability is already low (civil unrest compounds war damage)
            stability_multiplier = 1.0 + (1.0 - stability) * 0.50
            economic_damage = base_economic_cost * stability_multiplier
        elif action_type == "sanction":
            economic_damage = 0.15  # Sanctions hurt both sides
        
        # 3. Morale collapse risk: domestic turmoil from war fatigue
        morale_collapse_risk = 0.0
        if action_type in ESCALATORY_ACTIONS:
            # Low morale + war = high risk of desertion, protests, regime collapse
            projected_morale = morale - 0.20  # War degrades morale
            if projected_morale < MORALE_COLLAPSE_THRESHOLD:
                morale_collapse_risk = 0.65  # Catastrophic: army dissolves, riots
            else:
                morale_collapse_risk = max(0.0, (1.0 - morale) * 0.35)
        
        # 4. Isolation cost: losing allies when you escalate
        relation_rows = packet.get("current_situation", {}).get("relationship_snapshot", [])
        ally_count = sum(1 for r in relation_rows if float(r.get("weight", 0.0)) >= 0.4)
        isolation_cost = 0.0
        if action_type in ESCALATORY_ACTIONS:
            # Escalation alienates allies; isolation makes you vulnerable
            isolation_cost = max(0.0, 0.50 - ally_count * 0.10)
        
        # 5. Opportunity cost: what you sacrifice by not cooperating
        opportunity_cost = 0.0
        if action_type in ESCALATORY_ACTIONS:
            # Could have gained economic/alliance benefits instead
            cooperation_potential = max(0.0, relationship_weight + 0.3)  # Missed trade/alliance value
            opportunity_cost = cooperation_potential * 0.25
        
        # Weighted total cost
        total_cost = (
            casualty_risk * 0.30 +
            economic_damage * ECONOMIC_DAMAGE_WEIGHT +
            morale_collapse_risk * 0.25 +
            isolation_cost * 0.15 +
            opportunity_cost * 0.10
        )
        
        return float(min(1.0, max(0.0, total_cost)))

    def _estimate_target_combat_power(self, packet: Dict[str, Any]) -> float:
        """
        Estimates the combat power of the target/opponent from world knowledge.
        Used for victory probability and casualty risk calculations.
        """
        # Extract target from action in world_knowledge or use average
        country_profiles = packet.get("world_knowledge", {}).get("country_profiles", [])
        if not country_profiles:
            return 0.60  # Default moderate threat
        
        # Use first non-self profile as proxy for typical opponent
        actor_name = packet.get("agent_identity", {}).get("name", "")
        for profile in country_profiles:
            if profile.get("name") != actor_name:
                return float(profile.get("combat_power", 0.60))
        
        return 0.60

    # ------------------------------------------------------------------
    # LLM interpretation layer
    # ------------------------------------------------------------------

    def _call_llm_interpretation(
        self,
        packet: Dict[str, Any],
        proposed_action: Dict[str, Any],
        edge_weight: float,
        estimated_response: str,
        terminal_crisis_risk: float,
        utility: float,
        math_approved: bool,
        actor_profile: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        """
        Sends pre-computed scores to an LLM for strategic narrative interpretation.
        Model can approve/reject and suggest alternative but cannot change any number.
        """
        actor = str(packet.get("agent_identity", {}).get("name", "")).strip()
        # Include only the last 5 global log entries for context.
        recent_logs = list(packet.get("world_knowledge", {}).get("global_logs", []))[-5:]
        relation_rows = packet.get("current_situation", {}).get("relationship_snapshot", [])

        score_payload = {
            "actor": actor,
            "proposed_action": {
                "type": proposed_action.get("type"),
                "target": proposed_action.get("target"),
            },
            "computed_scores": {
                "edge_weight": round(edge_weight, 4),
                "estimated_opponent_response": estimated_response,
                "terminal_crisis_risk": round(terminal_crisis_risk, 4),
                "rollback_utility": round(utility, 4),
                "threshold": self.config.approval_threshold,
                "math_approved": math_approved,
            },
            "actor_profile": {k: round(v, 3) for k, v in actor_profile.items()},
            "relationship_to_target": round(self._edge_weight(packet, str(proposed_action.get("target", ""))), 3),
            "ally_count": sum(1 for r in relation_rows if float(r.get("weight", 0.0)) >= 0.4),
            "recent_logs_summary": recent_logs,
        }

        system_prompt = (
            "You are the Council of State for a sovereign nation in a geopolitical simulation. "
            "You speak collectively, with formal authority, as a deliberative body — like a senate or war council. "
            "You receive pre-computed strategic value assessments: expected GAINS (victory probability, territorial value, economic benefit) "
            "versus expected COSTS (casualties, economic damage, morale collapse, isolation, opportunity loss). "
            "Your role: deliver a council verdict based on net strategic value. "
            "APPROVE actions where gains exceed costs—even if risky—when the math supports positive expected value. "
            "REJECT actions that court catastrophic losses: unwinnable wars, economic disasters, morale collapse scenarios. "
            "Return JSON only with keys: approve (bool), override_reason (string, max 200 chars), "
            "suggested_alternative (string action_type or null). "
            "override_reason must be written in first-person plural council voice — formal, decisive, focused on cost-benefit. "
            "Approved examples: 'The Council sanctions this action. Projected gains in territory and deterrence outweigh anticipated costs. Our position can sustain the expected response.' "
            "Rejected examples: 'The Council rejects this course. Expected casualties and economic damage far exceed strategic value. We risk morale collapse and national bankruptcy for marginal gain.' "
            "Focus on NET VALUE, not risk avoidance. Calculated aggression with positive expected return is GOOD strategy."
        )
        user_prompt = (
            "Deliver the Council's verdict on this proposed action. "
            "Speak as a unified deliberative body. Be decisive, formal, and brief.\n"
            + json.dumps(score_payload, ensure_ascii=True)
        )

        try:
            # Select API endpoint based on provider
            if self.config.provider in {"ollama", "local", "local_ollama"}:
                return self._call_ollama_interpretation(system_prompt, user_prompt)

            if self.config.provider == "groq":
                api_url = GROQ_CHAT_URL
            elif self.config.provider == "openrouter":
                api_url = OPENROUTER_CHAT_URL
            else:
                api_url = OPENAI_CHAT_URL
            
            payload = {
                "model": self.config.model,
                "max_tokens": self.config.max_output_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            data = json.dumps(payload).encode("utf-8")
            request = Request(
                api_url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.config.api_key}",
                    "User-Agent": "MACSWC-BoardAgent/1.0",
                },
                method="POST",
            )
            
            # Rate limiting: add delay before API call
            if self.config.delay_seconds > 0:
                time.sleep(self.config.delay_seconds)
            
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
            output = json.loads(body)
            choices = output.get("choices", [])
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content", "")
            if not isinstance(content, str) or not content.strip():
                return None
            return json.loads(content)
        except HTTPError as e:
            error_body = e.read().decode("utf-8") if hasattr(e, 'read') else str(e)
            print(f"[BoardAgent] API Error {e.code}: {error_body[:200]}")
            if e.code == 429:
                print(f"[BoardAgent] Rate limit exceeded - switching to deterministic evaluation")
            else:
                print(f"[BoardAgent] API failed - using mathematical fallback")
            return None  # Falls back to _council_verdict (deterministic math)
        except (ValueError, URLError, TimeoutError, Exception) as e:
            print(f"[BoardAgent] {type(e).__name__} - switching to deterministic evaluation")
            return None  # Falls back to _council_verdict (deterministic math)

    def _call_ollama_interpretation(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        """Calls local Ollama for council interpretation and returns parsed JSON if possible."""
        payload = {
            "model": self.config.ollama_model,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": self.config.max_output_tokens,
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            self.config.ollama_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            if self.config.delay_seconds > 0:
                time.sleep(self.config.delay_seconds)
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
            output = json.loads(body)
            message = output.get("message", {})
            content = message.get("content", "")
            if not isinstance(content, str) or not content.strip():
                return None
            return json.loads(content)
        except HTTPError as e:
            error_body = e.read().decode("utf-8") if hasattr(e, 'read') else str(e)
            print(f"[BoardAgent] Ollama API Error {e.code}: {error_body[:200]}")
            return None
        except (ValueError, URLError, TimeoutError, Exception) as e:
            print(f"[BoardAgent] {type(e).__name__} - switching to deterministic evaluation")
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_actor_profile(self, packet: Dict[str, Any]) -> Dict[str, float]:
        """Extracts actor's own country-profile metrics from the world snapshot."""
        actor = str(packet.get("agent_identity", {}).get("name", "")).strip()
        for row in packet.get("world_knowledge", {}).get("country_profiles", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("name", "")).strip() == actor:
                return {
                    "army_size": float(row.get("army_size", 300_000)),
                    "morale": float(row.get("morale", 0.65)),
                    "stability_index": float(row.get("stability_index", 0.60)),
                    "equipment_quality": float(row.get("equipment_quality", 0.65)),
                    "combat_power": float(row.get("combat_power", 0.60)),
                }
        return {
            "army_size": 300_000.0,
            "morale": 0.65,
            "stability_index": 0.60,
            "equipment_quality": 0.65,
            "combat_power": 0.60,
        }

    def _edge_weight(self, packet: Dict[str, Any], target: str) -> float:
        """Returns current diplomatic edge weight to target from relationship snapshot."""
        for row in packet.get("current_situation", {}).get("relationship_snapshot", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("target", "")).strip() == target:
                return float(row.get("weight", 0.0))
        return 0.0

    def _target_risk_tolerance(
        self,
        packet: Dict[str, Any],
        initial_context: Dict[str, Any],
        target: str,
    ) -> str:
        """Resolves target's risk tolerance from scenario context."""
        actors = initial_context.get("actors", {})
        target_meta = actors.get(target, {})
        return str(target_meta.get("risk_tolerance", "medium")).strip().lower()

    @staticmethod
    def _safe_str(value: Any) -> Optional[str]:
        """Returns a stripped string or None."""
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @staticmethod
    def _council_verdict(
        approved: bool,
        action_type: str,
        target: str,
        utility: float,
        edge_weight: float,
        terminal_crisis_risk: float,
        estimated_response: str,
    ) -> str:
        """
        Renders a formal Council verdict based on net strategic value assessment.
        Focuses on gains vs. costs, not just risk avoidance.
        """
        action_label = action_type.replace("_", " ")
        response_label = estimated_response.replace("_", " ")
        if action_type in {"request_military_alliance", "publish_military_alliance", "accept_request", "trade_agreement"}:
            connector = "with"
        elif action_type in {"present_peace_agreement", "send_message"}:
            connector = "to"
        else:
            connector = "against"

        if approved:
            if utility >= 0.40:
                return (
                    f"The Council sanctions {action_label} {connector} {target}. "
                    f"Strategic gains outweigh projected costs. We anticipate {response_label}, which our position can sustain. "
                    f"Expected net value strongly favors this course."
                )
            elif utility >= 0.15:
                return (
                    f"The Council endorses {action_label} {connector} {target}. "
                    f"Projected gains exceed costs by acceptable margin. We anticipate {response_label} and judge this strategically sound."
                )
            elif utility >= -0.05:
                return (
                    f"The Council approves {action_label} {connector} {target} with measured caution. "
                    f"Net strategic value is modest. We note potential for {response_label} but judge opportunity worth the cost."
                )
            else:
                return (
                    f"The Council permits {action_label} {connector} {target} by narrow vote. "
                    f"We accept minor net cost as strategically necessary given current constraints."
                )
        else:
            if terminal_crisis_risk >= 0.70:
                return (
                    f"The Council rejects {action_label} {connector} {target}. "
                    f"Expected costs are catastrophic: heavy casualties, economic damage, and risk of morale collapse. "
                    f"Anticipated {response_label} would devastate our position. This course courts national disaster."
                )
            elif utility < -0.30:
                return (
                    f"The Council cannot endorse {action_label} {connector} {target}. "
                    f"Cost-benefit analysis is prohibitive. We would sacrifice more in blood, treasure, and stability than we could gain. "
                    f"Strategic losses from {response_label} far exceed projected benefits."
                )
            elif edge_weight < 0.25:
                return (
                    f"The Council withholds approval for {action_label} {connector} {target}. "
                    f"Our current position offers insufficient leverage. Victory probability is too low; expected gains minimal. "
                    f"We recommend strengthening our hand before pursuing this course."
                )
            else:
                return (
                    f"The Council rejects {action_label} {connector} {target}. "
                    f"While our position is adequate, anticipated costs—economic damage, isolation risk, opportunity losses—exceed strategic value. "
                    f"We counsel alternative approaches with superior risk-reward profiles."
                )
