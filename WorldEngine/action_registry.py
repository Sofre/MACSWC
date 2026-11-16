from dataclasses import dataclass
from typing import Dict

@dataclass
# Defined as Action Rules in Diagrams 
class ActionDef:
    name: str
    publicity: str  # "public" or "private"
    require_response: bool
    input_type: str # "target_only" or "target_and_message"

ACTION_REGISTRY: Dict[str, ActionDef] = {
    # Private actions that require a response and a textual message
    "request_military_alliance": ActionDef("request_military_alliance", "private", True, "target_and_message"),
    "present_peace_agreement": ActionDef("present_peace_agreement", "private", True, "target_and_message"),
    "send_message": ActionDef("send_message", "private", True, "target_and_message"),
    
    # Public actions (Announcements) that do not require responses
    "publish_military_alliance": ActionDef("publish_military_alliance", "public", False, "target_only"),
    "declare_war": ActionDef("declare_war", "public", False, "target_only"),
    "trade_agreement": ActionDef("trade_agreement", "public", False, "target_only"),
    "sanction": ActionDef("sanction", "public", False, "target_only"),
    
    # System actions used to answer pending requests
    "accept_request": ActionDef("accept_request", "private", False, "target_only"),
    "reject_request": ActionDef("reject_request", "private", False, "target_only")
}
