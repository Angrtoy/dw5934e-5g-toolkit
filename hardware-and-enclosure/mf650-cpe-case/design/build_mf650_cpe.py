"""Registered-source MF650 thick CPE conversion, all dimensions in mm.

Coordinate convention is source-native: X width, Z height, +Y is the source
screen/button side.  The source top is registered by (0, +16.7, 0), not used
at its STEP file origin.  This creates a 37.9-mm envelope (-10..27.9 Y) around
the correctly assembled 17.9-mm source shell: nominally 10 mm at each end.
"""
from __future__ import annotations
import json, os, math
from pathlib import Path
import cadquery as cq
from cadquery import exporters, importers

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "output_v3"
P = {"revision":"v3_rounded_vented","units":"mm","source_assembly_y":[0.0,17.9],
 "source_top_translate_y":16.7,"source_button_translate":[40.405,14.9,0.0],
 "case_y":[-10.0,27.9],"outer_x":160.0,"outer_z":90.0,"wall":2.5,"min_web":2.5,
 "screen_center":[4.475,0.0],"screen_open":[40.5,30.8],"button_center":[40.405,0.0],
 "button_release_gap":0.30,"button_digital_press":0.30,
 "front_vent_count":63,"front_vent_diameter":3.0,"front_vent_pitch":5.5,"rear_vent_count":8,"rear_vent_length":10.0,"rear_vent_width":3.4,
 "sma_diameter":6.6,"sma_panel_thickness":2.4,
 "sma_centers":[[-33,-11],[-11,-11],[11,-11],[33,-11],[-33,11],[-11,11],[11,11],[33,11]],
 "m3_clearance":3.3,"m3_nut_flat":5.7,"panel_bolts":[[-67,-40],[-67,40],[67,-40],[67,40]],
 "base_bolts":[[-42,8],[42,8]],
 "preserved_left_opening":{"x":[-74.75,-73.25],"y":[8.2,11.8],"z":[-4.8,4.8]}}

def box(x,y,z,*,y0=0,x0=0,z0=0): return cq.Workplane("XY").box(x,y,z,centered=(True,False,True)).translate((x0,y0,z0))
def yc(r,l,x,y,z): return cq.Solid.makeCylinder(r,l,cq.Vector(x,y,z),cq.Vector(0,1,0))
def xc(r,l,x,y,z): return cq.Solid.makeCylinder(r,l,cq.Vector(x,y,z),cq.Vector(1,0,0))
def zc(r,l,x,y,z): return cq.Solid.makeCylinder(r,l,cq.Vector(x,y,z),cq.Vector(0,0,1))
def rounded(x,y,z,*,y0,r=8): return box(x,y,z,y0=y0).edges("|Y").fillet(r)
def hex_y(flat,l,x,y,z): return cq.Workplane("XZ",origin=(x,y,z)).polygon(6,flat/.8660254).extrude(l).val()
def hex_z(flat,l,x,y,z): return cq.Workplane("XY",origin=(x,y,z)).polygon(6,flat/.8660254).extrude(l).val()
def wp(shape): return cq.Workplane("XY").newObject([shape])

def capsule_cut(x,z,length,width,angle,y0):
    """Round-ended through slot, made locally then rotated about its own centre."""
    straight=length-width; r=width/2
    s=box(width,5,straight,y0=0).val().fuse(yc(r,5,0,0,-straight/2)).fuse(yc(r,5,0,0,straight/2))
    return wp(s).rotate((0,0,0),(0,1,0),angle).translate((x,y0,z))

def source_bottom_frame():
    """Imported source bottom. Only central rear service aperture is removed.

    The 120x4.2x52 aperture remains 14.75 mm away from either source side;
    it cannot touch the measured left-side feature at Y=8.2..11.8.
    """
    s=importers.importStep(str(ROOT/"source_downloads"/"底壳.STEP"))
    return s.cut(box(120,4.2,52,y0=-.1))

def source_top_feature_frame():
    """Keep the registered perimeter and actual D6 button-capture island.

    A broad central subtraction opens the extra +Y bay to the original cavity.
    The source perimeter feature band remains untouched. The local button island
    is deliberately retained so source button D7 stop / D5.7 stem geometry is
    still captured by actual source geometry, rather than a guessed button hole.
    """
    t=importers.importStep(str(ROOT/"source_downloads"/"上盖.STEP")).translate((0,16.7,0))
    rim=t.cut(box(130,7,58,y0=12.6))
    button_island=t.intersect(box(14,7,14,y0=12.6,x0=40.405))
    screen_rim=t.intersect(box(48,7,38,y0=12.6,x0=4.475))
    # Two narrow upper bridges make the retained screen island one printable
    # part with the perimeter; a lateral bridge joins the button capture island.
    # They stay outside the clear screen opening and D6 button bore.
    bridges=box(6,5.2,12,y0=12.7,x0=-10,z0=24.5).union(box(6,5.2,12,y0=12.7,x0=15,z0=24.5))
    bridges=bridges.union(box(12,5.2,6,y0=12.7,x0=31,z0=0))
    return rim.union(button_island).union(screen_rim).union(bridges)

def chassis():
    # Rails sit just outside source +/-74.75 X and +/-35.75 Z envelope.
    body=rounded(160,32.0,90,y0=-7.5).cut(box(150,34,72,y0=-8))
    # This overlaps all three measured intervals of original left opening.
    body=body.cut(box(14,3.6,9.6,y0=8.2,x0=-79))
    # Z-long-edge antenna-panel apertures sit in the rear added bay.  They are
    # cut from added chassis material before the preserved source bottom joins.
    for z in (-45.0,45.0): body=body.cut(box(130.0,8.0,20.0,y0=-8.0,z0=z))
    for x,z in P["panel_bolts"]:
        for y in (-4.0,21.0):
            # Front trap opens toward -Y central cavity; rear trap opens toward
            # +Y central cavity.  The sign is intentional and gives a real
            # nut-loading path rather than a blind decorative hexagon.
            # XZ workplane has -Y normal: these start values put the actual
            # 2.5-mm trap inside the post, open to the central cavity.
            trap=hex_y(P["m3_nut_flat"],2.5,x,23.5,z) if y>0 else hex_y(P["m3_nut_flat"],2.5,x,-.5,z)
            bore=yc(P["m3_clearance"]/2,4,x,y-.2,z)
            post=yc(4.5,3.5,x,y,z)
            # Cut after union as well: at Z=+/-40 the post joins the existing
            # rail, so only a global subtraction creates a real nut cavity.
            body=body.union(wp(post)).cut(wp(trap)).cut(wp(bore))
            # A 6.2-mm-wide Z-directed loading throat joins each trap to the
            # central cavity.  It is wide enough for the M3 nut to enter but
            # preserves the trap's Y-side retention faces; it also prevents a
            # sealed internal void / disconnected STL inner shell.
            throat=box(6.2,2.7,3.2,y0=20.9 if y>0 else -3.05,x0=x,z0=36.0 if z>0 else -36.0)
            body=body.cut(throat)
            # At Z=+/-40 the post overlaps the continuous upper/lower rail
            # directly; it is one solid with the chassis and lies outside the
            # source-top-frame +/-34.225 mm extraction sweep envelope.
    for x,y in P["base_bolts"]:
        tab=box(12,12,6,y0=y-6,x0=x,z0=-43.5).cut(hex_z(P["m3_nut_flat"],2.5,x,y,-46.5)).cut(zc(P["m3_clearance"]/2,8,x,y,-48))
        body=body.union(tab)
    # Four short bridges join the preserved source side rails to this chassis.
    # They sit on unperforated outer-rim material at Z=+/-30, away from the
    # left access opening and source locator/interface band.  This makes the
    # printed functional frame and main chassis one axial-location component.
    frame=source_bottom_frame()
    bridges=None
    for x in (-75.0,75.0):
        for z in (-30.0,30.0):
            q=box(2.4,4.0,6.0,y0=4.0,x0=x,z0=z)
            bridges=q if bridges is None else bridges.union(q)
    combined=body.union(frame).union(bridges)
    # Repeat only the Z=+/-45 added-material apertures after all chassis tabs
    # are present; source geometry is far inside Z=+/-35.75 and unaffected.
    for z in (-45.0,45.0): combined=combined.cut(box(130.0,8.0,20.0,y0=-8.0,z0=z))
    return combined

def front_bezel():
    # Continuous corner radii replace the v2 cut corners.  R5 is the largest
    # safe plan radius at fixed M3 x=+/-67,z=+/-40; a 0.8-mm face fillet gives
    # the visible soft perimeter transition without rounding the screw bores.
    b=rounded(160,3,90,y0=24.9,r=5).edges(">Y").fillet(.8)
    b=b.cut(box(40.5,5,30.8,y0=23.9,x0=4.475)).cut(yc(3.3,5,40.405,23.9,0))
    for x,z in P["panel_bolts"]: b=b.cut(yc(1.65,5,x,23.9,z))
    # Main heat field: 7x9 regular D3.0 array over the negative-X side of the
    # source central opening.  It deliberately sits opposite the display/button
    # and inside |X|<65, |Z|<29, so every hole runs into the actual cavity.
    for x in (-60.5,-55.0,-49.5,-44.0,-38.5,-33.0,-27.5):
        for z in (-22.0,-16.5,-11.0,-5.5,0.0,5.5,11.0,16.5,22.0):
            b=b.cut(yc(1.5,5,x,23.9,z))
    guide=yc(3.5,3.2,40.405,21.8,0).cut(yc(2.65,3.5,40.405,21.7,0))
    b=b.union(wp(guide))
    # Four removable-front compression feet land on solid top-frame perimeter
    # rails at x=+/-55,z=+/-31.  Their Y=18.2 face gives 0.30-mm assembly
    # clearance above source-top Y=17.9; once the front bolts are tight, it
    # prevents +Y migration without touching the display or button islands.
    for x in (-55.0,55.0):
        for z in (-31.0,31.0): b=b.union(box(8.0,6.7,6.0,y0=18.2,x0=x,z0=z))
    return b

def rear_panel():
    # Same R5 plan treatment and a small face-edge soften as the front panel.
    b=rounded(144,2.4,88,y0=-10,r=5).edges("<Y").fillet(.8)
    # v3 rear service/vent cover deliberately has no SMA bores; all eight SMA
    # locations moved to the real left/right side planes.
    for x,z in P["panel_bolts"]: b=b.cut(yc(1.65,5,x,-11,z))
    # Two side banks remain inside the 120x52 source rear service aperture
    # (|X|<60, |Z|<26), giving a genuine rear-bay -> original-cavity route.
    for x in (-52,52):
        for z in (-18,-6,6,18): b=b.cut(capsule_cut(x,z,10,3.4,18 if x<0 else -18,-11))
    return b

def long_edge_antenna_panel(side):
    """Flush upper/lower long-edge panel; SMA axes are Z, tails start in rear bay."""
    z0=43.8 if side>0 else -43.8
    p=box(130.0,7.0,2.4,y0=-7.5,z0=z0).edges("|Z").fillet(3.0)
    start=40.0 if side>0 else -46.0
    direction=1 if side>0 else 1
    for x in (-51.0,-17.0,17.0,51.0): p=p.cut(zc(3.3,8,x,-4.0,start))
    for x in (-63.0,63.0): p=p.cut(zc(1.65,8,x,-4.0,start))
    return p

def button_extender():
    # D5.7 source stem ends at global Y=19.2. The rear 5.6-mm contact pad gives
    # a shallow axial touch; the 4.6-mm shaft has 0.35-mm radial guide clearance.
    # 0.30 mm is a printable initial release gap from source-button Y=19.2;
    # a digital 0.30-mm press reaches surface contact without solid overlap.
    contact=yc(2.8,.35,40.405,19.5,0); shaft=yc(2.3,5.45,40.405,19.85,0); cap=yc(3.0,1.2,40.405,25.3,0)
    return wp(contact.fuse(shaft).fuse(cap))

def base():
    b=rounded(118,42,7,y0=-1.5,r=3).translate((0,0,-50))
    b=b.cut(box(104,28,2.2,y0=5.5,z0=-47.0))
    for x,y in P["base_bolts"]: b=b.cut(zc(1.65,12,x,y,-55))
    return b

def info(s):
    bb=s.BoundingBox(); return {"cad_valid":True,"volume_mm3":round(s.Volume(),3),"bounds_mm":[round(x,3) for x in (bb.xmin,bb.xmax,bb.ymin,bb.ymax,bb.zmin,bb.zmax)]}

def main():
    OUT.mkdir(exist_ok=True)
    # Scope-limited cleanup: output contains only this project's prior generated files.
    for f in OUT.iterdir():
        if f.is_file() and f.suffix.lower() in {".step",".stl",".png",".json"}: f.unlink()
    models={"source_top_feature_frame":source_top_feature_frame(),"main_chassis":chassis(),"front_bezel":front_bezel(),"rear_service_cover":rear_panel(),"lower_antenna_panel_4x1":long_edge_antenna_panel(-1),"upper_antenna_panel_4x1":long_edge_antenna_panel(1),"button_extender":button_extender(),"desk_base_optional":base()}
    rec={}
    for n,m in models.items():
        s=m.val()
        if not s.isValid() or s.Volume()<=0: raise RuntimeError(f"invalid solid {n}")
        exporters.export(m,str(OUT/f"{n}.step")); exporters.export(m,str(OUT/f"{n}.stl"),tolerance=.08,angularTolerance=.10)
        rr=importers.importStep(str(OUT/f"{n}.step")).val()
        if not rr.isValid(): raise RuntimeError(f"step reimport failed {n}")
        rec[n]=info(s)|{"reopened_step_valid":True}
    report={"revision":P["revision"],"parameters":P,"parts":rec,
      "source_registration":{"top_translation":[0,16.7,0],"top_y_after":[12.7,17.9],"button_translation":[40.405,14.9,0],"button_geometry":"D7 stop Y=14.9..16.7, D5.7 stem Y=16.7..19.2; source D6 hole captures stop/stem with zero B-rep overlap"},
      "internal_space":{"total_case_y":[-10,27.9],"registered_source_y":[0,17.9],"front_extra_y":[17.9,24.9],"rear_extra_y":[-7.6,0],"connected_path":"front grille -> +Y bay -> source-top central opening -> original cavity -> source-bottom central rear aperture -> -Y bay -> rear vents","local_vs_global":"The source top is locally retained only as perimeter, screen rim and button-capture islands; it is not a full blocking cover."},
      "fasteners":{"hardware":"M3 bolts through 3.3-mm holes plus ordinary M3 hex nuts in 5.7-mm flats / 2.5-mm-deep traps","front":"four exterior bolts; insert nuts from central cavity before front bezel","rear":"four exterior bolts; insert nuts from central cavity before rear panel","base":"two underside bolts; insert chassis-tab nuts before source frame"},
      "limits":["Confirm actual SMA shank/nut/cable dimensions with supplied fit coupon.","PCB switch travel/force, physical fit, power/thermal and RF performance are not validated."]}
    (OUT/"cad_validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True); os._exit(0)
if __name__=="__main__": main()
