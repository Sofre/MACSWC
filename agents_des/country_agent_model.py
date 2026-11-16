import json
import os
import re
from dataclasses import dataclass
from socket import timeout as SocketTimeout
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen




HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class CountryAgentConfig:
    """Configuration for an API/local-backed country agent."""

    backend: str
    enabled: bool
    api_key: Optional[str]
    model: str = "Qwen/Qwen2.5-72B-Instruct"
    temperature: float = 0.2
    timeout_seconds: int = 35
    ollama_url: str = "http://localhost:11434/api/chat"
    ollama_model: str = "qwen2.5:14b-instruct"
    max_output_tokens: int = 220
    max_candidate_actions: int = 10
    max_relationship_rows: int = 8
    max_country_profiles: int = 10
    max_global_logs: int = 8
    max_inbox_events: int = 5


class CountryAgentModel:
    """Generates one country action using a prompt-based LLM backend."""

    MIN_THOUGHT_WORDS = 20
    MAX_THOUGHT_WORDS = 40
    MAX_PLANNING_ITEMS = 3
    MAX_CARD_TEXT = 140

    def __init__(self, config: CountryAgentConfig):
        self.config = config

    @staticmethod
    def _debug_enabled() -> bool:
        return os.getenv("AGENT_DEBUG", "0").strip().lower() in {"1", "true", "yes"}

    @classmethod
    def from_env(cls) -> "CountryAgentModel":
        """Builds config from environment variables."""

        enabled = os.getenv("COUNTRY_AGENT_ENABLED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
        backend = os.getenv("COUNTRY_AGENT_BACKEND", "hf_api").strip().lower()

        if backend in {"groq_api", "groq"}:
            api_key = (os.getenv("GROQ_API_KEY") or "").strip()
            default_model = "llama-3.1-8b-instant"
        elif backend in {"openrouter_api", "openrouter"}:
            api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
            default_model = "meta-llama/llama-3.1-8b-instruct"
        else:
            api_key = (os.getenv("HF_TOKEN") or "").strip()
            default_model = "Qwen/Qwen2.5-72B-Instruct"

        model_name = os.getenv("COUNTRY_AGENT_MODEL", default_model).strip()
        return cls(
            CountryAgentConfig(
                backend=backend,
                enabled=enabled,
                api_key=api_key,
                model=model_name,
                temperature=float(os.getenv("COUNTRY_AGENT_TEMPERATURE", "0.2")),
                timeout_seconds=int(os.getenv("COUNTRY_AGENT_TIMEOUT", "35")),
                ollama_url=os.getenv("COUNTRY_AGENT_OLLAMA_URL", "http://localhost:11434/api/chat"),
                ollama_model=os.getenv("COUNTRY_AGENT_OLLAMA_MODEL", "qwen2.5:14b-instruct"),
                max_output_tokens=int(os.getenv("COUNTRY_AGENT_MAX_OUTPUT_TOKENS", "220")),
                max_candidate_actions=int(os.getenv("COUNTRY_AGENT_MAX_CANDIDATES", "10")),
                max_relationship_rows=int(os.getenv("COUNTRY_AGENT_MAX_RELATIONSHIPS", "8")),
                max_country_profiles=int(os.getenv("COUNTRY_AGENT_MAX_PROFILES", "10")),
                max_global_logs=int(os.getenv("COUNTRY_AGENT_MAX_LOGS", "8")),
                max_inbox_events=int(os.getenv("COUNTRY_AGENT_MAX_INBOX", "5")),
            )
        )

    def propose_action(
        self,
        packet: Dict[str, Any],
        initial_context: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Returns one validated action proposal, or None when unavailable/invalid."""
        if not self.config.enabled:
            return None
        if not candidates:
            return None

        actor = str(packet.get("agent_identity", {}).get("name", "")).strip()
        if not actor:
            return None

        allowed_actions = list(packet.get("rules", {}).get("allowed_actions", []))
        known_targets = self._known_targets(packet)
        pending_ids = self._pending_request_ids(packet)
        compact_packet = self._compact_packet(packet)
        compact_candidates = candidates[: max(1, self.config.max_candidate_actions)]
        planning_mode = self._planning_mode(packet, initial_context)

        prompt_payload = {
            "agent_identity": compact_packet.get("agent_identity", {}),
            "goals": compact_packet.get("goals", {}),
            "world_knowledge": compact_packet.get("world_knowledge", {}),
            "private_inbox": compact_packet.get("private_inbox", []),
            "capabilities": compact_packet.get("capabilities", {}),
            "allowed_actions": allowed_actions,
            "known_targets": known_targets,
            "request_ids_in_inbox": pending_ids,
            "candidate_actions": compact_candidates,
            "scenario": self._build_scenario_payload(initial_context, actor),
            "planning_mode": planning_mode,
        }
        # System prompt is used for fixed instructions
        system_prompt = (
            "You are a sovereign country agent in a geopolitical simulation. "
            "Assess threats, alliances, leverage, timing, and opportunity before choosing. "
            "Choose exactly one action from candidate_actions. "
            "Return valid JSON only, with keys: type, actor, target, optional request_id, optional content, "
            "optional thought_summary, optional ally_candidates, optional enemy_candidates, optional strategic_options, optional selected_rationale, "
            "optional headline, optional public_message, optional private_intent, optional visual_motif, optional card_style_hint. "
            "planning_mode controls depth: if full_4_step, include all planning fields using concise bullet-like text; if short_update, include only selected_rationale and thought_summary. "
            "thought_summary must be a single first-person visible reasoning note between 20 and 40 words. "
            "Prefer adaptive strategy over repetitive loops unless repeating the same move is clearly justified by the situation. "
            "Card fields should be short, vivid, and structured for UI rendering, not long prose. "
            "It should read like a brief internal monologue summary, not hidden chain-of-thought or a long explanation. "
            "Do not return markdown, prose, or extra keys."
        )
        # Used for dynamic content, including the current situation, candidate actions, and other context
        user_prompt = (
            "Use this packet to select exactly one action. "
            "Hard constraints: action type must be in allowed_actions, target must be in known_targets, "
            "and thought_summary must stay between 20 and 40 words. "
            "ally_candidates and enemy_candidates should each contain up to 3 country names from known_targets. "
            "strategic_options should contain up to 3 concise options. "
            "headline should be 4 to 10 words, public_message and private_intent should each be concise, and visual_motif/card_style_hint should be compact UI hints. "
            "and accept_request/reject_request must use a request_id from request_ids_in_inbox.\n"
            + json.dumps(prompt_payload, ensure_ascii=True)
        )

    # A fallback is on local run. Using hardware (RTX 2050 4VRAM with 16 Random Access Memory of the Computer)
        try:
            if self.config.backend in {"local_ollama", "ollama", "local"}:
                raw = self._call_ollama_chat(system_prompt, user_prompt)
            elif self.config.backend in {"groq_api", "groq"}:
                if not self.config.api_key:
                    if self._debug_enabled():
                        print("[COUNTRY_DEBUG] Missing Groq key for country agent")
                    return None
                raw = self._call_groq_chat(system_prompt, user_prompt)
            elif self.config.backend in {"openrouter_api", "openrouter"}:
                if not self.config.api_key:
                    if self._debug_enabled():
                        print("[COUNTRY_DEBUG] Missing OpenRouter key for country agent")
                    return None
                raw = self._call_openrouter_chat(system_prompt, user_prompt)
            else:
                if not self.config.api_key:
                    if self._debug_enabled():
                        print("[COUNTRY_DEBUG] Missing HF token for country agent")
                    return None
                raw = self._call_hf_chat(system_prompt, user_prompt)
            parsed = self._parse_model_json(raw)
            if not isinstance(parsed, dict):
                if self._debug_enabled():
                    print(f"[COUNTRY_DEBUG] JSON parse failed. raw={str(raw)[:220]}")
                return None
        except (HTTPError, URLError, TimeoutError, SocketTimeout, ValueError) as exc:
            if self._debug_enabled():
                print(f"[COUNTRY_DEBUG] Provider call failed: {type(exc).__name__}: {exc}")
            return None

        normalized = self._normalize_action(
            parsed_action=parsed,
            actor=actor,
            allowed_actions=allowed_actions,
            known_targets=known_targets,
            pending_ids=set(pending_ids),
        )
        if normalized is None and self._debug_enabled():
            print(f"[COUNTRY_DEBUG] Normalization rejected action: {parsed}")
        return normalized

    @staticmethod
    def _parse_model_json(raw: str) -> Optional[Dict[str, Any]]:
        """Parses JSON payloads, including markdown-wrapped code blocks returned by some providers."""
        if not isinstance(raw, str):
            return None

        text = raw.strip()
        if not text:
            return None

        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except ValueError:
            pass

        # Handle fenced responses like: ```json { ... } ```
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            candidate = "\n".join(lines).strip()
            try:
                parsed = json.loads(candidate)
                return parsed if isinstance(parsed, dict) else None
            except ValueError:
                pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                parsed = json.loads(candidate)
                return parsed if isinstance(parsed, dict) else None
            except ValueError:
                pass

        # Last resort: recover core fields from quasi-JSON text.
        # Some providers emit malformed JSON (e.g., broken escaping/newlines in long strings).
        recovered: Dict[str, Any] = {}
        for key in (
            "type",
            "actor",
            "target",
            "request_id",
            "content",
            "thought_summary",
            "selected_rationale",
            "headline",
            "public_message",
            "private_intent",
            "visual_motif",
            "card_style_hint",
        ):
            match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', text, flags=re.DOTALL)
            if match:
                raw_value = match.group(1)
                recovered[key] = bytes(raw_value, "utf-8").decode("unicode_escape").strip()

        list_keys = ("ally_candidates", "enemy_candidates", "strategic_options")
        for key in list_keys:
            match = re.search(rf'"{re.escape(key)}"\s*:\s*\[(.*?)\]', text, flags=re.DOTALL)
            if not match:
                continue
            items = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', match.group(1), flags=re.DOTALL)
            if items:
                recovered[key] = [bytes(item, "utf-8").decode("unicode_escape").strip() for item in items if item.strip()]

        if "type" in recovered and "actor" in recovered and "target" in recovered:
            return recovered

        return None

    @staticmethod
    def _build_scenario_payload(initial_context: Dict[str, Any], actor: str) -> Dict[str, Any]:
        """Builds compact scenario framing so the model gets strategic context, not just labels."""
        actor_meta = initial_context.get("actors", {}).get(actor, {})
        return {
            "scenario_id": initial_context.get("scenario_id"),
            "scenario_title": initial_context.get("scenario_title"),
            "timeframe": initial_context.get("timeframe"),
            "context_anchor": initial_context.get("context_anchor"),
            "strategic_brief": CountryAgentModel._build_strategic_brief(initial_context, actor, actor_meta),
        }

    @staticmethod
    def _build_strategic_brief(
        initial_context: Dict[str, Any],
        actor: str,
        actor_meta: Dict[str, Any],
    ) -> str:
        """Creates a short scenario-aware instruction that sharpens strategic posture."""
        title = str(initial_context.get("scenario_title", "")).lower()
        anchor = str(initial_context.get("context_anchor", "")).strip()
        risk_tolerance = str(actor_meta.get("risk_tolerance", "medium")).strip().lower()

        scenario_pressure = (
            "This is a high-tension wartime scenario where coercion, opportunistic escalation, and rapid alliance shifts are plausible."
            if any(keyword in title for keyword in {"war", "breakdown", "offensive", "coalition"})
            else "This is a geopolitical competition scenario where signaling, coercion, and diplomacy all remain viable."
        )

        posture_hint = {
            "high": "Adopt an assertive posture: when hostile relationships and goals support it, offensive escalation is acceptable and often strategically sound.",
            "medium": "Adopt a pragmatic posture: balance deterrence, alliance management, and escalation risk; calculated aggression is viable when conditions favor it.",
            "low": "Adopt a cautious posture: prefer de-escalation and stability unless pressure strongly favors escalation.",
        }.get(risk_tolerance, "Adopt a pragmatic posture: balance deterrence, alliance management, and escalation risk; calculated aggression is viable when conditions favor it.")

        anchor_text = f"Historical anchor: {anchor}." if anchor else ""
        strategic_note = "Strategic Council will evaluate risk and approve actions that advance position without reckless exposure."
        return " ".join(part for part in [anchor_text, scenario_pressure, f"Actor focus: {actor}.", posture_hint, strategic_note] if part)

    def _call_hf_chat(self, system_prompt: str, user_prompt: str) -> str:
        """Calls HF router using an OpenAI-compatible chat-completions payload."""
        model_candidates: List[str] = []
        configured_model = (self.config.model or "").strip()
        base_model = configured_model.split(":", 1)[0].strip() if configured_model else ""
        if base_model:
            model_candidates.append(base_model)
        if configured_model and configured_model not in model_candidates:
            model_candidates.append(configured_model)

        if "Qwen/Qwen2.5-72B-Instruct" not in model_candidates:
            model_candidates.append("Qwen/Qwen2.5-72B-Instruct")

        last_error: Optional[Exception] = None
        for model_name in model_candidates:
            payload = {
                "model": model_name,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_output_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            data = json.dumps(payload).encode("utf-8")
            request = Request(
                HF_ROUTER_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.config.api_key}",
                },
                method="POST",
            )

            try:
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                output = json.loads(body)

                choices = output.get("choices", [])
                if not choices:
                    raise ValueError("No choices in HF response")

                message = choices[0].get("message", {})
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                raise ValueError("Missing JSON content from HF response")
            except HTTPError as exc:
                last_error = exc
                if exc.code in {400, 403, 404}:
                    if self._debug_enabled():
                        print(f"[COUNTRY_DEBUG] HF model '{model_name}' rejected with HTTP {exc.code}; trying next candidate")
                    continue
                raise
            except Exception as exc:
                last_error = exc
                if self._debug_enabled():
                    print(f"[COUNTRY_DEBUG] HF model '{model_name}' failed: {type(exc).__name__}: {exc}")
                continue

        if last_error:
            raise last_error
        raise ValueError("HF model selection failed with no candidates")

    def _call_groq_chat(self, system_prompt: str, user_prompt: str) -> str:
        """Calls Groq chat-completions API for country-agent inference."""
        model_candidates: List[str] = []
        configured_model = (self.config.model or "").strip()
        if configured_model:
            model_candidates.append(configured_model)
        if "llama-3.1-8b-instant" not in model_candidates:
            model_candidates.append("llama-3.1-8b-instant")
        if "llama-3.3-70b-versatile" not in model_candidates:
            model_candidates.append("llama-3.3-70b-versatile")

        last_error: Optional[Exception] = None
        for model_name in model_candidates:
            payload = {
                "model": model_name,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_output_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            data = json.dumps(payload).encode("utf-8")
            request = Request(
                GROQ_CHAT_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.config.api_key}",
                    "User-Agent": "MACSWC-CountryAgent/1.0",
                },
                method="POST",
            )

            try:
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                output = json.loads(body)

                choices = output.get("choices", [])
                if not choices:
                    raise ValueError("No choices in Groq response")

                message = choices[0].get("message", {})
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                raise ValueError("Missing JSON content from Groq response")
            except HTTPError as exc:
                last_error = exc
                if exc.code in {400, 403, 404, 429}:
                    if self._debug_enabled():
                        print(f"[COUNTRY_DEBUG] Groq model '{model_name}' rejected with HTTP {exc.code}; trying next candidate")
                    continue
                raise
            except Exception as exc:
                last_error = exc
                if self._debug_enabled():
                    print(f"[COUNTRY_DEBUG] Groq model '{model_name}' failed: {type(exc).__name__}: {exc}")
                continue

        if last_error:
            raise last_error
        raise ValueError("Groq model selection failed with no candidates")

    def _call_openrouter_chat(self, system_prompt: str, user_prompt: str) -> str:
        """Calls OpenRouter chat-completions API for country-agent inference."""
        configured_model = (self.config.model or "meta-llama/llama-3.1-8b-instruct").strip()
        
        payload = {
            "model": configured_model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            OPENROUTER_CHAT_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
                "HTTP-Referer": "https://github.com/MACSWC",
                "X-Title": "MACSWC Country Agent",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
            output = json.loads(body)

            choices = output.get("choices", [])
            if not choices:
                raise ValueError("No choices in OpenRouter response")

            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
            raise ValueError("Missing JSON content from OpenRouter response")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8") if hasattr(exc, 'read') else str(exc)
            if self._debug_enabled():
                print(f"[COUNTRY_DEBUG] OpenRouter HTTP {exc.code}: {error_body[:200]}")
            raise

    def _call_ollama_chat(self, system_prompt: str, user_prompt: str) -> str:
        """Calls a local Ollama server for country-agent inference."""
        payload = {
            "model": self.config.ollama_model,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
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
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = response.read().decode("utf-8")
        output = json.loads(body)

        message = output.get("message", {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        raise ValueError("Missing JSON content from Ollama response")

    @staticmethod
    def _canonical_token(value: str) -> str:
        """Lowercases and normalizes separators for fuzzy token matching."""
        return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

    @staticmethod
    def _resolve_from_allowed(raw_value: Any, allowed_values: List[str]) -> Optional[str]:
        """Resolves a model string to the closest allowed value using canonical matching."""
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None

        raw = raw_value.strip()
        if raw in allowed_values:
            return raw

        canonical = CountryAgentModel._canonical_token(raw)
        for candidate in allowed_values:
            if CountryAgentModel._canonical_token(candidate) == canonical:
                return candidate
        return None

    @staticmethod
    def _known_targets(packet: Dict[str, Any]) -> List[str]:
        """Collects valid target names from relationship rows and inbox origins."""
        targets: List[str] = []
        for row in packet.get("current_situation", {}).get("relationship_snapshot", []):
            target = row.get("target")
            if isinstance(target, str) and target and target not in targets:
                targets.append(target)

        for event in packet.get("private_inbox", []):
            origin = event.get("action", {}).get("actor") if isinstance(event.get("action"), dict) else None
            if isinstance(origin, str) and origin and origin not in targets:
                targets.append(origin)

        return targets

    @staticmethod
    def _pending_request_ids(packet: Dict[str, Any]) -> List[str]:
        """Returns pending request ids visible in the actor inbox."""
        request_ids: List[str] = []
        for event in packet.get("private_inbox", []):
            req_id = event.get("request_id")
            if isinstance(req_id, str) and req_id:
                request_ids.append(req_id)
        return request_ids

    def _compact_packet(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        """Limits packet size before prompting to reduce token spend."""
        world = packet.get("world_knowledge", {}) if isinstance(packet.get("world_knowledge"), dict) else {}

        compact_world = {
            "round": world.get("round"),
            "country_profiles": list(world.get("country_profiles", []))[: max(1, self.config.max_country_profiles)],
            "relationship_snapshot": list(world.get("relationship_snapshot", []))[: max(1, self.config.max_relationship_rows)],
            "global_logs": list(world.get("global_logs", []))[-max(1, self.config.max_global_logs) :],
        }

        return {
            "agent_identity": packet.get("agent_identity", {}),
            "goals": packet.get("goals", {}),
            "world_knowledge": compact_world,
            "private_inbox": list(packet.get("private_inbox", []))[-max(1, self.config.max_inbox_events) :],
            "capabilities": packet.get("capabilities", {}),
        }

    @staticmethod
    def _normalize_action(
        parsed_action: Dict[str, Any],
        actor: str,
        allowed_actions: List[str],
        known_targets: List[str],
        pending_ids: set,
    ) -> Optional[Dict[str, Any]]:
        """Validates and normalizes model output into engine-safe action shape."""
        action_type = CountryAgentModel._resolve_from_allowed(parsed_action.get("type"), allowed_actions)
        target = CountryAgentModel._resolve_from_allowed(parsed_action.get("target"), known_targets)

        if not action_type:
            return None
        if not target:
            return None

        normalized: Dict[str, Any] = {
            "type": action_type,
            "actor": actor,
            "target": target,
        }

        request_id = parsed_action.get("request_id")
        if action_type in {"accept_request", "reject_request"}:
            if not isinstance(request_id, str) or request_id not in pending_ids:
                return None
            normalized["request_id"] = request_id

        content = parsed_action.get("content")
        if isinstance(content, str) and content.strip():
            normalized["content"] = content.strip()[:280]

        if action_type in {"request_military_alliance", "present_peace_agreement", "send_message"} and "content" not in normalized:
            normalized["content"] = f"{actor} issues {action_type} to {target}."

        thought_summary = CountryAgentModel._normalize_thought_summary(
            parsed_action.get("thought_summary"),
            actor=actor,
            action_type=action_type,
            target=target,
        )
        if thought_summary:
            normalized["thought_summary"] = thought_summary

        ally_candidates = CountryAgentModel._normalize_country_list(
            parsed_action.get("ally_candidates"),
            known_targets=known_targets,
        )
        if ally_candidates:
            normalized["ally_candidates"] = ally_candidates

        enemy_candidates = CountryAgentModel._normalize_country_list(
            parsed_action.get("enemy_candidates"),
            known_targets=known_targets,
        )
        if enemy_candidates:
            normalized["enemy_candidates"] = enemy_candidates

        strategic_options = CountryAgentModel._normalize_option_list(parsed_action.get("strategic_options"))
        if strategic_options:
            normalized["strategic_options"] = strategic_options

        selected_rationale = CountryAgentModel._normalize_selected_rationale(parsed_action.get("selected_rationale"))
        if selected_rationale:
            normalized["selected_rationale"] = selected_rationale

        headline = CountryAgentModel._normalize_card_text(parsed_action.get("headline"), 64)
        if headline:
            normalized["headline"] = headline

        public_message = CountryAgentModel._normalize_card_text(parsed_action.get("public_message"), CountryAgentModel.MAX_CARD_TEXT)
        if public_message:
            normalized["public_message"] = public_message

        private_intent = CountryAgentModel._normalize_card_text(parsed_action.get("private_intent"), CountryAgentModel.MAX_CARD_TEXT)
        if private_intent:
            normalized["private_intent"] = private_intent

        visual_motif = CountryAgentModel._normalize_card_text(parsed_action.get("visual_motif"), 48)
        if visual_motif:
            normalized["visual_motif"] = visual_motif

        card_style_hint = CountryAgentModel._normalize_card_text(parsed_action.get("card_style_hint"), 48)
        if card_style_hint:
            normalized["card_style_hint"] = card_style_hint

        return normalized

    @staticmethod
    def _planning_mode(packet: Dict[str, Any], initial_context: Dict[str, Any]) -> str:
        """Selects full or short planning depth based on milestone round cadence."""
        round_number = int(packet.get("world_knowledge", {}).get("round", 0))
        cadence_raw = initial_context.get("agent_policy", {}).get("planning_milestone_every", 2)
        try:
            cadence = max(1, int(cadence_raw))
        except (TypeError, ValueError):
            cadence = 2

        if round_number <= 1:
            return "full_4_step"
        if round_number % cadence == 0:
            return "full_4_step"
        return "short_update"

    @classmethod
    def _normalize_thought_summary(
        cls,
        thought_summary: Any,
        actor: str,
        action_type: str,
        target: str,
    ) -> str:
        """Normalizes a short visible reasoning note into a 20-40 word summary."""
        if not isinstance(thought_summary, str) or not thought_summary.strip():
            thought_summary = cls._default_thought_summary(actor, action_type, target)

        words = thought_summary.replace("\n", " ").split()
        if len(words) < cls.MIN_THOUGHT_WORDS:
            filler = "I need a credible move that improves leverage without wasting initiative in this round."
            words.extend(filler.split())
        if len(words) > cls.MAX_THOUGHT_WORDS:
            words = words[: cls.MAX_THOUGHT_WORDS]

        return " ".join(words).strip()

    @staticmethod
    def _default_thought_summary(actor: str, action_type: str, target: str) -> str:
        """Builds a fallback visible reasoning note when the model omits one."""
        return (
            f"I am weighing pressure, timing, and exposure, and this {action_type} toward {target} looks like "
            f"the clearest move for {actor} to improve position while keeping strategic initiative in hand today."
        )

    @classmethod
    def _normalize_country_list(cls, values: Any, known_targets: List[str]) -> List[str]:
        """Normalizes ally/enemy candidate country lists to known targets only."""
        if not isinstance(values, list):
            return []

        normalized: List[str] = []
        allowed = set(known_targets)
        for value in values:
            if not isinstance(value, str):
                continue
            item = value.strip()
            if not item or item not in allowed:
                continue
            if item in normalized:
                continue
            normalized.append(item)
            if len(normalized) >= cls.MAX_PLANNING_ITEMS:
                break
        return normalized

    @classmethod
    def _normalize_option_list(cls, values: Any) -> List[str]:
        """Normalizes compact strategic option text list."""
        if not isinstance(values, list):
            return []

        normalized: List[str] = []
        for value in values:
            if not isinstance(value, str):
                continue
            item = " ".join(value.replace("\n", " ").split()).strip()
            if not item:
                continue
            if item in normalized:
                continue
            normalized.append(item[:120])
            if len(normalized) >= cls.MAX_PLANNING_ITEMS:
                break
        return normalized

    @staticmethod
    def _normalize_selected_rationale(value: Any) -> str:
        """Normalizes compact selected rationale string."""
        if not isinstance(value, str):
            return ""
        normalized = " ".join(value.replace("\n", " ").split()).strip()
        return normalized[:180] if normalized else ""

    @staticmethod
    def _normalize_card_text(value: Any, max_length: int) -> str:
        """Normalizes compact UI-facing card metadata text."""
        if not isinstance(value, str):
            return ""
        normalized = " ".join(value.replace("\n", " ").split()).strip()
        return normalized[:max_length] if normalized else ""
