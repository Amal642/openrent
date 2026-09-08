# -*- coding: utf-8 -*-
"""Assemble the client-facing London coverage PDF.

Coverage tables and headline figures are built from live 30-day activity
(coverage_areas.json, exported from the platform database). Region = South
(south of the Thames) / North (north of the Thames + commuter belt).
"""
import json
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, NextPageTemplate,
                                PageBreak, Paragraph, Spacer, Image, Table, TableStyle, HRFlowable)

NAVY = colors.HexColor("#1a2530"); SOUTH = colors.HexColor("#1b9e77")
NORTH = colors.HexColor("#3f6fb0"); AMBER = colors.HexColor("#e08a1e")
LGREY = colors.HexColor("#eef1f4"); MGREY = colors.HexColor("#6b7683")

# ---------------------------------------------------------------------------
# Live area data -> display name (None = drop from client report)
# ---------------------------------------------------------------------------
DISPLAY = {
    # North & commuter belt
    "3 Kingsley Ave, Borehamwood WD6 4LY, UK": "Borehamwood",
    "21 Chester Road, Chigwell IG7 6AH, UK": "Chigwell",
    "Finsbury Park, London": "Finsbury Park",
    "Acton, London": "Acton",
    "Ealing, Greater London": "Ealing",
    "South Park Cottages, Herongate, Warley, Brentwood CM13 3SA, UK": "Brentwood",
    "Wood Green, London": "Wood Green",
    "National Cycle Rte 57, Welwyn AL6 9BD, UK": "Welwyn",
    "Bow, London": "Bow",
    "Hackney, London": "Hackney",
    "Wessex House, Marlow Rd, Wooburn Green, Bourne End SL8 5SP, UK": "Wooburn Green",
    "Ilford, Greater London": "Ilford",
    "The Homestead, Tylers Rd, Roydon, Harlow CM19 5LJ, UK": "Harlow / Roydon",
    "11A Main Rd S, Dagnall, Berkhamsted HP4 1QX, UK": "Berkhamsted",
    "Leytonstone, London": "Leytonstone",
    "Enfield, London": "Enfield",
    "Enfield, Greater London": "Enfield",
    "Edmonton, London": "Edmonton",
    "Walthamstow, London": "Walthamstow",
    "Barnet, London": "Barnet",
    "Tottenham, London": "Tottenham",
    "CM19 5LJ Epping Forest, Essex": "Epping",
    "Leyton, London": "Leyton",
    "Stratford, London": "Stratford",
    "Unnamed Road, Great Missenden, Uk": "Great Missenden",
    "Finchley, London": "Finchley",
    "East Ham, London": "East Ham",
    "Barking, Greater London": "Barking",
    "Bassett's Ln, Ongar, Uk": "Ongar",
    "Slough": None,
    # South
    "Woolwich, Greater London": "Woolwich",
    "Hanworth, London": "Hanworth *",
    "Lewisham, London": "Lewisham",
    "Upper Norwood, London": "Upper Norwood",
    "Kingston Upon Thames, Greater London": "Kingston upon Thames",
    "Clapham, London": "Clapham",
    "Bexleyheath, Greater London": "Bexleyheath",
    "Wandsworth, London": "Wandsworth",
    "Peckham, London": "Peckham",
    "Greenwich, London": "Greenwich",
    "Tooting, London": "Tooting",
    "Purley, Greater London": "Purley",
    "Wimbledon, London": "Wimbledon",
    "Charlton, London": "Charlton",
    "Brixton, London": "Brixton",
    "Camberwell, London": "Camberwell",
    "Catford, London": "Catford",
    "New Cross, London": "New Cross",
    "Sutton, Greater London": "Sutton",
    "Croydon, Greater London": "Croydon",
    "Bromley, Greater London": "Bromley",
    "Bexley, Greater London": "Bexley",
    "Mitcham, London": "Mitcham",
    "Bermondsey, London": "Bermondsey",
    "Morden, London": "Morden",
    "Streatham, London": "Streatham",
    "Eltham, London": "Eltham",
    "Green Street Green, Bromley, Greater London": "Green St Green",
    "Deptford, London": "Deptford",
    "Balham, London": "Balham",
    "Earlsfield, London": "Earlsfield",
    "Herne Hill, London": "Herne Hill",
    "Sidcup, Greater London": "Sidcup",
    "East Dulwich, London": "East Dulwich",
    "Wimbledon, Greater London": None,
}

_data = json.load(open("coverage_areas.json"))
_missing = [x["area"] for x in _data if x["area"] not in DISPLAY]
assert not _missing, f"Unmapped areas: {_missing}"
_agg = {"South": {}, "North": {}}
for x in _data:
    disp = DISPLAY[x["area"]]
    if disp is None:
        continue
    slot = _agg[x["region"]].setdefault(disp, [0, 0])
    slot[0] += x["list30d"]
    slot[1] += x["phones_total"]
south_rows = sorted(([k, v[0], v[1]] for k, v in _agg["South"].items()), key=lambda r: -r[1])
north_rows = sorted(([k, v[0], v[1]] for k, v in _agg["North"].items()), key=lambda r: -r[1])
TOT_AREAS = len(south_rows) + len(north_rows)
TOT_LIST = sum(r[1] for r in south_rows + north_rows)
TOT_PH = sum(r[2] for r in south_rows + north_rows)

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Title"], fontSize=22, textColor=colors.white, alignment=TA_LEFT, leading=26, spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontSize=10.5, textColor=colors.HexColor("#c9d4de"), alignment=TA_LEFT)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13.5, textColor=NAVY, spaceBefore=14, spaceAfter=6)
BODY = ParagraphStyle("BODY", parent=styles["Normal"], fontSize=10.3, textColor=colors.HexColor("#2b3540"), leading=15)
SMALL = ParagraphStyle("SMALL", parent=styles["Normal"], fontSize=8.6, textColor=MGREY, leading=11)
CAP = ParagraphStyle("CAP", parent=styles["Normal"], fontSize=9.3, textColor=MGREY, leading=13, alignment=1)
CELL = ParagraphStyle("CELL", parent=styles["Normal"], fontSize=9.3, textColor=colors.HexColor("#2b3540"), leading=12)
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="Helvetica-Bold")

story = []

# ---------- Title bar ----------
tb = Table([[Paragraph("London Rental Coverage", H1)],
            [Paragraph("Areas covered, how we define the regions, and the expansion roadmap &nbsp;|&nbsp; September 2026", SUB)]],
           colWidths=[176*mm])
tb.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),NAVY),("LEFTPADDING",(0,0),(-1,-1),14),
                        ("RIGHTPADDING",(0,0),(-1,-1),14),("TOPPADDING",(0,0),(0,0),12),
                        ("BOTTOMPADDING",(0,0),(0,0),0),("TOPPADDING",(0,1),(0,1),0),("BOTTOMPADDING",(0,1),(-1,-1),12)]))
story += [tb, Spacer(1, 10)]

NUMST = ParagraphStyle("NUMST", parent=BODY, fontSize=19, leading=21, textColor=colors.white)
LBLST = ParagraphStyle("LBLST", parent=BODY, fontSize=8.4, leading=10, textColor=colors.white)
def card(num, label, col):
    return Table([[Paragraph(f'<b>{num}</b>', NUMST)],
                  [Paragraph(label, LBLST)]], colWidths=[42*mm],
                 style=TableStyle([("BACKGROUND",(0,0),(-1,-1),col),("LEFTPADDING",(0,0),(-1,-1),10),
                                   ("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(0,0),9),
                                   ("BOTTOMPADDING",(0,0),(0,0),4),("TOPPADDING",(0,1),(0,1),0),
                                   ("BOTTOMPADDING",(0,1),(0,1),10)]))
cards = Table([[card(str(TOT_AREAS),"Active areas (South + North + commuter belt)",NAVY),
                card(f"{len(south_rows)} / {len(north_rows)}","South areas / North areas",SOUTH),
                card(f"{(TOT_LIST//100)*100:,}+","New listings reached / month",NORTH),
                card(f"{(TOT_PH//100)*100:,}+","Landlord phone numbers captured",AMBER)]],
              colWidths=[44*mm]*4)
cards.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-2,-1),4),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
story += [cards, Spacer(1, 12)]

story += [Paragraph(
    "We run tenant outreach across Greater London and the surrounding commuter belt using a network of "
    "accounts, each searching a named area within roughly a 5&nbsp;km radius. Coverage is split into "
    "<b>South London</b> (boroughs south of the River Thames) and <b>North London &amp; the commuter belt</b> "
    "(everything north of the Thames, including the Home-Counties towns that ring the capital). "
    "The next page maps our current coverage; the area-by-area breakdown follows in the tables.", BODY)]
story += [Paragraph("How we define North vs. South", H2),
    Paragraph("The <b>River Thames is the North/South divider</b>: areas south of the river are South London, "
    "areas north of it are North London. The single exception is <b>Hanworth</b>, which we group with South "
    "London for operational reasons even though it sits just north of the river (marked with * on the map and "
    "tables). The <b>red outline is the Greater London administrative boundary &mdash; not the M25</b>; the two "
    "run close together but are not identical, so &lsquo;inside the M25&rsquo; and &lsquo;Greater London&rsquo; "
    "are not the same thing (several of our covered commuter towns lie between the two).", BODY)]
story += [Paragraph("Recently strengthened", H2),
    Paragraph("Alongside our established South London network and the commuter belt, we have brought a cluster of "
    "<b>North &amp; East London</b> boroughs into active coverage &mdash; including Hackney, Tottenham, Walthamstow, "
    "Wood Green, Enfield, Ealing and Ilford &mdash; materially widening reach north of the river.", BODY)]
story += [Spacer(1, 8), Paragraph("&#9656;&nbsp; See the full coverage map on the next page, "
    "with the area-by-area detail in the tables that follow.", SMALL)]

# ---------- Landscape map page ----------
story += [NextPageTemplate("L"), PageBreak()]
mimg = Image("coverage_map.png")
ratio = mimg.imageWidth / mimg.imageHeight
tgt_w = 262*mm
mimg.drawWidth = tgt_w
mimg.drawHeight = tgt_w / ratio
if mimg.drawHeight > 168*mm:
    mimg.drawHeight = 168*mm
    mimg.drawWidth = 168*mm * ratio
mimg.hAlign = "CENTER"
story += [mimg, Spacer(1, 3),
          Paragraph("Green = South London boroughs (covered) &nbsp;·&nbsp; Blue = North London boroughs &amp; "
                    "commuter-belt districts (covered) &nbsp;·&nbsp; Amber = expansion roadmap "
                    "(not yet covered) &nbsp;·&nbsp; Grey = not targeted &nbsp;·&nbsp; <b>Red outline = Greater "
                    "London, approx. (not the M25)</b> &nbsp;·&nbsp; Yellow outline = commuter belt &nbsp;·&nbsp; "
                    "Blue line = River Thames (North/South divider). &nbsp; * Hanworth is grouped with South London "
                    "though it lies just north of the Thames.", CAP)]

# ---------- Portrait: coverage tables ----------
story += [NextPageTemplate("P"), PageBreak()]

def cov_table(title, rows, header_col):
    data = [[Paragraph('<font color="white"><b>Area</b></font>', CELL),
             Paragraph('<font color="white"><b>New listings / month</b></font>', CELL),
             Paragraph('<font color="white"><b>Phone numbers captured</b></font>', CELL)]]
    for name, supply, leads in rows:
        data.append([Paragraph(name, CELLB), Paragraph(str(supply), CELL), Paragraph(str(leads), CELL)])
    t = Table(data, colWidths=[70*mm, 50*mm, 50*mm], repeatRows=1)
    st = [("BACKGROUND",(0,0),(-1,0),header_col),("LINEBELOW",(0,0),(-1,-1),0.4,colors.HexColor("#d5dbe1")),
          ("TOPPADDING",(0,0),(-1,-1),4.5),("BOTTOMPADDING",(0,0),(-1,-1),4.5),("LEFTPADDING",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"MIDDLE")]
    for i in range(1,len(data)):
        if i % 2 == 0: st.append(("BACKGROUND",(0,i),(-1,i),LGREY))
    t.setStyle(TableStyle(st))
    return [Paragraph(title, H2), t]

story += cov_table(f"Currently covering — South London  ({len(south_rows)} areas)", south_rows, SOUTH)
story += [Spacer(1,10)]
story += cov_table(f"Currently covering — North London &amp; commuter belt  ({len(north_rows)} areas)", north_rows, NORTH)
story += [Spacer(1,4), Paragraph("New listings / month = fresh listings reached in the last 30 days. "
    "Phone numbers captured = cumulative landlord mobile numbers acquired to date. "
    "* Hanworth is grouped with South London though it sits just north of the Thames.", SMALL)]

# ---------- Capacity / SIMs required for full focus-zone coverage ----------
story += [NextPageTemplate("P"), PageBreak()]
story += [Paragraph("Scaling to full coverage of the focus zone", H2),
    Paragraph("To cover <b>every</b> area inside the Greater London (red) and commuter-belt (yellow) focus zones, "
    "the fleet would need to scale roughly as shown below. Basis: one SIM sustains ~8 landlord contacts per day "
    "(&asymp;45 new listings / week). We currently run <b>14 SIMs</b>.", BODY), Spacer(1,4)]
def simrow(z, v, s, bold=False):
    st = CELLB if bold else CELL
    return [Paragraph(("<b>%s</b>" if bold else "%s") % z, CELLB),
            Paragraph(("<b>%s</b>" if bold else "%s") % v, st),
            Paragraph(("<b>%s</b>" if bold else "%s") % s, st)]
sim_data = [[Paragraph('<font color="white"><b>Zone</b></font>',CELL),
             Paragraph('<font color="white"><b>Est. new listings / week</b></font>',CELL),
             Paragraph('<font color="white"><b>SIMs for full coverage</b></font>',CELL)],
            simrow("Greater London (red zone)","~2,200","~50"),
            simrow("Commuter belt (yellow zone)","~1,300","~30"),
            simrow("Total focus zone","~3,500","~80", bold=True),
            simrow("Currently deployed","~14 SIMs","14")]
simt = Table(sim_data, colWidths=[70*mm,50*mm,50*mm])
sst=[("BACKGROUND",(0,0),(-1,0),NAVY),("BACKGROUND",(0,3),(-1,3),colors.HexColor("#dfeee7")),
     ("BACKGROUND",(0,4),(-1,4),LGREY),("LINEBELOW",(0,0),(-1,-1),0.4,colors.HexColor("#d5dbe1")),
     ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),("LEFTPADDING",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"MIDDLE")]
simt.setStyle(TableStyle(sst))
story += [simt, Spacer(1,4),
    Paragraph("Full coverage is a phased scale-up from today's <b>14 SIMs to ~80</b> &mdash; roughly 6&times; the "
    "current fleet. Figures are approximate; the commuter-belt estimate is the softest as several towns are not "
    "yet actively searched.", SMALL)]

story += [Paragraph("Not yet covered — expansion roadmap", H2),
    Paragraph("These areas sit inside the focus zones but are not yet covered &mdash; the priority runway as the "
    "fleet scales toward ~80 SIMs. Grouped by zone:", BODY), Spacer(1,4)]
exp = [("Greater London — North & East","Romford, Dagenham, Chingford, Woodford"),
       ("Greater London — West & Central","Fulham, Hammersmith, Brent, Harrow, Camden, Putney, Richmond, Uxbridge, Hayes, Kensington, Chelsea, Westminster"),
       ("Commuter belt — North","Luton, St Albans, Watford, Hemel Hempstead"),
       ("Commuter belt — East","Hertford, Broxbourne, Chelmsford, Basildon"),
       ("Commuter belt — West / SW","Slough, Maidenhead, Reading, Guildford, Woking")]
edata = [[Paragraph('<font color="white"><b>Zone</b></font>',CELL), Paragraph('<font color="white"><b>Priority areas (not yet covered)</b></font>',CELL)]]
for k,v in exp: edata.append([Paragraph(k,CELLB), Paragraph(v,CELL)])
et = Table(edata, colWidths=[52*mm,118*mm], repeatRows=1)
est=[("BACKGROUND",(0,0),(-1,0),AMBER),("LINEBELOW",(0,0),(-1,-1),0.4,colors.HexColor("#d5dbe1")),
     ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),("LEFTPADDING",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"MIDDLE")]
for i in range(1,len(edata)):
    if i%2==0: est.append(("BACKGROUND",(0,i),(-1,i),LGREY))
et.setStyle(TableStyle(est))
story += [et, Spacer(1,8),
    Paragraph("Every London borough is either covered or on the expansion roadmap. The only exception is the "
    "<b>City of London</b>, shown as not targeted: it is almost entirely commercial, with negligible residential "
    "rental stock.", SMALL)]

story += [Spacer(1,10), HRFlowable(width="100%", color=colors.HexColor("#d5dbe1")),
    Paragraph("Prepared September 2026. New-listing volumes are last-30-day counts; phone-number totals are "
    "cumulative landlord mobile numbers acquired. Coverage radius is approximate.", SMALL)]

# ---------- Document with portrait + landscape templates ----------
def on_portrait(canvas, doc): canvas.setPageSize(A4)
def on_landscape(canvas, doc): canvas.setPageSize(landscape(A4))
LW, LH = landscape(A4)
pP = PageTemplate(id="P", pagesize=A4, onPage=on_portrait,
                  frames=[Frame(17*mm, 12*mm, 176*mm, 273*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])
pL = PageTemplate(id="L", pagesize=landscape(A4), onPage=on_landscape,
                  frames=[Frame(12*mm, 10*mm, LW-24*mm, LH-20*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])
doc = BaseDocTemplate("London_Coverage_Client_Report.pdf", pagesize=A4, title="London Rental Coverage")
doc.addPageTemplates([pP, pL])
doc.build(story)
print(f"PDF written: London_Coverage_Client_Report.pdf | areas={TOT_AREAS} S={len(south_rows)} N={len(north_rows)} listings30d={TOT_LIST} phones={TOT_PH}")
