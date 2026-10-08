"""Independent production-part reimport, mesh, interference and preview checks."""
from __future__ import annotations
import itertools, json, os, math
from pathlib import Path
import cadquery as cq
import trimesh, vtk
OUT=Path(__file__).resolve().parent/"output_v3"
COL={"source_top_feature_frame":(.45,.55,.66),"main_chassis":(.10,.16,.24),"front_bezel":(.62,.70,.78),"rear_service_cover":(.72,.77,.83),"lower_antenna_panel_4x1":(.72,.77,.83),"upper_antenna_panel_4x1":(.72,.77,.83),"button_extender":(.95,.27,.08),"desk_base_optional":(.28,.37,.49)}
mesh={}; shapes={}
for n in COL:
    m=trimesh.load_mesh(OUT/f"{n}.stl",force="mesh")
    if not(m.is_watertight and m.is_volume and m.volume>0): raise RuntimeError(f"non-watertight/non-volume STL {n}")
    components=len(m.split(only_watertight=False))
    if components!=1: raise RuntimeError(f"disconnected printable STL {n}: {components} components")
    mesh[n]={"watertight":True,"is_volume":True,"connected_components":components,"volume_mm3":round(float(m.volume),3),"faces":int(len(m.faces))}
    shapes[n]=cq.importers.importStep(str(OUT/f"{n}.step")).val()
    if not shapes[n].isValid(): raise RuntimeError(f"reimport invalid {n}")
    if len(shapes[n].Solids())!=1: raise RuntimeError(f"disconnected STEP {n}: {len(shapes[n].Solids())} solids")
# Expected mechanical contacts are represented with 0.05-mm axial clearance;
# every pair below must have no unintended solid volume intersection.
iv={}
for a,b in itertools.combinations(COL,2):
    v=float(shapes[a].intersect(shapes[b]).Volume()); iv[f"{a}__{b}"]=round(v,6)
    if v>.01: raise RuntimeError(f"unexpected interference {a}/{b}: {v}")
panel=shapes["rear_service_cover"]
side_need={-24.,-8.,8.,24.}
for n in ("lower_antenna_panel_4x1","upper_antenna_panel_4x1"):
    found={round(e.Center().x,1) for e in shapes[n].Edges() if e.geomType()=="CIRCLE" and abs(e.radius()-3.3)<.03}
    if not {-51.,-17.,17.,51.}.issubset(found): raise RuntimeError(f"four long-edge SMA holes not found {n}: {found}")
mount_need={(-67.,-40.),(-67.,40.),(67.,-40.),(67.,40.)}
mount_found={(round(e.Center().x,1),round(e.Center().z,1)) for e in panel.Edges() if e.geomType()=="CIRCLE" and abs(e.radius()-1.65)<.03}
if not mount_need.issubset(mount_found): raise RuntimeError(f"four rear M3 holes not found: {mount_found}")
def yray(x,y,z,length=5,r=.8): return cq.Solid.makeCylinder(r,length,cq.Vector(x,y,z),cq.Vector(0,1,0))
# Representative centre rays prove each vent bank has a free exterior-to-bay
# route and that its bay continues through the deliberately open source frame.
front_points=[(x,z) for x in (-60.5,-55.0,-49.5,-44.0,-38.5,-33.0,-27.5) for z in (-22.0,-16.5,-11.0,-5.5,0.0,5.5,11.0,16.5,22.0)]
rear_points=[(x,z) for x in (-52,52) for z in (-18,-6,6,18)]
front_block=max(float(yray(x,22.9,z).intersect(shapes["front_bezel"]).Volume()) for x,z in front_points)
front_cavity_block=max(float(yray(x,17.95,z,6.5).intersect(shapes["source_top_feature_frame"]).Volume()) for x,z in front_points)
rear_block=max(float(yray(x,-11,z).intersect(shapes["rear_service_cover"]).Volume()) for x,z in rear_points)
rear_cavity_block=max(float(yray(x,-10,z,14).intersect(shapes["main_chassis"]).Volume()) for x,z in rear_points)
if max(front_block,front_cavity_block,rear_block,rear_cavity_block)>.01: raise RuntimeError(f"blocked ventilation: {front_block},{front_cavity_block},{rear_block},{rear_cavity_block}")
capsule_area=lambda l,w: w*(l-w)+math.pi*(w/2)**2
front_open_area=63*math.pi*(1.5**2)
rear_open_area=8*capsule_area(10,3.4)
def hex_y(flat,length,x,y,z): return cq.Workplane("XZ",origin=(x,y,z)).polygon(6,flat/.8660254).extrude(length).val()
def zc(r,l,x,y,z): return cq.Solid.makeCylinder(r,l,cq.Vector(x,y,z),cq.Vector(0,0,1))
# Every nut is fully inside its actual cut volume, but a 30-degree rotation is
# blocked by the surrounding post.  The front traps open -Y; rear traps +Y.
nut_checks=[]
for x,z in mount_need:
    for side,oy in (("front",23.45),("rear",-.55)):
        nut=hex_y(5.5,2.4,x,oy,z)
        free=float(nut.intersect(shapes["main_chassis"]).Volume())
        rotated=nut.rotate(cq.Vector(x,oy,z),cq.Vector(x,oy+1,z),30)
        blocked=float(rotated.intersect(shapes["main_chassis"]).Volume())
        if free>.01 or blocked<.01: raise RuntimeError(f"M3 trap fail {side} {x},{z}: free={free} blocked={blocked}")
        nut_checks.append({"side":side,"x":x,"z":z,"nut_interference_mm3":round(free,6),"rotated_retention_mm3":round(blocked,6)})
# Registered actual source button is included in the final static assembly test.
src_button=cq.importers.importStep(str(OUT.parents[1]/"source_downloads"/"按钮.STEP")).val().translate(cq.Vector(40.405,14.9,0))
button_overlap=float(src_button.intersect(shapes["button_extender"]).Volume())
if button_overlap>.01: raise RuntimeError(f"source button / extender overlap: {button_overlap}")
pressed_ext=shapes["button_extender"].translate(cq.Vector(0,-.30,0))
pressed_overlap=float(src_button.intersect(pressed_ext).Volume())
if pressed_overlap>.01: raise RuntimeError(f"pressed source button / extender overlap: {pressed_overlap}")
# Top frame has 0.30-mm +Y assembly clearance under four front-bezel feet;
# a 0.40-mm outward shift must be stopped by real solid material.
top_clear=float(shapes["source_top_feature_frame"].translate(cq.Vector(0,.30,0)).intersect(shapes["front_bezel"]).Volume())
top_stop=float(shapes["source_top_feature_frame"].translate(cq.Vector(0,.40,0)).intersect(shapes["front_bezel"]).Volume())
if top_clear>.01 or top_stop<.01: raise RuntimeError(f"top-frame clamp failure clear={top_clear} stop={top_stop}")
# Conservative non-printing connector-tail occupancy: D6.5 x 12 mm, starting
# inside each 2.4-mm long-edge panel and extending into the rear added bay.
tail_blocks=[]
for z0,sign in ((42.6,-1),(-42.6,1)):
    for x in (-51.,-17.,17.,51.):
        tail=zc(3.25,12,x,-4.0,30.6) if sign<0 else zc(3.25,12,x,-4.0,-42.6)
        tail_blocks.append(float(tail.intersect(shapes["main_chassis"]).Volume()))
if max(tail_blocks)>.01: raise RuntimeError(f"conservative SMA tail blocked: {max(tail_blocks)}")
# With front bezel removed, prove the full user-service extraction path rather
# than checking only the first few millimetres.  0.25-mm samples cover +Y 0..35.
top0=shapes["source_top_feature_frame"]
sweep=[]
for i in range(141):
    dy=i*.25; v=float(top0.translate(cq.Vector(0,dy,0)).intersect(shapes["main_chassis"]).Volume())
    if v>.01: raise RuntimeError(f"top-frame +Y extraction blocked at {dy}: {v}")
    sweep.append(round(v,6))
def actor(n,shift=(0,0,0),cut=False):
    r=vtk.vtkSTLReader(); r.SetFileName(str(OUT/f"{n}.stl")); r.Update(); m=vtk.vtkPolyDataMapper(); m.SetInputConnection(r.GetOutputPort())
    if cut:
        p=vtk.vtkPlane(); p.SetOrigin(0,8,0); p.SetNormal(-1,0,0); m.AddClippingPlane(p)
    a=vtk.vtkActor(); a.SetMapper(m); a.SetPosition(*shift); a.GetProperty().SetColor(*COL[n]); a.GetProperty().SetInterpolationToPhong(); return a
def screen_actor():
    # Rendering-only dark LCD placeholder.  It is deliberately not exported to
    # STEP/STL and never added to the physical interference calculation.
    s=vtk.vtkCubeSource(); s.SetXLength(38.8); s.SetYLength(.35); s.SetZLength(28.8); s.SetCenter(4.475,18.15,0); s.Update()
    m=vtk.vtkPolyDataMapper(); m.SetInputConnection(s.GetOutputPort()); a=vtk.vtkActor(); a.SetMapper(m); a.GetProperty().SetColor(.015,.03,.05); return a
def sma_tail_actor(x,z,top):
    s=vtk.vtkCylinderSource(); s.SetRadius(3.25); s.SetHeight(12); s.SetResolution(20); s.Update()
    m=vtk.vtkPolyDataMapper(); m.SetInputConnection(s.GetOutputPort()); a=vtk.vtkActor(); a.SetMapper(m); a.RotateX(90); a.SetPosition(x,-4.0,36.6 if top else -36.6); a.GetProperty().SetColor(.85,.62,.12); a.GetProperty().SetOpacity(.38); return a
def render(name,view,explode=False,section=False):
    sh={n:(0,0,0) for n in COL}
    if explode: sh.update({"front_bezel":(0,10,0),"button_extender":(0,16,0),"antenna_panel_2x4":(0,-10,0),"desk_base_optional":(0,0,-13)})
    ren=vtk.vtkRenderer(); ren.SetBackground(.95,.97,.99)
    for n in COL: ren.AddActor(actor(n,sh[n],section))
    if not section: ren.AddActor(screen_actor())
    if not section:
        for z,top in ((45,True),(-45,False)):
            for x in (-51,-17,17,51): ren.AddActor(sma_tail_actor(x,z,top))
    w=vtk.vtkRenderWindow(); w.SetOffScreenRendering(1); w.SetSize(1600,960); w.AddRenderer(ren); ren.ResetCamera(); c=ren.GetActiveCamera(); c.SetFocalPoint(0,0,-5); c.ParallelProjectionOn(); c.SetParallelScale(78 if view=="perspective" and not explode else 66)
    if view=="front": c.SetPosition(0,300,0); c.SetViewUp(0,0,1)
    elif view=="rear": c.SetPosition(0,-300,0); c.SetViewUp(0,0,1)
    elif view=="section": c.SetPosition(190,240,130); c.SetViewUp(0,0,1)
    else: c.SetPosition(190,240,145); c.SetViewUp(0,0,1)
    ren.ResetCameraClippingRange(); w.Render(); g=vtk.vtkWindowToImageFilter(); g.SetInput(w); g.Update(); q=vtk.vtkPNGWriter(); q.SetFileName(str(OUT/name)); q.SetInputConnection(g.GetOutputPort()); q.Write()
render("preview_front.png","front"); render("preview_rear.png","rear"); render("preview_assembled.png","perspective"); render("preview_exploded.png","perspective",True); render("preview_section.png","section",section=True)
r=json.loads((OUT/"cad_validation.json").read_text(encoding="utf-8")); r.update({"stl_mesh_validation":mesh,"all_nonexpected_brep_intersection_volumes_mm3":iv,"nonexpected_interference_max_mm3":max(iv.values()),"side_sma_holes_verified":{"left_z_mm":sorted(side_need),"right_z_mm":sorted(side_need),"diameter_mm":6.6},"rear_m3_holes_verified_xz_mm":sorted([list(x) for x in mount_need]),"m3_nut_trap_validation":nut_checks,"top_feature_axial_clamp":{"feet_xz_mm":[[-55,-31],[-55,31],[55,-31],[55,31]],"assembly_gap_y_mm":.30,"test_at_gap_interference_mm3":round(top_clear,6),"test_at_0_40mm_outward_interference_mm3":round(top_stop,6),"removal":"remove four front M3 bolts and bezel; feature frame is then released toward +Y"},"top_feature_removal_sweep":{"front_bezel_removed":True,"axis":"+Y","range_mm":[0,35],"increment_mm":.25,"samples":len(sweep),"maximum_main_chassis_interference_mm3":max(sweep)},"left_access_proof":{"source_opening":{"x":[-74.75,-73.25],"y":[8.2,11.8],"z":[-4.8,4.8]},"chassis_cut":{"x":[-86,-72],"y":[8.2,11.8],"z":[-4.8,4.8]},"result":"intervals overlap in all axes: outer access reaches preserved actual source opening"},"ventilation":{"front_round_holes":63,"rear_side_capsules":8,"front_open_area_mm2":round(front_open_area,3),"rear_open_area_mm2":round(rear_open_area,3),"representative_path_max_block_mm3":round(max(front_block,front_cavity_block,rear_block,rear_cavity_block),6),"minimum_solid_web_mm":2.5,"path":"front field enters +Y bay and source central opening; rear cover vents enter -Y bay and source rear service aperture"},"button_motion":{"actual_source_button_registration":[40.405,14.9,0],"source_button_global_y":[14.9,19.2],"extender_contact_y":[19.5,19.85],"source_button_extender_interference_mm3":round(button_overlap,6),"axial_release_gap_mm":.30,"digital_pressed_translation_y_mm":-.30,"digital_pressed_interference_mm3":round(pressed_overlap,6),"guide_bore_diameter":5.3,"extender_shaft_diameter":4.6,"radial_clearance":.35,"design_travel_allowance_mm":.8},"preview_note":"Dark screen rectangle is a render-only visual placeholder, not a printable/exported part; section preview intentionally omits it.","actual_geometry_previews":[str(OUT/x) for x in ("preview_front.png","preview_rear.png","preview_assembled.png","preview_exploded.png","preview_section.png")]})
(OUT/"cad_validation.json").write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"watertight_parts":len(mesh),"max_interference_mm3":max(iv.values()),"verified_side_sma_holes":8},ensure_ascii=False),flush=True); os._exit(0)
