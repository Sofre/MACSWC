import json
import uuid
from typing import Dict, Any, List, Optional
from WorldEngine.world_state import WorldState
from WorldEngine.action_registry import ACTION_REGISTRY

class SimulationEngine:
    """
    Manages the environment, discrete time steps, and rules for interactions between agents,
    including diplomatic negotiations, economic actions, military escalation, and strategic deterrence.
    """
    def __init__(self, world_state: Optional[WorldState] = None, rules_parameters: Optional[Dict[str, Any]] = None):
        """
        Initializes the simulation engine with world state and rule parameters.

        If no world state is provided, a default empty WorldState is created.
        """
        self.world_state = world_state if world_state is not None else WorldState()
        self.rules_parameters = rules_parameters if rules_parameters is not None else {}
        self.logs: List[Dict[str, Any]] = []
        self.pending_requests: Dict[str, Dict[str, Any]] = {}

    def apply_actions(self, actions: List[Dict[str, Any]]):
        """
        Processes a list of actions, determining publicity (routing to inboxes vs global logs)
        and checking if actions are instant or require a response.
        """
        for action in actions:
            action_type = action.get("type")
            actor = action.get("actor")
            target = action.get("target")

            if not action_type or not actor or not target:
                continue

            action_def = ACTION_REGISTRY.get(action_type)
            if not action_def:
                print(f"Warning: Unknown action type {action_type}")
                continue

            # Ensure nodes exist in the graph (in case agents aren't fully populated)
            if not self.world_state.diplomacy_graph.has_node(actor):
                self.world_state.diplomacy_graph.add_node(actor)
            if not self.world_state.diplomacy_graph.has_node(target):
                self.world_state.diplomacy_graph.add_node(target)
            
            event = {"round": len(self.logs), "action": action}

            # Handle Pending Requests
            if action_def.require_response:
                request_id = str(uuid.uuid4())
                event["request_id"] = request_id
                self.pending_requests[request_id] = action

            # Publicity Routing
            if action_def.publicity == "public":
                self.world_state.global_logs.append(event)
                self.logs.append(event) # legacy tracking
            elif action_def.publicity == "private":
                if target in self.world_state.country_inboxes:
                    self.world_state.country_inboxes[target].append(event)
                else:
                    self.world_state.country_inboxes[target] = [event]
            
            # Apply NetworkX graph transformations
            # Only apply for instant actions or when accepting a pending request
            if not action_def.require_response:
                if action_type == "accept_request":
                    req_id = action.get("request_id")
                    if req_id and req_id in self.pending_requests:
                        orig_action = self.pending_requests[req_id]
                        if orig_action.get("type") == "request_military_alliance":
                            self.world_state.diplomacy_graph.add_edge(orig_action["actor"], orig_action["target"], weight=1.0)
                        elif orig_action.get("type") == "present_peace_agreement":
                            self.world_state.diplomacy_graph.add_edge(orig_action["actor"], orig_action["target"], weight=0.0)
                        del self.pending_requests[req_id]
                
                elif action_type == "reject_request":
                    req_id = action.get("request_id")
                    if req_id and req_id in self.pending_requests:
                        del self.pending_requests[req_id]

                else:
                    edge_data = self.world_state.diplomacy_graph.get_edge_data(actor, target, default={"weight": 0.0})
                    current_weight = edge_data.get("weight", 0.0) if edge_data is not None else 0.0

                    if action_type == "publish_military_alliance":
                        self.world_state.diplomacy_graph.add_edge(actor, target, weight=1.0)
                    elif action_type == "declare_war":
                        self.world_state.diplomacy_graph.add_edge(actor, target, weight=-1.0)
                    elif action_type == "trade_agreement":
                        new_weight = min(1.0, current_weight + 0.3)
                        self.world_state.diplomacy_graph.add_edge(actor, target, weight=new_weight)
                    elif action_type == "sanction":
                        new_weight = max(-1.0, current_weight - 0.4)
                        self.world_state.diplomacy_graph.add_edge(actor, target, weight=new_weight)

    def update_state(self, updates: Dict[str, Any]):
        """
        Applies explicit updates to the world state based on evaluated interactions.

        This is a placeholder for future state mutation logic that goes beyond
        diplomacy edge updates handled in apply_actions.
        """
        pass # Will implement explicit attribute tracking for players

    def advance_rounds(self, save_path="world_state.json"):
        """
        Concludes the current discrete time step and advances to the next round.

        The method refreshes analytics structures, writes the global world state,
        and creates one personalized context file per country.
        """
        # Sync the dataframe at the end of the round for analytics
        self.world_state.update_dataframe()
        
        # Save a generic world_state.json and then loop through inboxes to create personalized contexts
        self.world_state.save_to_file(save_path)
        
        for cp in self.world_state.country_profiles:
            personalized_path = f"context_{cp.name.replace(' ', '_')}.json"
            self.world_state.save_to_file(personalized_path, viewer_country=cp.name)

    def provide_context(self) -> Dict[str, Any]:
        """
        Returns a compact snapshot of the current simulation context.

        This helper is designed for consumers that only need high-level context,
        not the full serialized world state.
        """
        return {
            "world_state": {
                "global_context": self.world_state.global_context,
                "countries": [cp.name for cp in self.world_state.country_profiles]
            },
            "rules_parameters": self.rules_parameters,
            "logs_length": len(self.logs)
        }
    
    #Provide round logs 
