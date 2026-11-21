import argparse
import warnings
import hashlib
from requests.exceptions import RequestException
import json
from collections import Counter, defaultdict
import gzip
import math
from pathlib import Path
import textwrap
import time as wall_time
import xml.etree.ElementTree as ET
import matplotlib.animation as animation
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.lines import Line2D
from matplotlib.widgets import Slider, Button
import numpy as np
import contextily as ctx
from pyproj import Transformer
from traffic_signals import FixedTimeSignals


from microscopic_traffic import (
    GAP, SPEED_COLORS, MicroscopicPlayback, position,
    DAY_SECONDS, DAY_PLAYBACK_SPEED, day_time, daily_operations, DayFrameCache,
    PlaybackClock, PeriodicFrameCache, vehicle_hitbox, FocalContinuousCache,
    read_operations, replay_frames, speed_color, sample_color, agent_profile, desired_speed,
)
from traffic_routing import balanced_routes, routing_summary


_UTM_TO_MERCATOR = Transformer.from_crs("EPSG:32615", "EPSG:3857", always_xy=True)


def map_to_web_mercator(points):
    """Project UTM 15N metres directly; never fit or deform a bounding box."""
    xy=np.asarray(points,dtype=float)
    if xy.ndim==0 or xy.shape[-1]!=2 or not np.isfinite(xy).all():
        raise ValueError("Coordinates must be finite UTM XY pairs")
    if xy.size==0: return xy.copy()
    flat=xy.reshape(-1,2)
    x,y=_UTM_TO_MERCATOR.transform(flat[:,0].tolist(),flat[:,1].tolist(),errcheck=True)
    return np.stack((x,y),axis=-1).reshape(xy.shape)


def configure_zona1_projection(ax,nodes,registration=None):
    if registration != 'EPSG:32615':
        raise ValueError('Lab08 requires an EPSG:32615 export; regenerate with Lab08Zona1Network')
    map_to_web_mercator(list(nodes.values()))
    ax._map_crs='EPSG:3857'


def map_coordinates(ax,points):
    return map_to_web_mercator(points) if getattr(ax,'_map_crs',None)=='EPSG:3857' else np.asarray(points,dtype=float)


def load_map_registration(network_path):
    opener=gzip.open if str(network_path).endswith('.gz') else open
    with opener(network_path,'rb') as stream:
        attrs={a.get('name'):a.text for a in ET.parse(stream).getroot().findall('attributes/attribute')}
    return attrs.get('visualProjection')


DARK_TILE_URL = "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# Verified RGB fingerprint of CartoCDN's HTTP-200 "API KEY REQUIRED" tile.
CARTO_KEY_TILE_SHA256 = "d36df23c63879d10e90e52f7ccd86148998030867958151e8e8d026a7338b47b"


def _is_key_placeholder(image):
    pixels = np.asarray(image)
    for y in range(0,pixels.shape[0]-255,256):
        for x in range(0,pixels.shape[1]-255,256):
            tile = np.ascontiguousarray(pixels[y:y+256,x:x+256,:3],dtype=np.uint8)
            if hashlib.sha256(tile.tobytes()).hexdigest() == CARTO_KEY_TILE_SHA256:
                return True
    return False


def add_zona1_basemap(ax, source=None):
    """Load once; also reject the verified HTTP-200 key placeholder, not just errors."""
    if getattr(ax, '_map_crs', None) != "EPSG:3857":
        raise ValueError("Configure the Zona 1 projection before adding a basemap")
    ax.autoscale_view()
    limits = ax.get_xlim(), ax.get_ylim()
    sources = [source] if source is not None else [DARK_TILE_URL, OSM_TILE_URL]
    ax._basemap_source = None
    for candidate in sources:
        old_artists = set(ax.get_children())
        try:
            kwargs = dict(zoom=16, crs="EPSG:3857", reset_extent=True,zorder=0,timeout=5)
            if candidate in (DARK_TILE_URL, OSM_TILE_URL):
                kwargs['headers'] = {'User-Agent':'MATSim-Guatemala-Lab08/1.0 (desktop traffic visualization)'}
                cache_dir = Path(__file__).resolve().parents[1]/'target'/'map-tile-cache'
                cache_dir.mkdir(parents=True,exist_ok=True)
                ctx.set_cache_dir(str(cache_dir))
                kwargs['attribution'] = '(C) OpenStreetMap contributors' + (' (C) CARTO' if candidate==DARK_TILE_URL else '')
            ctx.add_basemap(ax,source=candidate,**kwargs)
            new_images = [im for im in ax.images if im not in old_artists]
            if candidate==DARK_TILE_URL and any(_is_key_placeholder(im.get_array()) for im in new_images):
                raise ValueError("CartoCDN returned the API key placeholder")
            ax._basemap_source = candidate
            return
        except (RequestException,OSError,ValueError) as exc:
            for artist in set(ax.get_children())-old_artists:
                artist.remove()
            warnings.warn(f"Fondo no disponible ({type(exc).__name__}); intentando respaldo o fondo local")
        finally:
            ax.set_xlim(limits[0]); ax.set_ylim(limits[1])


def load_network(network_path):
    nodes = {}
    links = {}
    open_fn = gzip.open if str(network_path).endswith(".gz") else open

    with open_fn(network_path, "rb") as f:
        for event, elem in ET.iterparse(f):
            if elem.tag == "node":
                nodes[elem.attrib["id"]] = (
                    float(elem.attrib["x"]),
                    float(elem.attrib["y"]),
                )
            elif elem.tag == "link":
                attributes = {a.get("name"): a.text for a in elem.findall("attributes/attribute")}
                link_id = elem.attrib["id"]
                from_node = elem.attrib["from"]
                to_node = elem.attrib["to"]
                links[link_id] = {
                    "from": nodes[from_node],
                    "to": nodes[to_node],
                    "length": float(elem.attrib.get("length", 400.0)),
                    "capacity": float(elem.attrib.get("capacity", 1800.0)),
                    "freespeed": float(elem.attrib.get("freespeed", 13.89)),
                    "lanes": max(1, int(float(elem.attrib.get("permlanes", 1)))),
                    "from_id": from_node,
                    "to_id": to_node,
                    "attributes": attributes,
                    "lateral_offset": float(attributes.get("lateralOffset", 0)),
                    "right_of_way": attributes.get('rightOfWay') == 'true',
                    "stop_before_avenue": attributes.get('stopBeforeAvenue') == 'true',
                    "stop_seconds": float(attributes.get('mandatoryStopSeconds', 1)),
                    "stop_setback": float(attributes.get('stopLineSetback', 3.25)),
                    "night_freespeed": float(attributes.get("nightFreeSpeed", 0)),
                    "extreme_night": attributes.get("extremeNight") == "true",
                    "lane_changing": attributes.get("laneChanging") == "true",
                    "max_active": int(attributes.get("maxActiveVehicles", 2147483647)),
                    "routing_eligible": attributes.get("routingEligible", "true") != "false",
                    "internal": not (from_node.startswith("B_") and to_node.startswith("B_")),
                    "is_bypass": (from_node.startswith("B_") and to_node.startswith("B_")
                                  and float(elem.attrib.get("freespeed", 13.89)) >= 20),
                }
                if "laneWidth" in attributes:
                    links[link_id]["lane_width"] = float(attributes["laneWidth"])
                if attributes.get('signalized') == 'true':
                    plan = FixedTimeSignals(float(attributes['avenueGreen']),float(attributes['streetGreen']),
                                            float(attributes['signalYellow']),float(attributes['signalAllRed']),
                                            float(attributes.get('signalOffset',0)))
                    plan.validate_cycle(float(attributes['signalCycle']))
                    group = attributes['signalGroup']
                    if group not in ('avenue','street'):
                        raise ValueError('Invalid signal group')
                    links[link_id]['signal_plan'] = plan
                    links[link_id]['signal_group'] = group
                elem.clear()
    for link_id, link in links.items():
        if any(not math.isfinite(link[key]) or link[key] <= 0
               for key in ("length", "capacity", "freespeed")):
            raise ValueError(f"Atributos viales inválidos: {link_id}")
    return nodes, links


def load_special_areas(network_path):
    """Read optional Lab06 polygons; earlier network files remain compatible."""
    open_fn = gzip.open if str(network_path).endswith(".gz") else open
    with open_fn(network_path, "rb") as stream:
        root = ET.parse(stream).getroot()
    areas = []
    for attribute in root.findall("attributes/attribute"):
        if not attribute.get("name", "").startswith("visualArea."):
            continue
        kind, label, coordinates = attribute.text.split("|", 2)
        points = [tuple(map(float, pair.split(","))) for pair in coordinates.split(";")]
        if len(points) < 3 or any(len(p) != 2 or not all(map(math.isfinite, p)) for p in points):
            raise ValueError("Polígono especial inválido")
        areas.append(dict(kind=kind, label=label, points=points))
    return areas


def draw_special_areas(ax, areas):
    for area in areas:
        color = "#80c991" if area["kind"] == "green" else "#e8cf70"
        ax.add_patch(Polygon(map_coordinates(ax, area["points"]), closed=True, facecolor=color,
                             edgecolor=color, alpha=.4, zorder=1))
        center = map_coordinates(ax, np.mean(area["points"], axis=0))
        label_width = 14 if np.ptp(np.asarray(area["points"])[:, 0]) < 150 else 22
        ax.text(*center, textwrap.fill(area["label"], label_width), color=color, fontsize=7,
                ha="center", va="center", zorder=1)


def load_points_of_interest(network_path):
    opener = gzip.open if str(network_path).endswith(".gz") else open
    with opener(network_path, "rb") as stream:
        root = ET.parse(stream).getroot()
    points = []
    for attribute in root.findall("attributes/attribute"):
        if attribute.get("name", "").startswith("visualPoi."):
            kind, label, coordinates = attribute.text.split("|", 2)
            x, y = map(float, coordinates.split(","))
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("Punto de interés inválido")
            points.append(dict(kind=kind, label=label, xy=(x, y)))
    return points


def draw_points_of_interest(ax, points):
    for point in points:
        color = "#eeaaaa" if point["kind"] == "hospital" else "#e8cf70"
        ax.scatter(*map_coordinates(ax, point["xy"]), marker="P" if point["kind"] == "hospital" else "s",
                   color=color, s=45, zorder=2)
        ax.annotate(point["label"], map_coordinates(ax, point["xy"]), xytext=(6, 6),
                    textcoords="offset points", fontsize=7, color=color, zorder=2)


def signal_colors(roads, time):
    palette = {'green':'#00D66B','yellow':'#FFC107','red':'#FF4545'}
    return [palette[r['signal_plan'].states(time)[0 if r['signal_group']=='avenue' else 1]] for r in roads]


class SignalDisplay:
    """Four batched collections, independent of the number of intersections."""
    def __init__(self, ax, roads):
        from matplotlib.transforms import offset_copy
        from matplotlib.path import Path as MarkerPath
        self.roads = roads
        xy = np.asarray([position(r, max(0,r['length']-r.get('stop_setback',3.25)-12),
                                  r['lanes']-.5+24/r.get('lane_width',3.2))
                         for r in roads]).reshape(-1,2)
        xy = map_coordinates(ax, xy)
        box = MarkerPath([(-.35,-.85),(.35,-.85),(.35,.85),(-.35,.85),(-.35,-.85)])
        self.housing = ax.scatter(xy[:,0],xy[:,1],s=150,marker=box,
                                 c='#111111',edgecolors='#888888',linewidths=.4,zorder=3)
        self.lamps = []
        for offset in (3.5,0,-3.5):
            lamp = ax.scatter(xy[:,0],xy[:,1],s=8,marker='o',c='#333333',zorder=3)
            lamp.set_offset_transform(offset_copy(ax.transData,fig=ax.figure,y=offset,units='points'))
            self.lamps.append(lamp)
        self.artists = [self.housing,*self.lamps]
        self.update(0)

    def update(self, time):
        active = signal_colors(self.roads,time)
        for lamp, color in zip(self.lamps,('#FF4545','#FFC107','#00D66B')):
            lamp.set_facecolors([color if c==color else '#333333' for c in active])


def draw_road(ax, road):
    if "lane_width" not in road:
        p, q = map_coordinates(ax, [road["from"], road["to"]])
        ax.plot([p[0], q[0]], [p[1], q[1]], color="lightgray", linewidth=5, alpha=0.5, zorder=2)
        return
    n = road["lanes"]
    p, q = map_coordinates(ax, [road["from"], road["to"]])
    ax.plot([p[0],q[0]],[p[1],q[1]],color="lightgray",alpha=0.5,lw=5+2*n,
            solid_capstyle="butt",zorder=2)
    vertices = [position(road, d, lane) for d, lane in
                ((0, -.5), (road["length"], -.5), (road["length"], n-.5), (0, n-.5))]
    ax.add_patch(Polygon(map_coordinates(ax, vertices), facecolor="lightgray", edgecolor="lightgray", alpha=0.5, lw=.3, zorder=2))
    for lane in range(n - 1):
        p, q = map_coordinates(ax, [position(road, 0, lane+.5), position(road, road["length"], lane+.5)])
        ax.plot([p[0], q[0]], [p[1], q[1]], color="lightgray", lw=.3, ls="-", alpha=0.5, zorder=2)


def load_multi_agent_trajectories(events_path, links, mode="replay", dt=None):
    """Compatibility API returning positions and actual displayed parking intervals.

    Animation itself streams frames instead of retaining every agent/time sample.
    """
    if mode not in ("replay", "microscopic"):
        raise ValueError("Modo de reproducción desconocido")
    dt = dt if dt is not None else (.2 if mode == "microscopic" else 1.0)
    routes = read_operations(events_path, links)
    engine = MicroscopicPlayback(routes, links, dt=dt) if mode == "microscopic" else None
    frames = engine.frames() if engine else replay_frames(routes, links, dt)
    trajectories = defaultdict(dict)
    for time, frame in frames:
        for agent, sample in frame.items():
            trajectories[agent][time] = position(links[sample.link], sample.distance, sample.lane)
    activities = defaultdict(list)
    if engine:
        for agent, start, end, source, link, distance in engine.parking_log:
            activities[agent].append(dict(t_start=start, t_end=end, link=link, source=source))
    else:
        for agent, ops in routes.items():
            activities[agent] = [dict(t_start=op.start, t_end=op.end, link=op.link, source=op.source)
                                 for op in ops if op.kind == "parking"]
    return dict(trajectories), dict(activities)


def render_agents(points, frame, links, frame_index=0):
    """Refresh positions and instantaneous speed colors together, every frame."""
    samples = list(frame.values())
    points.set_offsets(map_coordinates(points.axes, np.array([position(links[s.link], s.distance, s.lane)
                                 for s in samples]).reshape(-1, 2)))
    points.set_color([sample_color(s, frame_index) for s in samples])
    if getattr(points, "_focal", False):
        points.set_sizes([100])
    elif any("lane_width" in road for road in links.values()):
        # A fixed marker size can cover several 3.2 m lanes at city scale.
        # Keep vehicle width in map metres, including when zooming/resizing.
        ax = points.axes
        ax.apply_aspect()
        origin, edge = ax.transData.transform(map_coordinates(ax, [(0, 0), (2.0, 0)]))
        diameter_points = np.linalg.norm(edge - origin) * 72 / ax.figure.dpi
        points.set_sizes([diameter_points ** 2])


class AgentInspector:
    """Hover over current display coordinates, with a constant pixel tolerance.

    The active ID list follows scatter offset order; IDs are never inferred
    from the order of all routes. Re-evaluate on every frame, even when the
    mouse stays still, to avoid inspecting an agent that has already left.
    """
    WAITING = "Seleccione un agente\ncon el cursor..."

    def __init__(self, map_axes, points, panel_axes, radius_pixels=10):
        self.map_axes, self.points = map_axes, points
        self.canvas = map_axes.figure.canvas
        self.radius_pixels = radius_pixels
        self.ids, self.frame, self.cursor = [], {}, None
        self.selected_id = None
        self.time = None
        panel_axes.text(.04, .96, "Telemetría por agente", transform=panel_axes.transAxes,
                        color="white", fontsize=11, weight="bold", va="top")
        self.text = panel_axes.text(.04, .88, self.WAITING, transform=panel_axes.transAxes,
                                   color="white", fontsize=9, va="top", linespacing=1.15)
        panel_axes.text(.04, .06, "Promedio: distancia / tiempo.\nIncluye paradas desde la\nprimera aparición del agente.",
                        transform=panel_axes.transAxes, color="#AAAAAA", fontsize=8, va="bottom")
        self.connections = [
            self.canvas.mpl_connect("motion_notify_event", self.on_motion),
            self.canvas.mpl_connect("figure_leave_event", self.on_leave),
            self.canvas.mpl_connect("resize_event", self.on_leave),
            self.canvas.mpl_connect("close_event", self.disconnect),
        ]

    def reset(self):
        self.ids, self.frame = [], {}
        self.selected_id, self.time = None, None
        self.text.set_text(self.WAITING)

    def disconnect(self, event=None):
        for connection in self.connections:
            self.canvas.mpl_disconnect(connection)

    def on_motion(self, event):
        self.cursor = ((event.x, event.y) if event.inaxes is self.map_axes
                       and event.x is not None and event.y is not None else None)
        if self.refresh():
            self.canvas.draw_idle()

    def on_leave(self, event):
        self.cursor = None
        if self.refresh():
            self.canvas.draw_idle()

    def update(self, time, frame):
        if self.time is not None and time < self.time:
            self.reset()
        self.time = time
        self.frame, self.ids = frame, list(frame)
        self.refresh()

    def refresh(self):
        selected = None
        if self.cursor is not None and self.ids:
            offsets = np.asarray(self.points.get_offsets())
            if len(offsets) == len(self.ids):
                pixels = self.map_axes.transData.transform(offsets)
                distances = np.sum((pixels - self.cursor) ** 2, axis=1)
                nearest = int(np.argmin(distances))
                if distances[nearest] <= self.radius_pixels ** 2:
                    selected = self.ids[nearest]
        self.selected_id = selected
        content = self.WAITING
        if selected is not None:
            value = self.frame[selected]
            states = {"drive": "Circulando", "following": "Seguimiento lento",
                      "yielding": "Cediendo paso / parada obligatoria",
                      "signal": "Detenido ante semaforo",
                      "queued": "Detenido / en cola", "parking": "Parking"}
            agent_label = textwrap.fill(str(selected), width=24)
            content = (f"ID del agente\n{agent_label}\n\n"
                       f"Tiempo transcurrido\n{value.elapsed_clock} ({value.elapsed_time:.1f} s)\n\n"
                       f"Velocidad actual\n{value.speed * 3.6:.2f} km/h\n\n"
                       f"Velocidad maxima\n{value.max_speed * 3.6:.2f} km/h\n\n"
                       f"Velocidad promedio\n{value.mean_speed * 3.6:.2f} km/h\n\n"
                       f"Velocidad mínima\n{value.min_speed * 3.6:.2f} km/h\n\n"
                       f"{textwrap.fill(states.get(value.state, value.state), width=24)}")
        changed = content != self.text.get_text()
        if changed:
            self.text.set_text(content)
        return changed


def create_traffic_figure(lab_name, mode_label, controls=False):
    """Left legend/scales, centre map and fitted timeline, right telemetry."""
    from matplotlib.transforms import Bbox
    fig = plt.figure(figsize=(16, 12), facecolor="black")
    grid = fig.add_gridspec(2 if controls else 1, 3, width_ratios=(3.1, 9.8, 3.0),
                           height_ratios=(11.3, .7) if controls else (1,),
                           left=.02, right=.985, bottom=.035, top=.98, wspace=.08, hspace=.04)
    sidebar = grid[:, 0].subgridspec(4, 1, height_ratios=(1.1,2.2,3.1,3), hspace=.12)
    header = fig.add_subplot(sidebar[0])
    ax = fig.add_subplot(grid[0, 1])
    footer = fig.add_subplot(sidebar[1])
    panel = fig.add_subplot(grid[:, 2])
    fig._traffic_panel = panel
    fig._legend_axes = footer
    if controls:
        fig._slider_axes = fig.add_subplot(grid[1, 1])
        slider_slot = grid[1, 1]
        def locate_slider(_axes, _renderer):
            box = ax.get_position()
            slot = slider_slot.get_position(fig)
            return Bbox.from_bounds(box.x0, slot.y0+.34*slot.height, box.width, .25*slot.height)
        fig._slider_axes.set_axes_locator(locate_slider)
        button_grid = sidebar[2].subgridspec(6, 1, hspace=.22)
        fig._button_axes = [fig.add_subplot(button_grid[i]) for i in range(6)]
    for area in (header, ax, footer, panel):
        area.set_facecolor("black")
        area.axis("off")
    header.text(0, .95, "MATSim | " + lab_name.split(" - ")[0], ha="left", va="top",
                transform=header.transAxes, color="white", fontsize=11)
    text = header.text(0, .66, "", ha="left", va="top", transform=header.transAxes,
                       color="white", fontsize=10,
                       bbox=dict(facecolor="#161616", edgecolor="#555555", boxstyle="round,pad=.3"))
    fig._clock_text = text
    labels = ("0 km/h (cola / ceder paso)", "0 < v ≤ 30 km/h", "30 < v ≤ 60 km/h",
              "60 < v ≤ 100 km/h", "100 < v < 150 km/h", "≥150: rojo/amarillo alternos")
    handles = [Line2D([], [], marker="o", linestyle="", color=color, label=label)
               for color, label in zip(SPEED_COLORS, labels)]
    handles.append(Line2D([], [], marker='o', linestyle='', color='#FFFFFF', label='Parking: 3 s (detenido)'))
    handles.append(Line2D([], [], marker='s', linestyle='', color='#FF4545', label='Semaforo: rojo / amarillo / verde'))
    legend = footer.legend(handles=handles, loc="upper left", ncol=1, facecolor="black",
                  labelcolor="white", fontsize=8, borderaxespad=0)
    # Fit the legend before each draw, including programmatic resizes under Agg.
    original_legend_draw = legend.draw
    def draw_fitted_legend(renderer):
        for label in legend.get_texts():
            label.set_fontsize(8)
        width = legend.get_window_extent(renderer).width
        available = footer.get_window_extent(renderer).width
        if width > available:
            size = max(3, 8 * (available-45) / max(1,width-45))
            for label in legend.get_texts():
                label.set_fontsize(size)
        original_legend_draw(renderer)
    legend.draw = draw_fitted_legend
    ax.set_aspect("equal")
    return fig, ax, text


class PlaybackControls:
    """Widget callbacks and animation ticks share one synchronous render path."""
    def __init__(self, fig, clock, render):
        self.fig, self.clock, self.render = fig, clock, render
        self.slider = Slider(fig._slider_axes, "Hora", 0, DAY_SECONDS - 1,
                             valinit=0, valstep=1, color="#438aac")
        self.slider.label.set_color("white")
        self.slider.valtext.set_color("white")
        self.slider.on_changed(self.seek)
        self.buttons = []
        self.selected_scale = clock.base_speed
        self.doubled = False
        labels = ('Pausa', 'Tiempo real (1x)', '1h = 10 min', '1h = 1 min', '1h = 30 s', '2x')
        callbacks = (self.toggle, lambda e:self.select_scale(1), lambda e:self.select_scale(6),
                     lambda e:self.select_scale(60), lambda e:self.select_scale(120), self.toggle_double)
        for axes, label, callback in zip(fig._button_axes, labels, callbacks):
            button = Button(axes, label, color='#333333', hovercolor='#557788')
            button.label.set_color('white')
            button.on_clicked(callback)
            self.buttons.append(button)
        pause_axes = self.buttons[0].ax
        self.pause_bars = [pause_axes.plot([x,x],[.32,.68], transform=pause_axes.transAxes,
                                         color='white',lw=2)[0] for x in (.16,.20)]
        self.play_icon = Polygon(((.14,.3),(.14,.7),(.24,.5)),transform=pause_axes.transAxes,
                                 facecolor='white',visible=False)
        pause_axes.add_patch(self.play_icon)
        self.slider.label.set_position((0, 1.8))
        self.slider.label.set_horizontalalignment('left')
        self.slider.valtext.set_position((.5, -1.1))
        self.slider.valtext.set_horizontalalignment('center')
        self.closed = False
        fig.canvas.mpl_connect("close_event", self.close)

    def close(self, event=None):
        self.closed = True
        self.slider.disconnect_events()
        for button in self.buttons:
            button.disconnect_events()
        animation = getattr(self.fig, "_traffic_animation", None)
        if animation and animation.event_source:
            animation.event_source.stop()

    def toggle(self, event=None):
        self.set_rate(1 if self.clock.rate == 0 else 0)

    def select_scale(self, scale):
        self.selected_scale = scale
        self.clock.set_scale(scale * (2 if self.doubled else 1))
        self.refresh()
        self.fig.canvas.draw_idle()

    def toggle_double(self, event=None):
        self.doubled = not self.doubled
        self.select_scale(self.selected_scale)

    def refresh(self):
        for i, scale in enumerate((1,6,60,120), start=1):
            self.buttons[i].color = '#285b72' if self.selected_scale == scale else '#333333'
            self.buttons[i].ax.set_facecolor(self.buttons[i].color)
        self.buttons[5].label.set_text('2x: activo' if self.doubled else '2x')
        paused = self.clock.rate == 0
        self.buttons[0].label.set_text('Reanudar' if paused else 'Pausa')
        self.play_icon.set_visible(paused)
        for bar in self.pause_bars:
            bar.set_visible(not paused)
        artists = self.render(self.clock.time)
        self.slider.eventson = self.slider.drawon = False
        try:
            self.slider.set_val(min(DAY_SECONDS - 1, int(self.clock.time % DAY_SECONDS)))
            seconds = int(self.clock.time % DAY_SECONDS)
            self.slider.valtext.set_text(f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}")
        finally:
            self.slider.eventson = self.slider.drawon = True
        return artists

    def seek(self, seconds):
        self.clock.seek_day(seconds)
        self.refresh()
        self.fig.canvas.draw_idle()

    def set_rate(self, rate):
        self.clock.set_rate(rate)
        self.refresh()
        self.fig.canvas.draw_idle()

    def tick(self, _=None):
        if self.closed:
            return []
        self.clock.tick()
        return self.refresh()


def animate_simulation(net_path, events_path, lab_name, mode="microscopic", dt=.2,
                       synthetic_stops=True, check=False, playback_speed=DAY_PLAYBACK_SPEED,
                       routing=None, aggressive_profiles=True, daily=False, focal=False, obstacles=()):
    if not math.isfinite(playback_speed) or playback_speed <= 0:
        raise ValueError("La velocidad de reproducción debe ser positiva y finita")
    if daily and playback_speed != DAY_PLAYBACK_SPEED:
        raise ValueError("El ciclo diario requiere escala inicial 120: 1 h en 30 s")
    nodes, links = load_network(net_path)
    if focal and mode == "microscopic":
        for road in links.values():
            road["freespeed"] = float(road["attributes"].get("focalBaseSpeed", road["freespeed"]))
        synthetic_stops = False
        routing = "observed"
    areas = load_special_areas(net_path)
    routes = read_operations(events_path, links)
    if not routes:
        raise ValueError("No se encontraron trayectos completos en los eventos.")
    multilane = any(r.get("lane_changing", False) for r in links.values())
    routing = routing or ("balanced" if mode == "microscopic" and not daily else "observed")
    if mode == "replay" and routing != "observed":
        raise ValueError("El modo replay requiere --routing observed para conservar las rutas XML")
    print(f"Rutas XML: enlaces y km por zona = {routing_summary(routes, links)}")
    if routing == "balanced":
        routes = balanced_routes(routes, links, aggressive_profiles,
                                 progress=lambda done, total: print(f"Rutas preparadas: {done}/{total}", flush=True))
        print(f"Rutas sintéticas: enlaces y km por zona = {routing_summary(routes, links)}")
    if daily and mode != "microscopic":
        raise ValueError("El ciclo diario requiere --mode microscopic; use --no-day para replay")
    if daily:
        if abs(4 / dt - round(4 / dt)) > 1e-8:
            raise ValueError("En modo diario dt debe dividir 4 s y 3 s")
        routes = daily_operations(routes)
    engine = MicroscopicPlayback(routes, links, dt, synthetic_stops,
                                 aggressive_profiles=aggressive_profiles, daily=daily, focal=focal, obstacles=obstacles, persistent=focal) if mode == "microscopic" else None
    if engine and focal:
        print(f"Perfil focal Python: {engine.focal_profile.kind}; reloj interno en horas, escala {playback_speed:g}x")
    frame_factory = ((lambda: engine.frames(start_time=0, end_time=DAY_SECONDS)) if daily else
                     engine.frames if engine else lambda: replay_frames(routes, links, dt))
    print(f"Agentes: {len(routes)}. Modo: {mode}. Paso: {dt} s.")
    if engine:
        print("Modelo visual sintético: colas, rutas balanceadas y excesos de velocidad "
              "no alteran los resultados de MATSim.")
    if check:
        count = 0
        color_counts = Counter()
        hourly = defaultdict(lambda: [0, 0, 0.0])
        max_speed = 0.0
        reported_hour = -1
        for time, frame in frame_factory():
            if focal and set(frame) != set(routes):
                raise ValueError('El agente focal desaparecio o cambio de identidad')
            if daily and int(time // 3600) != reported_hour:
                reported_hour = int(time // 3600)
                print(f"Validando {reported_hour:02d}:00; activos={len(frame)}", flush=True)
            lanes = defaultdict(list)
            for agent, sample in frame.items():
                if not all(math.isfinite(x) for x in (sample.distance, sample.speed)):
                    raise ValueError("Posición o velocidad inválida")
                if not all(math.isfinite(x) and x >= 0 for x in
                           (sample.elapsed_time, sample.travelled_distance, sample.min_speed, sample.max_speed, sample.mean_speed)):
                    raise ValueError("Telemetría inválida")
                if sample.max_speed + 1e-8 < sample.speed:
                    raise ValueError('Maximum speed smaller than instantaneous speed')
                if sample.state in ("parking", "queued") and sample.speed != 0:
                    raise ValueError("Estado detenido con velocidad distinta de cero")
                if sample.state == "following" and sample.speed > 30 / 3.6:
                    raise ValueError("Estado de cola lenta con velocidad superior a 30 km/h")
                lanes[sample.link, sample.lane].append(sample.distance)
                color_counts[sample_color(sample, count)] += 1
                max_speed = max(max_speed, sample.speed)
                bucket = hourly[min(23, int(time // 3600))]
                bucket[0] += 1
                bucket[1] += sample.state in ("queued", "following", "parking", "signal", "yielding")
                bucket[2] += sample.speed * 3.6
                if engine and sample.speed > desired_speed(engine.focal_profile or agent_profile(agent), links[sample.link], aggressive_profiles, time if daily else None) + 1e-8:
                    raise ValueError("Velocidad superior al límite del perfil para esta vía")
            if engine:
                for distances in lanes.values():
                    distances.sort()
                    if any(b - a < GAP - 1e-6 for a, b in zip(distances, distances[1:])):
                        raise ValueError("Solapamiento longitudinal en un carril")
            count += 1
        print(f"Validacion de posiciones y velocidades OK: {count} cuadros, hasta t={time:.1f} s.")
        print(f"Máxima observada: {max_speed * 3.6:.2f} km/h. Muestras por color: {dict(color_counts)}")
        if engine:
            print(f"Pico simultaneo en red: {engine.peak_active}; cambios de carril: {len(engine.lane_change_log)}")
            sources = defaultdict(int)
            for _, start, end, source, _, _ in engine.parking_log:
                sources[source] += 1
                if source == "synthetic" and abs(end - start - 3) > 1e-8:
                    raise ValueError("Duración incorrecta de parada sintética")
            print(f"Agentes completados: {engine.completed}. Parking: {dict(sources)}")
        if daily:
            print("Hora | muestras | detenidas/cola | velocidad media km/h")
            for hour, (samples, queued, speed_sum) in sorted(hourly.items()):
                print(f"{hour:02d} | {samples} | {queued} | {speed_sum / max(1, samples):.2f}")
            print(f"Agente persistente activo: {engine.peak_active}" if focal else f"Pendientes a medianoche: {len(routes) - engine.completed}")
            if engine.completed < len(routes) and not focal:
                print("Descarga de demanda NO confirmada: hay viajes pendientes; "
                      "la validez de los cuadros no demuestra ausencia de bloqueos.")
            if engine.gridlock_time is not None:
                raise RuntimeError(f"Validacion de descarga fallida: bloqueo permanente certificado "
                                   f"a t={engine.gridlock_time:.1f} s")
        return

    cache = None
    if daily:
        print("Preparando agente focal persistente..." if focal else
              "Preparando dias consecutivos y verificando continuidad...", flush=True)
        cache = FocalContinuousCache(engine) if focal else PeriodicFrameCache(engine, progress=lambda t: print(
            f"Preparacion: {int(t // 3600):02d} h simuladas", flush=True))
    mode_label = (f"Microscópico · rutas {routing} · perfiles agresivos {'sí' if aggressive_profiles else 'no'}"
                  if engine else "Reproducción de rutas y tiempos XML")
    fig, ax, text = create_traffic_figure(lab_name, mode_label, controls=daily)
    if focal:
        configure_zona1_projection(ax, nodes, load_map_registration(net_path))
    draw_special_areas(ax, areas)
    draw_points_of_interest(ax, load_points_of_interest(net_path))
    for data in links.values():
        draw_road(ax, data)
    signal_roads = [r for r in links.values() if r.get('signal_plan')]
    signal_display = SignalDisplay(ax, signal_roads)
    fig._traffic_signals = signal_display
    # One collection avoids hundreds of separate artist updates per frame.
    points = ax.scatter([], [], s=5 if any("lane_width" in r for r in links.values()) else 14,
                        edgecolors="none", zorder=3)
    points._focal = focal
    if focal:
        points.set_zorder(4)
    hitbox = Polygon(map_coordinates(ax, np.repeat([next(iter(nodes.values()))], 4, axis=0)), closed=True, facecolor='cyan', edgecolor='white', zorder=4, visible=False) if focal else None
    if hitbox is not None:
        ax.add_patch(hitbox)
    for x,y,u,v in obstacles:
        ax.add_patch(Polygon(map_coordinates(ax, ((x,y),(u,y),(u,v),(x,v))), color='red', alpha=.4))
    if focal:
        add_zona1_basemap(ax)
    inspector = AgentInspector(ax, points, fig._traffic_panel)
    fig._agent_inspector = inspector  # Keep callbacks alive for the figure lifetime.

    def init():
        render_agents(points, {}, links)
        text.set_text("")
        inspector.reset()
        return [points, text, inspector.text]

    def update(item):
        index, (time, frame) = item
        signal_display.update(time)
        hours, rest = divmod(time % DAY_SECONDS, 3600)
        minutes, seconds = divmod(rest, 60)
        max_kmh = max((s.speed for s in frame.values()), default=0) * 3.6
        text.set_text(f"Hora: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}\n"
                      f"Escala: {playback_speed:g}x\nActivos: {len(frame)}")
        render_agents(points, frame, links, index)
        if hitbox is not None:
            hitbox.set_visible(bool(frame))
            if frame:
                sample = next(iter(frame.values()))
                hitbox.set_xy(map_coordinates(ax, vehicle_hitbox(links[sample.link], sample.distance, sample.lane)))
                hitbox.set_facecolor(sample_color(sample, index))
        inspector.update(time, frame)
        if daily:
            text.set_text(f"Dia {int(time // DAY_SECONDS) + 1}\n"
                          f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
                          f"\n{clock.rate:+.1f}x | Escala: {clock.base_speed:g}x\nActivos: {len(frame)}")
            if focal:
                elapsed = f"{max(s.elapsed_time for s in frame.values()) / 3600:.4f} h" if frame else "inactivo"
                text.set_text(f"Hora: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}\n"
                              f"Dia {int(time // DAY_SECONDS)+1} | Escala: {clock.base_speed:g}x\n"
                              f"Viaje: {elapsed}")
        return [points, text, inspector.text, *signal_display.artists]

    if daily:
        clock = PlaybackClock(playback_speed, now=wall_time.perf_counter)
        display_frame = 0
        def render_time(t):
            nonlocal display_frame
            display_frame += 1
            return update((display_frame, (t, cache.at(t))))
        controls = PlaybackControls(fig, clock, render_time)
        ani = animation.FuncAnimation(fig, controls.tick, init_func=controls.refresh, blit=False,
                                      interval=1000 / 30, repeat=False, cache_frame_data=False)
        fig._day_cache = cache
        fig._playback_controls = controls
    else:
        ani = animation.FuncAnimation(fig, update, frames=lambda: enumerate(frame_factory()), init_func=init,
                                      blit=True, interval=1000 * dt / playback_speed,
                                      repeat=True, cache_frame_data=False)
    # Retain the animation for the lifetime of the figure, including nonblocking backends.
    fig._traffic_animation = ani
    plt.show()


LAB_FOLDERS = {
    "1": "01-linea-recta",
    "2": "02-grid-network",
    "3": "03-bottleneck",
    "4": "04-lanes-turns",
    "5": ("05-zona1", "05-mini-city-directed", "05-mini-city"),
    "6": "06-zona1",
    "7": "07-multilane-zona1",
    "8": ("08-zona1-warped", "08-zona1-utm", "08-zona1-irregular", "08-zona1-signals", "08-zona1-right-of-way", "08-zona1-priority", "08-zona1-historic"),
}


def resolve_input_paths(lab, iteration=None, project_root=None, output_dir=None):
    """Explicit iterations never silently fall back to another run."""
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    folder_names = LAB_FOLDERS[lab]
    if isinstance(folder_names, str):
        folder_names = (folder_names,)
    output = next(
        (root / "output" / "labs" / name for name in folder_names
         if (root / "output" / "labs" / name).is_dir()),
        root / "output" / "labs" / folder_names[0],
    )
    if output_dir is not None:
        output = Path(output_dir).resolve()
    network = output / "output_network.xml.gz"
    events = (output / "output_events.xml.gz" if iteration is None else
              output / "ITERS" / f"it.{iteration}" / f"{iteration}.events.xml.gz")
    paths = []
    for path in (network, events):
        if not path.is_file():
            path = path.with_suffix("")  # Also support uncompressed XML.
        if not path.is_file():
            raise FileNotFoundError(f"No se encontró {path} ni su versión .gz")
        paths.append(path)
    return tuple(paths)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab", choices=LAB_FOLDERS, default="4", help="Número de laboratorio")
    parser.add_argument("--iter", type=int, default=None,
                        help="Iteración exacta; sin esta opción usa output_events.xml.gz")
    parser.add_argument("--mode", choices=("microscopic", "replay"), default="microscopic",
                        help="Modelo visual con colas o reproducción de tiempos XML")
    parser.add_argument("--day", action=argparse.BooleanOptionalAction, default=None,
                        help="Ciclo 00:00-24:00 a 120x (predeterminado en Lab06/07 microscopico)")
    parser.add_argument("--dt", type=float, default=None, help="Paso temporal en segundos (predeterminado: 0.2)")
    parser.add_argument("--playback-speed", type=float, default=None,
                        help="Factor de reproducción visual (60 por defecto, 1 para tiempo real)")
    parser.add_argument("--no-synthetic-stops", action="store_true", help="Usar sólo parking observado en XML")
    parser.add_argument("--routing", choices=("balanced", "observed"), default=None,
                        help="Rutas visuales repartidas (microscopic) o rutas originales (replay)")
    parser.add_argument("--no-aggressive-profiles", action="store_true",
                        help="Desactivar los excesos de velocidad sintéticos del bypass")
    parser.add_argument("--output-dir", type=Path, help="Carpeta exacta de resultados MATSim")
    parser.add_argument("--obstacles", type=Path, help="Lab08: JSON con cajas [xmin,ymin,xmax,ymax] en metros")
    parser.add_argument("--check", action="store_true", help="Validar todos los cuadros sin abrir ventana")
    args = parser.parse_args()
    args.day = (args.lab in ("6", "7", "8") and args.mode == "microscopic") if args.day is None else args.day
    if args.lab == "8" and args.mode == "microscopic" and not args.day:
        parser.error("Lab08 microscopico requiere --day para el reloj 120x")
    args.dt = args.dt if args.dt is not None else (.5 if args.day else .2)
    args.playback_speed = args.playback_speed if args.playback_speed is not None else DAY_PLAYBACK_SPEED
    if args.day and args.playback_speed != DAY_PLAYBACK_SPEED:
        parser.error("El ciclo diario usa exactamente --playback-speed 120")
    if not math.isfinite(args.dt) or args.dt <= 0:
        parser.error("--dt debe ser positivo y finito")
    if args.iter is not None and args.iter < 0:
        parser.error("--iter debe ser mayor o igual a cero")
    try:
        obstacles = json.loads(args.obstacles.read_text(encoding='utf-8')) if args.obstacles else []
        if args.obstacles and (args.lab != '8' or args.mode != 'microscopic'):
            parser.error('--obstacles requiere Lab08 microscopico')
        net_file, events_file = resolve_input_paths(args.lab, args.iter, output_dir=args.output_dir)
        label = f"Iteración {args.iter}" if args.iter is not None else "Salida final"
        lab_folder = net_file.parent.name
        lab_title = f"Lab {args.lab} - {lab_folder} - {label}"
        print(f"Red: {net_file}")
        print(f"Eventos: {events_file}")
        animate_simulation(net_file, events_file, lab_title, args.mode, args.dt,
                           not args.no_synthetic_stops, args.check, args.playback_speed,
                           args.routing, not args.no_aggressive_profiles, args.day, args.lab == "8", obstacles)
    except (OSError, EOFError, ET.ParseError, KeyError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Error al cargar la simulación: {exc}\n")


if __name__ == "__main__":
    main()
