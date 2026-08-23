# -*- coding: utf-8 -*-
"""Assemble the client-facing London coverage PDF (map on its own landscape page)."""
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

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Title"], fontSize=22, textColor=colors.white, alignment=TA_LEFT, leading=26, spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontSize=10.5, textColor=colors.HexColor("#c9d4de"), alignment=TA_LEFT)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13.5, textColor=NAVY, spaceBefore=14, spaceAfter=6)
BODY = ParagraphStyle("BODY", parent=styles["Normal"], fontSize=10.3, textColor=colors.HexColor("#2b3540"), leading=15)
SMALL = ParagraphStyle("SMALL", parent=styles["Normal"], fontSize=8.6, textColor=MGREY, leading=11)
CAP = ParagraphStyle("CAP", parent=styles["Normal"], fontSize=9.5, textColor=MGREY, leading=13, alignment=1)
CELL = ParagraphStyle("CELL", parent=styles["Normal"], fontSize=9.3, textColor=colors.HexColor("#2b3540"), leading=12)
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="Helvetica-Bold")

story = []

# ---------- Title bar ----------
tb = Table([[Paragraph("London Rental Coverage", H1)],
            [Paragraph("Areas covered, recently expanded, and expansion roadmap &nbsp;|&nbsp; August 2026", SUB)]],
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
cards = Table([[card("28","Areas covered (South + commuter belt)",NAVY), card("18 / 10","South areas / North areas",SOUTH),
                card("5,000+","New listings reached / month",NORTH), card("1,000+","Landlord phone numbers captured",AMBER)]],
              colWidths=[44*mm]*4)
cards.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-2,-1),4),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
story += [cards, Spacer(1, 12)]

story += [Paragraph(
    "We run tenant outreach across London and its commuter belt using a network of accounts, each searching a "
    "named area within roughly a 5&nbsp;km radius. Coverage spans <b>South London</b> (the established South boroughs) "
    "and <b>North London</b> (the commuter-belt towns ringing the capital &mdash; our best-converting areas). "
    "The next page maps our coverage; the detailed area-by-area breakdown follows in the tables.", BODY)]
story += [Paragraph("Recently strengthened (August 2026)", H2),
    Paragraph("We recently re-focused several accounts onto our highest-value neighbourhoods: "
    "<b>Greenwich</b> and <b>Hanworth</b> (two of our strongest lead-generating areas) were given dedicated coverage, "
    "and the <b>Clapham / Wandsworth / Tooting</b> south-west corridor and <b>Peckham</b> were reinforced. "
    "The <b>North London commuter-belt</b> network &mdash; our highest-converting areas &mdash; remains fully active.", BODY)]
story += [Spacer(1, 10), Paragraph("&#9656;&nbsp; See the full coverage map on the next page, "
    "with the area-by-area detail in the tables that follow.", SMALL)]

# ---------- Landscape map page ----------
story += [NextPageTemplate("L"), PageBreak()]
mimg = Image("coverage_map.png")
ratio = mimg.imageWidth / mimg.imageHeight
tgt_w = 262*mm
mimg.drawWidth = tgt_w
mimg.drawHeight = tgt_w / ratio
if mimg.drawHeight > 170*mm:
    mimg.drawHeight = 170*mm
    mimg.drawWidth = 170*mm * ratio
mimg.hAlign = "CENTER"
story += [mimg, Spacer(1, 3),
          Paragraph("Green = South London boroughs (covered) &nbsp;·&nbsp; Blue = North London / commuter-belt districts (covered) "
                    "&nbsp;·&nbsp; Amber = expansion-roadmap boroughs &nbsp;·&nbsp; Grey = not targeted &nbsp;·&nbsp; "
                    "<b>Red / yellow outlines = the target focus zones</b> (Greater London / commuter belt)",
                    CAP)]

# ---------- Portrait: coverage tables ----------
story += [NextPageTemplate("P"), PageBreak()]

def cov_table(title, rows, header_col, leads_label="Phone numbers captured"):
    data = [[Paragraph('<font color="white"><b>Area</b></font>', CELL),
             Paragraph('<font color="white"><b>New listings / month</b></font>', CELL),
             Paragraph(f'<font color="white"><b>{leads_label}</b></font>', CELL)]]
    for name, supply, leads in rows:
        data.append([Paragraph(name, CELLB), Paragraph(str(supply), CELL), Paragraph(str(leads), CELL)])
    t = Table(data, colWidths=[70*mm, 50*mm, 50*mm], repeatRows=1)
    st = [("BACKGROUND",(0,0),(-1,0),header_col),("LINEBELOW",(0,0),(-1,-1),0.4,colors.HexColor("#d5dbe1")),
          ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),("LEFTPADDING",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"MIDDLE")]
    for i in range(1,len(data)):
        if i % 2 == 0: st.append(("BACKGROUND",(0,i),(-1,i),LGREY))
    t.setStyle(TableStyle(st))
    return [Paragraph(title, H2), t]

south_rows = [("Woolwich",782,22),("Hanworth (West)",682,107),("Greenwich",564,106),("Upper Norwood",562,100),
    ("Peckham",263,27),("Lewisham",211,87),("Wandsworth",209,29),("Tooting",146,19),("Kingston upon Thames",143,68),
    ("Clapham",141,8),("Bexleyheath",128,84),("Sutton",39,14),("Bexley",38,5),("Purley",36,12),("Croydon",28,3),
    ("Mitcham",15,11),("Green St Green",7,4),("Sidcup",3,3)]
north_rows = [("Brentwood",751,71),("Borehamwood",707,39),("Chigwell",595,59),("Harlow / Roydon",244,30),
    ("Welwyn",239,29),("Wooburn Green",204,31),("Berkhamsted",151,22),("Great Missenden",139,23),
    ("Epping",77,5),("Ongar",48,8)]
story += cov_table("Currently covering — South London (established boroughs)", south_rows, SOUTH)
story += [Spacer(1,10)]
story += cov_table("Currently covering — North London (commuter belt)", north_rows, NORTH)

# ---------- Capacity / SIMs required for full focus-zone coverage ----------
story += [Paragraph("Scaling to full coverage of the focus zone (red + yellow)", H2),
    Paragraph("To cover <b>every</b> area inside the red (Greater London) and yellow (commuter belt) focus zones, "
    "the fleet would need to scale roughly as shown below. Basis: one SIM sustains ~8 landlord contacts per day "
    "(&asymp;45 new listings / week). Our calibration point: South London (12 boroughs, ~760 listings/week) is "
    "covered by ~17 SIMs today.", BODY), Spacer(1,4)]
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
            simrow("Currently deployed","~720 capacity","16")]
simt = Table(sim_data, colWidths=[70*mm,50*mm,50*mm])
sst=[("BACKGROUND",(0,0),(-1,0),NAVY),("BACKGROUND",(0,3),(-1,3),colors.HexColor("#dfeee7")),
     ("BACKGROUND",(0,4),(-1,4),LGREY),("LINEBELOW",(0,0),(-1,-1),0.4,colors.HexColor("#d5dbe1")),
     ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),("LEFTPADDING",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"MIDDLE")]
simt.setStyle(TableStyle(sst))
story += [simt, Spacer(1,4),
    Paragraph("Full coverage is a phased scale-up from today's <b>16 SIMs to ~80</b> &mdash; roughly 5&times; the "
    "current fleet. Figures are approximate; the commuter-belt estimate is the softest as several towns are not "
    "yet actively searched.", SMALL)]

story += [Paragraph("Not yet covered — expansion roadmap (inside the focus zone)", H2),
    Paragraph("These areas sit inside the red / yellow focus zones but are not yet covered &mdash; the priority runway "
    "as the fleet scales from 16 toward ~80 SIMs. Grouped by zone:", BODY), Spacer(1,4)]
exp = [("Greater London — North & East","Wood Green, Tottenham, Stratford, Walthamstow, Hackney, Enfield, Ilford, Romford"),
       ("Greater London — West & Central","Ealing, Fulham, Hammersmith, Brent, Harrow, Islington, Camden"),
       ("Greater London — South gaps","Brixton, Streatham, Balham, Catford, New Cross, Putney, Wimbledon"),
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
story += [et]

story += [Spacer(1,10), HRFlowable(width="100%", color=colors.HexColor("#d5dbe1")),
    Paragraph("Prepared August 2026. Listing volumes are recent monthly averages; lead totals are cumulative "
    "landlord phone numbers acquired. Coverage radius is approximate.", SMALL)]

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
print("PDF written: London_Coverage_Client_Report.pdf")
