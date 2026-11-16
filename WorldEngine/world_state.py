import pandas as pd
import networkx as nx
from typing import List, Dict, Any, Optional


class CountryProfile:
    """Represents a specific country's state."""

    def __init__(
        self,
        name: str,
        population: int,
        army_size: int,
        morale: float,
        national_unity: float,
        equipment_quality: float,
    ):
        super().__init__()
        self.name = name
        self.population = population
        self.army_size = army_size
        self.morale = max(0.0, min(1.0, morale))
        self.national_unity = max(0.0, min(1.0, national_unity))
        self.equipment_quality = max(0.0, min(1.0, equipment_quality))

    @property
    def combat_power(self) -> float:
        return self.army_size * (self.equipment_quality + self.morale)

    @property
    def stability_index(self) -> float:
        return self.national_unity * self.morale

# World State .. Engine updates this on each round 
class WorldState:
    """
    A unified class defining the current state from Country Profiles and Global Context.
    It synchronously maintains a Pandas DataFrame and a NetworkX graph for rapid analytics.
    """
    def __init__(self, country_profiles: Optional[List[CountryProfile]] = None, global_context: Optional[Dict[str, Any]] = None):
        """
        Initializes the world state container and its synchronized data structures.

        Creates country inboxes, initializes diplomacy graph nodes, and builds
        the initial analytics dataframe from the provided country profiles.
        """
        self.country_profiles = country_profiles if country_profiles is not None else []
        self.global_context = global_context if global_context is not None else {}
        
        # Communication tracking
        self.global_logs: List[Dict[str, Any]] = []
        self.country_inboxes: Dict[str, List[Dict[str, Any]]] = {
            cp.name: [] for cp in self.country_profiles
        }
        
        # Data Science Structures
        self.diplomacy_graph = nx.Graph()
        self.df = pd.DataFrame()
        
        # Initialize nodes in the graph for each country
        for cp in self.country_profiles:
            self.diplomacy_graph.add_node(cp.name)
            
        self.update_dataframe()

    def update_dataframe(self):
        """
        Syncs our country objects directly into a fast Pandas DataFrame.
        Run this before performing global mathematical transformations.
        """
        if not self.country_profiles:
            self.df = pd.DataFrame()
        else:
            country_dicts = [
                {
                    "name": c.name, 
                    "population": c.population,
                    "army_size": c.army_size, 
                    "morale": c.morale,
                    "national_unity": c.national_unity,
                    "equipment_quality": c.equipment_quality,
                    "combat_power": c.combat_power,
                    "stability_index": c.stability_index
                } for c in self.country_profiles
            ]
            self.df = pd.DataFrame(country_dicts)

    def to_dict(self, viewer_country: Optional[str] = None) -> dict:
        """
        Serializes the current WorldState into a dictionary suitable for JSON.
        If viewer_country is provided, returns personalized private_inbox data alongside public data.
        """
        base_dict = {
            "global_context": self.global_context,
            "global_logs": self.global_logs,
            "countries": self.df.to_dict(orient="records") if hasattr(self, 'df') and not self.df.empty else [],
            "diplomacy": nx.node_link_data(self.diplomacy_graph)
        }
        if viewer_country and viewer_country in self.country_inboxes:
            base_dict["private_inbox"] = self.country_inboxes[viewer_country]

        return base_dict

    def save_to_file(self, filename: str = "world_state.json", viewer_country: Optional[str] = None):
        """
        Saves the serialized WorldState to a JSON file.

        When viewer_country is provided, the output includes that country's
        private inbox along with public state.
        """
        import json
        with open(filename, 'w') as f:
            json.dump(self.to_dict(viewer_country), f, indent=4)
