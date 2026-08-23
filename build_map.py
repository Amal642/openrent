# -*- coding: utf-8 -*-
"""London + commuter-belt coverage map — real filled district boundaries."""
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

# South London boroughs — covered
SOUTH = {"Greenwich","Bexley","Lewisham","Southwark","Croydon","Wandsworth",
         "Kingston upon Thames","Lambeth","Sutton","Merton","Hounslow","Bromley"}
# North London = commuter-belt districts (client definition) -> label by the town we cover
COMMUTER = {"Hertsmere":"Borehamwood","Welwyn Hatfield":"Welwyn","Dacorum":"Berkhamsted",
            "Chiltern":"Great Missenden","Wycombe":"Wooburn Green","Epping Forest":"Chigwell / Epping",
            "Harlow":"Harlow / Roydon","Brentwood":"Brentwood"}
# Expansion roadmap — London boroughs held
EXPANSION = {"Haringey","Enfield","Waltham Forest","Newham","Redbridge","Tower Hamlets","Hackney",
             "Ealing","Barking and Dagenham","Hammersmith and Fulham","Islington","Camden","Brent",
             "Harrow","Havering","Richmond upon Thames"}
DISP = {"Barking and Dagenham":"Barking &\nDagenham","Hammersmith and Fulham":"Hammersmith\n& Fulham",
        "Kingston upon Thames":"Kingston","Richmond upon Thames":"Richmond","Waltham Forest":"Waltham Forest",
        "Tower Hamlets":"Tower Hamlets"}
CARED = SOUTH | set(COMMUTER) | EXPANSION

C_S,C_N,C_E,C_U = "#1b9e77","#3f6fb0","#f2c078","#e9edf0"
THAMES = [(-0.31,51.415),(-0.28,51.44),(-0.23,51.47),(-0.19,51.46),(-0.16,51.482),(-0.13,51.487),
          (-0.12,51.507),(-0.075,51.509),(-0.045,51.505),(-0.02,51.502),(0.0,51.492),(0.02,51.503),
          (0.05,51.492),(0.072,51.49),(0.10,51.508),(0.14,51.505)]
BBOX = (-0.88, 0.62, 51.22, 51.93)  # lng_min,lng_max,lat_min,lat_max

# Focus boundaries (approx, matching the client's red/yellow zones)
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

def status(name):
    if name in SOUTH: return "S"
    if name in COMMUTER: return "N"
    if name in EXPANSION: return "E"
    return "U"
FILL={"S":C_S,"N":C_N,"E":C_E,"U":C_U}
TXT={"S":"white","N":"white","E":"#7a4a00","U":"#9aa4ad"}
HALO={"S":"#12503c","N":"#233f66","E":"white","U":"white"}

fig, ax = plt.subplots(figsize=(15, 11))
gj = json.load(open("eng_lad.json"))
for f in gj["features"]:
    name = f["properties"]["LAD13NM"]
    g=f["geometry"]; polys=g["coordinates"] if g["type"]=="MultiPolygon" else [g["coordinates"]]
    rings=[[proj(c[0],c[1]) for c in poly[0]] for poly in polys]
    # bbox filter by lon/lat centroid of largest ring (unless it's one we care about)
    best=max(rings,key=lambda r:abs(shoelace(r)))
    clon=sum(c[0] for poly in polys for c in poly[0])/sum(len(poly[0]) for poly in polys)
    clat=sum(c[1] for poly in polys for c in poly[0])/sum(len(poly[0]) for poly in polys)
    inbox = BBOX[0]<=clon<=BBOX[1] and BBOX[2]<=clat<=BBOX[3]
    if not (inbox or name in CARED): continue
    st=status(name)
    for r in rings:
        ax.add_patch(MplPolygon(r,closed=True,facecolor=FILL[st],edgecolor="white",
                                linewidth=0.9 if st=="U" else 1.2, alpha=0.9, zorder=2))
    if st=="U": continue
    cx,cy=centroid(best)
    label = COMMUTER[name] if st=="N" else DISP.get(name,name)
    fs = 9.0 if st=="N" else (6.6 if st=="E" else 7.2)
    t=ax.text(cx,cy,label,fontsize=fs,ha="center",va="center",color=TXT[st],fontweight="bold",zorder=6,linespacing=0.9)
    t.set_path_effects([pe.withStroke(linewidth=2.0,foreground=HALO[st])])

tx=[proj(l,la) for l,la in THAMES]
ax.plot([p[0] for p in tx],[p[1] for p in tx],color="#6fa8d6",linewidth=3.4,alpha=0.95,zorder=4,solid_capstyle="round")

# focus-zone boundaries
for ring,col in [(YELLOW_RING,"#f2c400"),(RED_RING,"#e11d1d")]:
    pts=[proj(l,la) for l,la in ring]
    ln,=ax.plot([p[0] for p in pts],[p[1] for p in pts],color=col,linewidth=5.0,alpha=0.9,
                zorder=9,solid_capstyle="round",solid_joinstyle="round")
    ln.set_path_effects([pe.withStroke(linewidth=7.5,foreground="white")])

legend=[
    Line2D([0],[0],marker="s",color="w",markerfacecolor=C_S,markersize=15,label="South London — covered  (12 boroughs)"),
    Line2D([0],[0],marker="s",color="w",markerfacecolor=C_N,markersize=15,label="North London / commuter belt — covered"),
    Line2D([0],[0],marker="s",color="w",markerfacecolor=C_E,markersize=15,label="Expansion roadmap  (London boroughs)"),
    Line2D([0],[0],marker="s",color="w",markerfacecolor=C_U,markersize=15,label="Not targeted"),
    Line2D([0],[0],color="#e11d1d",linewidth=4.5,label="Focus zone — Greater London"),
    Line2D([0],[0],color="#f2c400",linewidth=4.5,label="Focus zone — commuter belt"),
]
ax.legend(handles=legend,loc="upper center",bbox_to_anchor=(0.5,-0.005),ncol=3,fontsize=12,frameon=True,
          facecolor="white",edgecolor="#c4ccd4",framealpha=0.96,borderpad=0.9,labelspacing=0.7,columnspacing=1.6,handletextpad=0.5)
x0,_=proj(BBOX[0],LAT0); x1,_=proj(BBOX[1],LAT0)
_,y0=proj(LNG0,BBOX[2]); _,y1=proj(LNG0,BBOX[3])
ax.set_xlim(x0-2,x1+2); ax.set_ylim(y0-2,y1+2)
ax.set_aspect("equal"); ax.axis("off")
ax.set_title("Coverage — South London Boroughs & North London / Commuter Belt",fontsize=19,fontweight="bold",color="#1a2530",pad=12)
fig.savefig("coverage_map.png",dpi=200,bbox_inches="tight",facecolor="white")
print("map written")
