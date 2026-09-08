# -*- coding: utf-8 -*-
"""London + commuter-belt coverage map — live coverage (Sept 2026).

Coverage status is derived from real 30-day activity per area (see build_pdf.py).
London boroughs are filled by status; commuter-belt towns (outside Greater London)
are drawn as point markers. The River Thames is drawn as the North/South divider.
The red outline is the Greater London boundary (NOT the M25).
"""
import json, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.lines import Line2D
import matplotlib.patheffects as pe

LAT0, LNG0 = 51.5, -0.15
def proj(lng, lat):
    return ((lng - LNG0) * 111.32 * math.cos(math.radians(LAT0)), (lat - LAT0) * 110.57)

# ---------------------------------------------------------------------------
# Borough coverage status (33 London local authorities).
#   S = South London borough, covered (green)
#   N = North London borough, covered (blue)
#   E = expansion roadmap, not yet covered (amber)
#   U = not targeted (grey)
# A borough is "covered" if a live area with real 30-day activity sits in it.
# ---------------------------------------------------------------------------
STATUS = {
    # South (covered)
    "Greenwich": "S", "Lewisham": "S", "Southwark": "S", "Lambeth": "S",
    "Wandsworth": "S", "Bexley": "S", "Bromley": "S", "Croydon": "S",
    "Sutton": "S", "Merton": "S", "Kingston upon Thames": "S",
    # North (covered)
    "Hackney": "N", "Haringey": "N", "Waltham Forest": "N", "Enfield": "N",
    "Ealing": "N", "Redbridge": "N", "Tower Hamlets": "N", "Newham": "N",
    "Barking and Dagenham": "N", "Barnet": "N", "Islington": "N",
    # Expansion roadmap (not yet covered)
    "Brent": "E", "Harrow": "E", "Camden": "E", "Hammersmith and Fulham": "E",
    "Havering": "E", "Richmond upon Thames": "E", "Hounslow": "E", "Hillingdon": "E",
    "Westminster": "E", "Kensington and Chelsea": "E",
    # Not targeted — negligible residential rental stock (almost entirely commercial)
    "City of London": "U",
}

# Commuter-belt districts (outside Greater London) — covered, filled blue.
# LAD name -> (town label, label lat, label lng)  [label placed at the covered town]
COMMUTER_DISTRICTS = {
    "Hertsmere": ("Borehamwood", 51.655, -0.272),
    "Welwyn Hatfield": ("Welwyn", 51.802, -0.207),
    "Dacorum": ("Berkhamsted", 51.762, -0.565),
    "Chiltern": ("Great Missenden", 51.704, -0.706),
    "Wycombe": ("Wooburn Green", 51.586, -0.690),
    "Epping Forest": ("Chigwell / Epping", 51.685, 0.095),
    "Harlow": ("Harlow / Roydon", 51.772, 0.100),
    "Brentwood": ("Brentwood", 51.621, 0.305),
}
# Hanworth — the one covered *area* inside the (otherwise uncovered, north-of-river)
# Hounslow borough. Shown as a South marker, and it is the single Thames exception.
HANWORTH = ("Hanworth", 51.418, -0.398)

DISP = {"Barking and Dagenham": "Barking &\nDagenham",
        "Hammersmith and Fulham": "Hammersmith\n& Fulham",
        "Kingston upon Thames": "Kingston", "Richmond upon Thames": "Richmond",
        "Kensington and Chelsea": "Kensington\n& Chelsea", "City of London": "City"}

C_S, C_N, C_E, C_U = "#1b9e77", "#3f6fb0", "#f2c078", "#e9edf0"
FILL = {"S": C_S, "N": C_N, "E": C_E, "U": C_U}
TXT = {"S": "white", "N": "white", "E": "#7a4a00", "U": "#9aa4ad"}
HALO = {"S": "#12503c", "N": "#233f66", "E": "white", "U": "white"}

THAMES = [(-0.39,51.405),(-0.34,51.41),(-0.31,51.415),(-0.28,51.44),
          (-0.23,51.47),(-0.19,51.46),(-0.16,51.482),(-0.13,51.487),(-0.12,51.507),(-0.075,51.509),
          (-0.045,51.505),(-0.02,51.502),(0.0,51.492),(0.02,51.503),(0.05,51.492),(0.072,51.49),
          (0.10,51.508),(0.14,51.505),(0.18,51.50),(0.24,51.49),(0.30,51.47)]
BBOX = (-0.90, 0.65, 51.20, 51.95)

RED_RING = [(-0.16,51.69),(0.02,51.68),(0.16,51.64),(0.26,51.58),(0.30,51.50),(0.27,51.41),
            (0.17,51.34),(0.02,51.30),(-0.16,51.29),(-0.33,51.32),(-0.47,51.41),(-0.51,51.52),
            (-0.45,51.62),(-0.31,51.68),(-0.16,51.69)]
YELLOW_RING = [(-0.42,51.89),(-0.08,51.87),(0.22,51.80),(0.47,51.72),(0.58,51.60),(0.55,51.48),
               (0.44,51.37),(0.24,51.30),(-0.02,51.26),(-0.28,51.29),(-0.52,51.36),(-0.70,51.47),
               (-0.78,51.60),(-0.70,51.74),(-0.55,51.84),(-0.42,51.89)]

def shoelace(r):
    return 0.5*sum(r[i][0]*r[i+1][1]-r[i+1][0]*r[i][1] for i in range(len(r)-1))
def centroid(r):
    A=shoelace(r)
    if abs(A)<1e-9: return sum(p[0] for p in r)/len(r), sum(p[1] for p in r)/len(r)
    cx=sum((r[i][0]+r[i+1][0])*(r[i][0]*r[i+1][1]-r[i+1][0]*r[i][1]) for i in range(len(r)-1))
    cy=sum((r[i][1]+r[i+1][1])*(r[i][0]*r[i+1][1]-r[i+1][0]*r[i][1]) for i in range(len(r)-1))
    return cx/(6*A), cy/(6*A)

fig, ax = plt.subplots(figsize=(15, 11))

# --- Regional basemap: surrounding districts so nothing renders as blank white.
#     Inside the commuter-belt target ring -> amber (expansion roadmap);
#     outside it -> light grey (context / not targeted).
def _pip(x, y, ring):
    inside = False; n = len(ring); j = n-1
    for i in range(n):
        xi, yi = ring[i]; xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj-xi)*(y-yi)/(yj-yi)+xi):
            inside = not inside
        j = i
    return inside
ROADMAP_LABELS = {
    "St Albans": "St Albans", "Watford": "Watford", "Three Rivers": "Rickmansworth",
    "East Hertfordshire": "Hertford", "Broxbourne": "Broxbourne", "Luton": "Luton",
    "Stevenage": "Stevenage", "North Hertfordshire": "Hitchin", "Chelmsford": "Chelmsford",
    "Basildon": "Basildon", "Thurrock": "Grays", "Slough": "Slough",
    "Windsor and Maidenhead": "Maidenhead", "Dartford": "Dartford", "Sevenoaks": "Sevenoaks",
    "Epsom and Ewell": "Epsom", "Reigate and Banstead": "Reigate", "Spelthorne": "Staines",
}
_region = json.load(open("region_districts.geojson"))
for f in _region["features"]:
    nm = f["properties"].get("LAD19NM")
    if nm in STATUS or nm in COMMUTER_DISTRICTS:
        continue  # London boroughs + covered commuter districts are drawn separately
    g = f["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    allpts = [c for poly in polys for c in poly[0]]
    clon = sum(p[0] for p in allpts)/len(allpts); clat = sum(p[1] for p in allpts)/len(allpts)
    inside = _pip(clon, clat, YELLOW_RING)
    col = C_E if inside else "#eef1f4"
    for poly in polys:
        r = [proj(c[0], c[1]) for c in poly[0]]
        ax.add_patch(MplPolygon(r, closed=True, facecolor=col, edgecolor="white",
                                linewidth=0.7, alpha=0.9, zorder=1))
    if inside and nm in ROADMAP_LABELS:
        x, y = proj(clon, clat)
        t = ax.text(x, y, ROADMAP_LABELS[nm], fontsize=6.2, ha="center", va="center",
                    color="#7a4a00", fontweight="bold", zorder=5)
        t.set_path_effects([pe.withStroke(linewidth=1.6, foreground="white")])

gj = json.load(open("london_boroughs.geojson"))
for f in gj["features"]:
    name = f["properties"]["name"]
    st = STATUS.get(name, "U")
    g = f["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    rings = [[proj(c[0], c[1]) for c in poly[0]] for poly in polys]
    for r in rings:
        ax.add_patch(MplPolygon(r, closed=True, facecolor=FILL[st], edgecolor="white",
                                linewidth=0.9 if st == "U" else 1.2, alpha=0.92, zorder=2))
    best = max(rings, key=lambda r: abs(shoelace(r)))
    cx, cy = centroid(best)
    label = DISP.get(name, name)
    fs = 6.3 if st in ("E", "U") else 7.0
    t = ax.text(cx, cy, label, fontsize=fs, ha="center", va="center", color=TXT[st],
                fontweight="bold", zorder=6, linespacing=0.9)
    t.set_path_effects([pe.withStroke(linewidth=2.0, foreground=HALO[st])])

# River Thames — the North/South divider
tx = [proj(l, la) for l, la in THAMES]
ax.plot([p[0] for p in tx], [p[1] for p in tx], color="#4f97d6", linewidth=4.0,
        alpha=0.95, zorder=4, solid_capstyle="round")

# Commuter-belt districts (covered, filled blue), labelled by the covered town
cg = json.load(open("commuter_districts.geojson"))
for f in cg["features"]:
    lad = f["properties"].get("LAD19NM")
    if lad not in COMMUTER_DISTRICTS:
        continue
    g = f["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    for poly in polys:
        r = [proj(c[0], c[1]) for c in poly[0]]
        ax.add_patch(MplPolygon(r, closed=True, facecolor=C_N, edgecolor="white",
                                linewidth=1.2, alpha=0.92, zorder=2))
    town, tla, tl = COMMUTER_DISTRICTS[lad]
    x, y = proj(tl, tla)
    t = ax.text(x, y, town, fontsize=8.2, ha="center", va="center", color="white",
                fontweight="bold", zorder=6)
    t.set_path_effects([pe.withStroke(linewidth=2.2, foreground="#233f66")])

# Hanworth — covered South area inside Hounslow (the Thames exception)
hx, hy = proj(HANWORTH[2], HANWORTH[1])
ax.scatter([hx], [hy], s=190, c=C_S, edgecolors="white", linewidths=1.6, zorder=7)
t = ax.text(hx, hy-1.6, HANWORTH[0]+" *", fontsize=8.0, ha="center", va="top",
            color="#12503c", fontweight="bold", zorder=7)
t.set_path_effects([pe.withStroke(linewidth=2.2, foreground="white")])

# North / South orientation labels
for txt, la, l, col in [("NORTH OF THE THAMES", 51.88, -0.32, "#3f6fb0"),
                        ("SOUTH OF THE THAMES", 51.23, -0.05, "#1b9e77")]:
    x, y = proj(l, la)
    ax.text(x, y, txt, fontsize=11, ha="center", va="center", color=col,
            fontweight="bold", alpha=0.5, style="italic", zorder=3)

# Focus-zone boundaries (approximate): yellow = commuter belt, red = Greater London
for ring, col in [(YELLOW_RING, "#f2c400"), (RED_RING, "#e11d1d")]:
    pts = [proj(l, la) for l, la in ring]
    ln, = ax.plot([p[0] for p in pts], [p[1] for p in pts], color=col, linewidth=5.0,
                  alpha=0.9, zorder=9, solid_capstyle="round", solid_joinstyle="round")
    ln.set_path_effects([pe.withStroke(linewidth=7.5, foreground="white")])

legend = [
    Line2D([0],[0],marker="s",color="w",markerfacecolor=C_S,markersize=15,label="South London — covered  (11 boroughs)"),
    Line2D([0],[0],marker="s",color="w",markerfacecolor=C_N,markersize=15,label="North London — covered  (11 boroughs)"),
    Line2D([0],[0],marker="s",color="w",markerfacecolor=C_N,markersize=15,label="Commuter-belt district — covered"),
    Line2D([0],[0],marker="s",color="w",markerfacecolor=C_E,markersize=15,label="Expansion roadmap  (not yet covered)"),
    Line2D([0],[0],marker="s",color="w",markerfacecolor=C_U,markersize=15,label="Not targeted"),
    Line2D([0],[0],color="#e11d1d",linewidth=4.5,label="Greater London — approx. (not the M25)"),
    Line2D([0],[0],color="#f2c400",linewidth=4.5,label="Commuter belt (target)"),
    Line2D([0],[0],color="#4f97d6",linewidth=4.0,label="River Thames (North / South divider)"),
]
ax.legend(handles=legend, loc="upper center", bbox_to_anchor=(0.5,-0.005), ncol=3, fontsize=11.5,
          frameon=True, facecolor="white", edgecolor="#c4ccd4", framealpha=0.96, borderpad=0.9,
          labelspacing=0.7, columnspacing=1.5, handletextpad=0.5)
x0,_=proj(BBOX[0],LAT0); x1,_=proj(BBOX[1],LAT0)
_,y0=proj(LNG0,BBOX[2]); _,y1=proj(LNG0,BBOX[3])
ax.set_xlim(x0-2,x1+2); ax.set_ylim(y0-2,y1+2)
ax.set_aspect("equal"); ax.axis("off")
ax.set_title("Coverage — North & South London and the Commuter Belt",
             fontsize=19, fontweight="bold", color="#1a2530", pad=12)
fig.savefig("coverage_map.png", dpi=200, bbox_inches="tight", facecolor="white")
print("map written")
