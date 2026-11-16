"""
MACSWC Pygame UI.

Features:
- Balkans battle map with country regions and diplomacy links
- Country status panel with morale, stability, and army size
- Events panel with stacked live event cards
- Round counter in the top bar
"""

import math
import os
from typing import Any, Dict, List, Optional, Tuple

import pygame

WINDOW_WIDTH = 1600
WINDOW_HEIGHT = 900
TOPBAR_HEIGHT = 52
MAP_WIDTH = 1120
RIGHT_PANEL_X = MAP_WIDTH + 8
RIGHT_PANEL_WIDTH = WINDOW_WIDTH - MAP_WIDTH - 14
STATUS_PANEL_HEIGHT = 310
EVENTS_PANEL_Y = TOPBAR_HEIGHT + STATUS_PANEL_HEIGHT + 8
EVENTS_PANEL_HEIGHT = WINDOW_HEIGHT - EVENTS_PANEL_Y - 6
FPS = 30
NODE_RADIUS = 22

C_BG = (14, 16, 22)
C_TOPBAR_BG = (10, 12, 18)
C_TOPBAR_ACCENT = (140, 110, 50)
C_PANEL_BG = (20, 22, 32)
C_PANEL_BORDER = (55, 60, 80)
C_TEXT = (215, 218, 225)
C_TEXT_DIM = (110, 115, 130)
C_TEXT_BRIGHT = (245, 248, 255)
C_HEADER = (170, 150, 90)
C_GRID = (35, 40, 52)

C_MAP_WATER = (28, 45, 72)
C_MAP_BORDER = (90, 84, 60)

C_ALLIED = (60, 210, 110)
C_COOPERATIVE = (90, 150, 255)
C_NEUTRAL = (140, 140, 140)
C_HOSTILE = (255, 130, 70)
C_ADVERSARIAL = (255, 55, 55)

C_GOOD = (70, 200, 110)
C_WARN = (255, 175, 50)
C_CRIT = (255, 70, 70)

COUNTRY_COLORS: Dict[str, Tuple[int, int, int]] = {
    "Bulgaria": (34, 139, 34),
    "Serbia": (70, 130, 180),
    "Greece": (30, 90, 200),
    "Romania": (180, 50, 50),
    "Ottoman Empire": (80, 20, 20),
    "Montenegro": (100, 70, 160),
}
DEFAULT_NODE_COLOR = (80, 80, 100)

BALKANS_POLYGONS: Dict[str, List[Tuple[int, int]]] = {
    "Romania": [
        (510, 130), (680, 110), (820, 145), (875, 210), (845, 285),
        (760, 310), (660, 330), (540, 310), (460, 260), (470, 185),
    ],
    "Serbia": [
        (460, 320), (560, 305), (645, 330), (665, 405), (625, 460),
        (530, 480), (450, 450), (420, 390), (430, 340),
    ],
    "Montenegro": [
        (388, 440), (450, 428), (472, 468), (445, 508), (390, 508),
        (364, 478),
    ],
    "Bulgaria": [
        (655, 318), (798, 302), (888, 330), (908, 415), (865, 475),
        (762, 500), (648, 480), (600, 430), (612, 368),
    ],
    "Greece": [
        (492, 530), (582, 498), (685, 520), (715, 605), (685, 685),
        (615, 745), (542, 772), (492, 722), (462, 652), (472, 578),
    ],
    "Ottoman Empire": [
        (878, 308), (1005, 288), (1085, 348), (1092, 452), (1042, 528),
        (940, 558), (842, 540), (792, 478), (812, 388),
    ],
}

BALKANS_NODES: Dict[str, Tuple[int, int]] = {
    "Bulgaria": (760, 400),
    "Serbia": (540, 390),
    "Greece": (582, 628),
    "Romania": (668, 215),
    "Ottoman Empire": (958, 412),
    "Montenegro": (418, 468),
}

SEA_PATCHES: List[List[Tuple[int, int]]] = [
    [(640, 720), (780, 698), (900, 748), (922, 848), (822, 880), (682, 875), (602, 818), (602, 758)],
    [(835, 95), (1005, 72), (1105, 135), (1105, 215), (992, 245), (872, 215), (822, 152)],
    [(292, 338), (392, 328), (412, 408), (382, 488), (312, 508), (272, 448), (272, 388)],
]


def relation_color(weight: float) -> Tuple[int, int, int]:
    if weight >= 0.7:
        return C_ALLIED
    if weight >= 0.2:
        return C_COOPERATIVE
    if weight >= -0.2:
        return C_NEUTRAL
    if weight >= -0.7:
        return C_HOSTILE
    return C_ADVERSARIAL


def metric_color(value: float) -> Tuple[int, int, int]:
    if value >= 0.65:
        return C_GOOD
    if value >= 0.45:
        return C_WARN
    return C_CRIT


def _draw_panel(surface: pygame.Surface, rect: pygame.Rect, radius: int = 7) -> None:
    pygame.draw.rect(surface, C_PANEL_BG, rect, border_radius=radius)
    pygame.draw.rect(surface, C_PANEL_BORDER, rect, 1, border_radius=radius)


class TopBar:
    def __init__(self) -> None:
        self._round = 0
        self._complete = False
        self._scenario = "BALKAN WARS "

    def set_round(self, round_number: int, complete: bool = False) -> None:
        self._round = round_number
        self._complete = complete

    def set_scenario(self, scenario_file: str) -> None:
        self._scenario = os.path.basename(scenario_file).replace("_", " ").replace(".json", "")

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, C_TOPBAR_BG, pygame.Rect(0, 0, WINDOW_WIDTH, TOPBAR_HEIGHT))
        pygame.draw.line(surface, C_TOPBAR_ACCENT, (0, TOPBAR_HEIGHT - 2), (WINDOW_WIDTH, TOPBAR_HEIGHT - 2), 2)

        font_title = pygame.font.Font(None, 28)
        font_round = pygame.font.Font(None, 36)
        font_legend = pygame.font.Font(None, 16)

        scenario_text = font_title.render(f"THE WAR ROOM - MULTI AGENT SIMULATION WORLD ·  {self._scenario}", True, C_HEADER)
        surface.blit(scenario_text, (14, TOPBAR_HEIGHT // 2 - scenario_text.get_height() // 2))

        round_label = f"ROUND  {self._round}"
        round_color = C_GOOD if self._complete else C_TEXT_BRIGHT
        if self._complete:
            round_label += "  ·  COMPLETE"
        round_text = font_round.render(round_label, True, round_color)
        surface.blit(round_text, (WINDOW_WIDTH // 2 - round_text.get_width() // 2, TOPBAR_HEIGHT // 2 - round_text.get_height() // 2))

        legend = [("Allied", C_ALLIED), ("Cooperative", C_COOPERATIVE), ("Neutral", C_NEUTRAL), ("Hostile", C_HOSTILE)]
        x_cursor = WINDOW_WIDTH - 14
        for label, color in reversed(legend):
            legend_text = font_legend.render(label, True, color)
            x_cursor -= legend_text.get_width() + 4
            surface.blit(legend_text, (x_cursor, TOPBAR_HEIGHT // 2 - legend_text.get_height() // 2))
            x_cursor -= 16
            pygame.draw.circle(surface, color, (x_cursor + 6, TOPBAR_HEIGHT // 2), 5)
            x_cursor -= 10


class BalkansMapView:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._fallback_positions: Dict[str, Tuple[int, int]] = {}
        
        # Load map background image
        map_path = os.path.join(os.path.dirname(__file__), "assets", "map", "Map.webp")
        self.map_image = None
        if os.path.exists(map_path):
            try:
                loaded_image = pygame.image.load(map_path)
                # Scale to fit the map area
                self.map_image = pygame.transform.scale(loaded_image, (width, height - TOPBAR_HEIGHT))
            except Exception as e:
                print(f"Warning: Failed to load map image: {e}")
                self.map_image = None

    def _ensure_fallback_positions(self, countries: List[str]) -> None:
        count = len(countries)
        center_x = self.width // 2
        center_y = (self.height + TOPBAR_HEIGHT) // 2
        radius = min(self.width, self.height - TOPBAR_HEIGHT) // 2 - 100
        for index, country in enumerate(countries):
            if country not in BALKANS_NODES and country not in self._fallback_positions:
                angle = (2 * math.pi * index / max(count, 1)) - math.pi / 2
                self._fallback_positions[country] = (
                    int(center_x + radius * math.cos(angle)),
                    int(center_y + radius * math.sin(angle)),
                )

    def _get_position(self, country: str) -> Optional[Tuple[int, int]]:
        return BALKANS_NODES.get(country) or self._fallback_positions.get(country)

    def draw(self, surface: pygame.Surface, edges: List[Dict[str, Any]], countries: List[str]) -> None:
        self._ensure_fallback_positions(countries)
        map_rect = pygame.Rect(0, TOPBAR_HEIGHT, self.width, self.height - TOPBAR_HEIGHT)
        map_surface = surface.subsurface(map_rect)
        
        def shifted_y(world_y: int) -> int:
            return world_y - TOPBAR_HEIGHT

        # Draw map background image or fallback to solid color
        if self.map_image:
            map_surface.blit(self.map_image, (0, 0))
        else:
            map_surface.fill(C_MAP_WATER)
            # Fallback: draw grid and polygons if no image
            grid_color = (C_MAP_WATER[0] + 7, C_MAP_WATER[1] + 7, C_MAP_WATER[2] + 7)
            for grid_x in range(0, self.width, 60):
                pygame.draw.line(map_surface, grid_color, (grid_x, 0), (grid_x, map_surface.get_height()))
            for grid_y in range(0, map_surface.get_height(), 60):
                pygame.draw.line(map_surface, grid_color, (0, grid_y), (self.width, grid_y))

            for patch in SEA_PATCHES:
                points = [(x, shifted_y(y)) for x, y in patch]
                if len(points) >= 3:
                    pygame.draw.polygon(map_surface, (32, 55, 88), points)
                    pygame.draw.polygon(map_surface, (40, 65, 100), points, 1)

            active_countries = set(countries)
            for country, polygon in BALKANS_POLYGONS.items():
                points = [(x, shifted_y(y)) for x, y in polygon]
                if len(points) < 3:
                    continue
                fill = COUNTRY_COLORS.get(country, (55, 62, 40))
                if active_countries and country not in active_countries:
                    fill = tuple(max(0, component - 28) for component in fill)
                pygame.draw.polygon(map_surface, fill, points)
                pygame.draw.polygon(map_surface, C_MAP_BORDER, points, 2)

            label_font = pygame.font.Font(None, 17)
            for country, polygon in BALKANS_POLYGONS.items():
                if country not in active_countries:
                    continue
                centroid_x = sum(point[0] for point in polygon) // len(polygon)
                centroid_y = shifted_y(sum(point[1] for point in polygon) // len(polygon))
                shadow = label_font.render(country, True, (0, 0, 0))
                label = label_font.render(country, True, (230, 225, 200))
                label_rect = label.get_rect(center=(centroid_x, centroid_y))
                map_surface.blit(shadow, (label_rect.x + 1, label_rect.y + 1))
                map_surface.blit(label, label_rect)

        for edge in edges:
            source = edge.get("a")
            target = edge.get("b")
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            source_pos = self._get_position(source)
            target_pos = self._get_position(target)
            if source_pos is None or target_pos is None:
                continue
            weight = float(edge.get("weight", 0.0))
            color = relation_color(weight)
            thickness = max(1, int(abs(weight) * 4))
            pygame.draw.line(
                map_surface,
                color,
                (source_pos[0], shifted_y(source_pos[1])),
                (target_pos[0], shifted_y(target_pos[1])),
                thickness,
            )

        node_font = pygame.font.Font(None, 19)
        for country in countries:
            position = self._get_position(country)
            if position is None:
                continue
            node_x, node_y = position[0], shifted_y(position[1])
            fill = COUNTRY_COLORS.get(country, DEFAULT_NODE_COLOR)
            pygame.draw.circle(map_surface, fill, (node_x, node_y), NODE_RADIUS)
            pygame.draw.circle(map_surface, (220, 215, 180), (node_x, node_y), NODE_RADIUS, 2)
            abbreviation = node_font.render(country[:3].upper(), True, C_TEXT_BRIGHT)
            map_surface.blit(abbreviation, abbreviation.get_rect(center=(node_x, node_y)))

        self._draw_compass(map_surface, self.width - 58, map_surface.get_height() - 58)

    def _draw_compass(self, surface: pygame.Surface, center_x: int, center_y: int) -> None:
        radius = 22
        pygame.draw.circle(surface, (38, 42, 54), (center_x, center_y), radius)
        pygame.draw.circle(surface, C_MAP_BORDER, (center_x, center_y), radius, 1)
        font = pygame.font.Font(None, 16)
        for label, dx, dy in [("N", 0, -radius + 5), ("S", 0, radius - 9), ("E", radius - 7, 0), ("W", -radius + 3, 0)]:
            text = font.render(label, True, C_HEADER)
            surface.blit(text, (center_x + dx - text.get_width() // 2, center_y + dy - text.get_height() // 2))
        pygame.draw.polygon(surface, C_HEADER, [(center_x, center_y - radius // 2), (center_x - 5, center_y), (center_x + 5, center_y)])


class CountryStatusView:
    ROW_HEIGHT = 44

    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def draw(self, surface: pygame.Surface, countries_data: List[Dict[str, Any]]) -> None:
        _draw_panel(surface, pygame.Rect(self.x, self.y, self.width, self.height))

        header_font = pygame.font.Font(None, 20)
        text_font = pygame.font.Font(None, 17)
        surface.blit(header_font.render("COUNTRY STATUS", True, C_HEADER), (self.x + 8, self.y + 6))
        pygame.draw.line(surface, C_PANEL_BORDER, (self.x + 6, self.y + 24), (self.x + self.width - 6, self.y + 24), 1)

        if not countries_data:
            surface.blit(text_font.render("Awaiting data...", True, C_TEXT_DIM), (self.x + 8, self.y + 32))
            return

        current_y = self.y + 28
        bar_space = self.width - 108
        for country in countries_data:
            if current_y + self.ROW_HEIGHT > self.y + self.height:
                break

            name = country.get("name", "?")
            morale = min(1.0, max(0.0, float(country.get("morale", 0.5))))
            stability = min(1.0, max(0.0, float(country.get("stability_index", 0.5))))
            army_size = int(country.get("army_size", 0))
            node_color = COUNTRY_COLORS.get(name, DEFAULT_NODE_COLOR)

            pygame.draw.circle(surface, node_color, (self.x + 13, current_y + 10), 7)
            surface.blit(text_font.render(name[:15], True, C_TEXT), (self.x + 25, current_y + 3))

            army_text = text_font.render(f"{army_size // 1000}k", True, C_TEXT_DIM)
            surface.blit(army_text, (self.x + self.width - army_text.get_width() - 6, current_y + 3))

            bar_x = self.x + 8
            bar_y = current_y + 22
            morale_width = (bar_space * 3) // 5
            bar_height = 8
            pygame.draw.rect(surface, C_GRID, (bar_x, bar_y, morale_width, bar_height))
            pygame.draw.rect(surface, metric_color(morale), (bar_x, bar_y, int(morale_width * morale), bar_height))
            surface.blit(text_font.render("M", True, C_TEXT_DIM), (bar_x + morale_width + 2, bar_y - 1))

            stability_x = bar_x + morale_width + 18
            stability_width = bar_space - morale_width - 22
            pygame.draw.rect(surface, C_GRID, (stability_x, bar_y, stability_width, bar_height))
            pygame.draw.rect(surface, metric_color(stability), (stability_x, bar_y, int(stability_width * stability), bar_height))
            surface.blit(text_font.render("S", True, C_TEXT_DIM), (stability_x + stability_width + 2, bar_y - 1))

            current_y += self.ROW_HEIGHT
            pygame.draw.line(surface, C_GRID, (self.x + 4, current_y - 2), (self.x + self.width - 4, current_y - 2), 1)


class EventsView:
    CARD_HEIGHT = 80
    CARD_GAP = 5
    MAX_EVENTS = 10

    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self._events: List[Dict[str, Any]] = []

    def add_event(self, action: Dict[str, Any]) -> None:
        self._events.insert(0, action)
        if len(self._events) > self.MAX_EVENTS:
            self._events.pop()

    def draw(self, surface: pygame.Surface, current_round: int) -> None:
        _draw_panel(surface, pygame.Rect(self.x, self.y, self.width, self.height))

        header_font = pygame.font.Font(None, 20)
        body_font = pygame.font.Font(None, 17)
        meta_font = pygame.font.Font(None, 15)
        surface.blit(header_font.render(f"EVENTS  ·  R{current_round}", True, C_HEADER), (self.x + 8, self.y + 6))
        pygame.draw.line(surface, C_PANEL_BORDER, (self.x + 6, self.y + 24), (self.x + self.width - 6, self.y + 24), 1)

        if not self._events:
            surface.blit(body_font.render("No events yet...", True, C_TEXT_DIM), (self.x + 8, self.y + 32))
            return

        card_y = self.y + 28
        for index, event in enumerate(self._events):
            if card_y + self.CARD_HEIGHT > self.y + self.height:
                break

            actor = event.get("actor", "?")
            target = event.get("target", "?")
            action_type = event.get("type", "?").replace("_", " ").title()
            thought = event.get("thought_summary", "")
            secretary_status = event.get("secretary_status", "")
            public_message = event.get("public_message", "")
            rationale_code = event.get("rationale_code", "")
            event_round = event.get("_round", current_round)
            is_llm = "llm" in rationale_code.lower()

            background = (38, 44, 60) if index == 0 else (24, 27, 42)
            card_rect = pygame.Rect(self.x + 4, card_y, self.width - 8, self.CARD_HEIGHT)
            pygame.draw.rect(surface, background, card_rect, border_radius=5)
            pygame.draw.rect(surface, C_PANEL_BORDER, card_rect, 1, border_radius=5)

            accent = COUNTRY_COLORS.get(actor, DEFAULT_NODE_COLOR)
            pygame.draw.rect(surface, accent, pygame.Rect(self.x + 4, card_y, 4, self.CARD_HEIGHT), border_radius=3)

            text_x = self.x + 12
            headline = body_font.render(f"{actor}  →  {target}   [{action_type}]", True, C_TEXT_BRIGHT)
            surface.blit(headline, (text_x, card_y + 5))

            tag = meta_font.render(f"R{event_round}  {'◆LLM' if is_llm else '◇fb'}", True, C_TEXT_DIM)
            surface.blit(tag, (self.x + self.width - tag.get_width() - 8, card_y + 6))

            if thought:
                short_thought = thought if len(thought) <= 66 else thought[:63] + "..."
                surface.blit(meta_font.render(short_thought, True, C_TEXT_DIM), (text_x, card_y + 24))

            if secretary_status:
                surface.blit(meta_font.render(f"Secretary: {secretary_status}", True, (150, 200, 150)), (text_x, card_y + 42))

            if public_message:
                short_message = public_message if len(public_message) <= 62 else public_message[:59] + "..."
                surface.blit(meta_font.render(f'"{short_message}"', True, (180, 165, 120)), (text_x, card_y + 60))

            card_y += self.CARD_HEIGHT + self.CARD_GAP


class SimulationWindow:
    def __init__(self, scenario_file: str = ""):
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption("MACSWC — Geopolitical Simulation")
        self.clock = pygame.time.Clock()
        self.running = True

        self.current_result: Optional[Dict[str, Any]] = None
        self.world_state: Optional[Any] = None
        self.iron_ledger: Optional[Any] = None
        self.current_round = 0
        self.simulation_complete = False

        self.topbar = TopBar()
        self.map_view = BalkansMapView(MAP_WIDTH, WINDOW_HEIGHT)
        self.status_view = CountryStatusView(RIGHT_PANEL_X, TOPBAR_HEIGHT, RIGHT_PANEL_WIDTH, STATUS_PANEL_HEIGHT)
        self.events_view = EventsView(RIGHT_PANEL_X, EVENTS_PANEL_Y, RIGHT_PANEL_WIDTH, EVENTS_PANEL_HEIGHT)

        if scenario_file:
            self.topbar.set_scenario(scenario_file)

    def set_world_state(self, world_state: Any) -> None:
        self.world_state = world_state

    def set_iron_ledger(self, iron_ledger: Any) -> None:
        self.iron_ledger = iron_ledger

    def set_simulation_complete(self, complete: bool) -> None:
        self.simulation_complete = complete

    def set_result(self, result: Dict[str, Any]) -> None:
        self.current_result = result
        self.current_round = 0

    def add_live_action(self, action: Dict[str, Any]) -> None:
        action["_round"] = self.current_round
        self.events_view.add_event(action)

    def draw(self) -> None:
        self.screen.fill(C_BG)

        state_after: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        countries: List[str] = []

        if self.current_result:
            rounds = self.current_result.get("rounds", [])
            if rounds:
                latest_round = rounds[-1]
                self.current_round = latest_round.get("round", self.current_round)
                state_after = latest_round.get("state_after_round", [])
            else:
                state_after = self.current_result.get("initial_state", [])
            edges = self.current_result.get("final_diplomacy_edges", [])
            countries = []
            for country in state_after:
                if not country:
                    continue
                name = country.get("name")
                if isinstance(name, str):
                    countries.append(name)

        self.topbar.set_round(self.current_round, self.simulation_complete)
        self.topbar.draw(self.screen)
        self.map_view.draw(self.screen, edges, countries)

        pygame.draw.line(self.screen, C_PANEL_BORDER, (MAP_WIDTH, TOPBAR_HEIGHT), (MAP_WIDTH, WINDOW_HEIGHT), 1)

        if not self.current_result:
            waiting_font = pygame.font.Font(None, 28)
            waiting_text = waiting_font.render("Waiting for simulation data...", True, C_TEXT_DIM)
            self.screen.blit(waiting_text, (MAP_WIDTH // 2 - waiting_text.get_width() // 2, WINDOW_HEIGHT // 2))

        self.status_view.draw(self.screen, state_after)
        self.events_view.draw(self.screen, self.current_round)

        pygame.display.flip()

    def handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return False
        return True

    def process_events_only(self) -> bool:
        """
        Process pygame events without rendering. 
        Keeps window responsive during long operations like LLM API calls.
        Returns False if user requested quit.
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.running = False
                return False
        return True

    def update(self) -> bool:
        self.running = self.handle_events()
        self.draw()
        self.clock.tick(FPS)
        return self.running

    def is_running(self) -> bool:
        return self.running

    def close(self) -> None:
        pygame.quit()


_window_instance: Optional[SimulationWindow] = None


def init_gui(scenario_file: str = "") -> Optional[SimulationWindow]:
    global _window_instance
    if not _window_instance:
        _window_instance = SimulationWindow(scenario_file=scenario_file)
    return _window_instance


def get_gui() -> Optional[SimulationWindow]:
    return _window_instance


def close_gui() -> None:
    global _window_instance
    if _window_instance:
        _window_instance.close()
        _window_instance = None


if __name__ == "__main__":
    gui = init_gui()
    try:
        while gui and gui.is_running():
            gui.update()
    finally:
        close_gui()
