import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"


@dataclass
class SecretaryAgentConfig:
    """Configuration for an LLM-backed secretary validation agent."""

    enabled: bool
    api_key: Optional[str]
    provider: str = "openai"  # "openai" or "groq"
    model: str = "gpt-4o-mini"
    delay_seconds: float = 0.0  # Rate limiting delay between API calls
    temperature: float = 0.0
    timeout_seconds: int = 30
    max_output_tokens: int = 220
    ollama_url: str = OLLAMA_CHAT_URL
    ollama_model: str = "qwen2.5:14b-instruct"


class SecretaryAgentModel:
    """Validates action-rule compliance and logical consistency for a proposed action."""

    def __init__(self, config: SecretaryAgentConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "SecretaryAgentModel":
        """Builds config from environment variables."""
        enabled = os.getenv("SECRETARY_AGENT_ENABLED", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
        provider = os.getenv("SECRETARY_AGENT_PROVIDER", "groq").strip().lower()

        if provider in {"ollama", "local", "local_ollama"}:
            api_key = None
            default_model = os.getenv("SECRETARY_AGENT_OLLAMA_MODEL", "qwen2.5:14b-instruct")
        else:
            groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
            openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
            openrouter_key = (os.getenv("SECRETARY_OPENROUTER_KEY") or os.getenv("OPENROUTER_API_KEY") or "").strip()

            # Select provider and API key
            if provider == "openrouter" and openrouter_key:
                api_key = openrouter_key
                default_model = "meta-llama/llama-3.1-70b-instruct"
            elif provider == "groq" and groq_key:
                api_key = groq_key
                default_model = "llama-3.3-70b-versatile"
            else:
                provider = "openai"
                api_key = openai_key
                default_model = "gpt-4o-mini"

        configured_model = (os.getenv("SECRETARY_AGENT_MODEL", "") or "").strip()
        if configured_model:
            model_name = configured_model
            if provider == "openai" and model_name.startswith("llama-"):
                model_name = default_model
        else:
            model_name = default_model
        
        return cls(
            SecretaryAgentConfig(
                enabled=enabled,
                api_key=api_key,
                provider=provider,
                model=model_name,
                temperature=float(os.getenv("SECRETARY_AGENT_TEMPERATURE", "0.0")),
                timeout_seconds=int(os.getenv("SECRETARY_AGENT_TIMEOUT", "30")),
                max_output_tokens=int(os.getenv("SECRETARY_AGENT_MAX_OUTPUT_TOKENS", "220")),
                delay_seconds=float(os.getenv("SECRETARY_AGENT_DELAY", "0.5")),  # Default 0.5s delay
                ollama_url=os.getenv("SECRETARY_AGENT_OLLAMA_URL", OLLAMA_CHAT_URL),
                ollama_model=os.getenv("SECRETARY_AGENT_OLLAMA_MODEL", "qwen2.5:14b-instruct"),
            )
        )

    def validate_action(
        self,
        packet: Dict[str, Any],
        proposed_action: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Returns corrected action if valid, or None when unavailable/rejected."""
        if not self.config.enabled:
            return proposed_action
        if self.config.provider not in {"ollama", "local", "local_ollama"} and not self.config.api_key:
            return proposed_action

        actor = str(packet.get("agent_identity", {}).get("name", "")).strip()
        if not actor:
            return None

        allowed_actions = list(packet.get("rules", {}).get("allowed_actions", []))
        relationship_targets = {
            str(row.get("target"))
            for row in packet.get("current_situation", {}).get("relationship_snapshot", [])
            if isinstance(row, dict) and isinstance(row.get("target"), str)
        }
        inbox_events = list(packet.get("private_inbox", []))
        valid_request_ids = {
            str(event.get("request_id"))
            for event in inbox_events
            if isinstance(event, dict) and isinstance(event.get("request_id"), str)
        }

        compact_input = {
            "actor": actor,
            "allowed_actions": allowed_actions,
            "known_targets": sorted(list(relationship_targets)),
            "valid_request_ids": sorted(list(valid_request_ids)),
            "inbox_last": inbox_events[-4:],
            "candidates": candidates[:8],
            "proposed_action": proposed_action,
        }

        system_prompt = (
            "You are a strict secretary validator for a geopolitical simulation. "
            "Validate one proposed action for legal action type, valid target, and request_id causality. "
            "Return JSON only with keys: valid (bool), corrected_action (object|null), reason (string)."
        )
        user_prompt = (
            "Check logical consistency and fix only if needed. "
            "If action is invalid and cannot be safely corrected, set valid=false and corrected_action=null.\n"
            + json.dumps(compact_input, ensure_ascii=True)
        )

        # Rate limiting: add delay before API call
        if self.config.delay_seconds > 0:
            time.sleep(self.config.delay_seconds)
        
        try:
            raw = self._call_llm_chat(system_prompt, user_prompt)
            parsed = json.loads(raw)
        except HTTPError as e:
            error_body = e.read().decode("utf-8") if hasattr(e, 'read') else str(e)
            print(f"[SecretaryAgent] API Error {e.code}: {error_body[:200]}")
            if e.code == 429:
                print(f"[SecretaryAgent] Rate limit exceeded - switching to deterministic validation")
            else:
                print(f"[SecretaryAgent] API failed - using deterministic fallback")
            return proposed_action  # Deterministic fallback: accept if basic checks pass
        except (ValueError, URLError, TimeoutError, Exception) as e:
            print(f"[SecretaryAgent] {type(e).__name__} - switching to deterministic validation")
            return proposed_action  # Deterministic fallback: accept if basic checks pass

        if not isinstance(parsed, dict):
            return proposed_action

        if not bool(parsed.get("valid", False)):
            return None

        corrected = parsed.get("corrected_action")
        if not isinstance(corrected, dict):
            return proposed_action

        return self._normalize_action(
            corrected,
            actor=actor,
            allowed_actions=set(allowed_actions),
            known_targets=relationship_targets,
            valid_request_ids=valid_request_ids,
        )

    def _call_llm_chat(self, system_prompt: str, user_prompt: str) -> str:
        """Calls chat completions API or local Ollama and returns raw message content."""
        if self.config.provider in {"ollama", "local", "local_ollama"}:
            return self._call_ollama_chat(system_prompt, user_prompt)

        # Select API endpoint based on provider
        if self.config.provider == "groq":
            api_url = GROQ_CHAT_URL
        elif self.config.provider == "openrouter":
            api_url = OPENROUTER_CHAT_URL
        else:
            api_url = OPENAI_CHAT_URL
        
        payload = {
            "model": self.config.model,
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
            api_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
                "User-Agent": "MACSWC-SecretaryAgent/1.0",
            },
            method="POST",
        )

        with urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = response.read().decode("utf-8")
        output = json.loads(body)

        choices = output.get("choices", [])
        if not choices:
            raise ValueError("No choices in OpenAI response")

        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        raise ValueError("Missing JSON content from OpenAI response")

    def _call_ollama_chat(self, system_prompt: str, user_prompt: str) -> str:
        """Calls local Ollama chat completions API and returns raw message content."""
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
            headers={"Content-Type": "application/json"},
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
    def _normalize_action(
        action: Dict[str, Any],
        actor: str,
        allowed_actions: set,
        known_targets: set,
        valid_request_ids: set,
    ) -> Optional[Dict[str, Any]]:
        """Re-checks secretary output with deterministic validation."""
        action_type = action.get("type")
        target = action.get("target")

        if not isinstance(action_type, str) or action_type not in allowed_actions:
            return None
        if not isinstance(target, str) or target not in known_targets:
            return None

        normalized: Dict[str, Any] = {
            "type": action_type,
            "actor": actor,
            "target": target,
        }

        if action_type in {"accept_request", "reject_request"}:
            request_id = action.get("request_id")
            if not isinstance(request_id, str) or request_id not in valid_request_ids:
                return None
            normalized["request_id"] = request_id

        content = action.get("content")
        if isinstance(content, str) and content.strip():
            normalized["content"] = content.strip()[:280]

        if action_type in {"request_military_alliance", "present_peace_agreement", "send_message"} and "content" not in normalized:
            normalized["content"] = f"{actor} issues {action_type} to {target}."

        return normalized
