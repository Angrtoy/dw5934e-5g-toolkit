"""Verify the detachable U-base at either real short-end interface."""
from pathlib import Path
import trimesh, numpy as np, json, os
OUT=Path(__file__).resolve().parent/'output'
def load(n):return trimesh.load_mesh(OUT/(n+'.stl'),process=True)
def iv(a,b):
 q=trimesh.boolean.intersection([a,b],engine='manifold');return 0 if q is None else abs(float(q.volume))
def pose(m,sign):
 q=m.copy()
 if sign<0:q.apply_transform(trimesh.transformations.rotation_matrix(np.pi,[0,0,1]))
 return q
def cylx(r,l,x,y,z):
 q=trimesh.creation.cylinder(r,l,sections=24);q.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,[0,1,0]));q.apply_translation((x,y,z));return q
def hexx(flat,l,x,y,z):
 q=trimesh.creation.cylinder(flat/1.7320508,l,sections=6);q.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,[0,1,0]));q.apply_translation((x,y,z));return q
def loading_nut(x,y,z=-4.0):
 # Match the printable pocket's hex-flat orientation.  A standard hex nut can
 # be rotated to this orientation before insertion; the test volume remains a
 # real 5.5-AF x 2.4-mm hex, rather than a round proxy.
 q=hexx(5.5,2.4,x,y,z);q.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(30),[1,0,0],point=[x,y,z]));return q
def antenna_proxy(x,side):
 # Ø8 x 100 exterior-only assumed rod: -X is upright and Y is the side normal.
 direction=np.array([-np.sqrt(.5),side*np.sqrt(.5),0.])
 q=trimesh.creation.cylinder(4.,100.,sections=28)
 q.apply_transform(trimesh.geometry.align_vectors([0,0,1],direction))
 # Centre is 5 mm beyond the panel's outer plane, representing the external
 # connector shoulder before the assumed flexible rod begins.
 q.apply_translation(np.array([x,side*50.0,-3.5])+50*direction)
 return q
def main():
 base=load('dual_end_desk_base'); others={n:load(n) for n in ['main_chassis','front_bezel','rear_cover_no_sma','left_side_antenna_panel_4x1','right_side_antenna_panel_4x1','registered_source_top_feature_frame']};out={}
 for sign,key in [(1,'plus_x'),(-1,'minus_x')]:
  b=pose(base,sign);hits={n:iv(b,m) for n,m in others.items()}
  if max(hits.values())>.01:raise RuntimeError(f'{key} base interference {hits}')
  # Actual M3 x16 clamp chain: head seats in the main inner shoulder at X=±77,
  # Ø3 stem goes outward through chassis/base, then engages the base's captive nut.
  clamps=[]; captures=[]
  for y in (-25,25):
   head=cylx(2.75,3.0,sign*75.5,sign*y,-4.0)
   stem=cylx(1.50,16.0,sign*85.0,sign*y,-4.0)
   # Clearance, not material overlap, is correct for the physical screw.
   head_main=iv(head,others['main_chassis']); stem_main=iv(stem,others['main_chassis']); stem_base=iv(stem,b)
   if max(head_main,stem_main,stem_base)>.01:raise RuntimeError(f'{key} M3 clamp clearance failed y={y}: head/main={head_main}, stem/main={stem_main}, stem/base={stem_base}')
   # An outward 0.10mm displacement of the seated head must meet the shoulder.
   pushed=head.copy();pushed.apply_translation((sign*.10,0,0)); shoulder=iv(pushed,others['main_chassis'])
   if shoulder<.01:raise RuntimeError(f'{key} M3 head has no main-chassis seat y={y}')
   # The full head must travel in from the open central rear bay, below Z=0.
   arrival=[]
   for hx in np.arange(60.0,75.51,.25):
    q=cylx(2.75,3.0,sign*hx,sign*y,-4.0);v=iv(q,others['main_chassis'])
    if v>.01:raise RuntimeError(f'{key} M3 head insertion blocked y={y}, x={hx}: {v}')
    arrival.append(round(v,6))
   # The base, not just the chassis, supplies a true captive M3 nut feature.
   # Follow the selected end's outward-to-inward installation direction and
   # check every 0.25 mm position of an actual 5.5 AF x 2.4 mm nut volume.
   # Nut enters the exterior Y flank of this short support, then seats at Y=±25.
   ys=np.arange(43.0,24.99,-.25)*(1 if y>0 else -1)
   sweep=[]
   for yy in ys:
    q=pose(loading_nut(89.0,yy),sign)
    w=iv(q,b)
    if w>.01:raise RuntimeError(f'{key} base nut loading blocked y={y} at path y={yy}: {w}')
    sweep.append(round(w,6))
   seated=pose(loading_nut(89.0,y),sign)
   # At the installed 30-degree orientation the two adjacent flat orientations
   # (0 and 60 degrees) collide with the hex pocket, proving anti-rotation.
   turned=pose(hexx(5.5,2.4,89.0,y,-4.0),sign);locked=iv(turned,b)
   if locked<.01:raise RuntimeError(f'{key} base nut is not anti-rotation retained y={y}')
   engagement=iv(stem,seated)
   if engagement<.01:raise RuntimeError(f'{key} M3 stem does not reach base nut y={y}')
   clamps.append({'seat_y_mm':sign*y,'z_mm':-4.0,'m3x16_proxy':{'head_diameter_mm':5.5,'head_length_mm':3.0,'stem_diameter_mm':3.0,'stem_length_mm':16.0},'head_main_mm3':round(head_main,6),'stem_main_mm3':round(stem_main,6),'stem_base_mm3':round(stem_base,6),'head_outward_0_10_shoulder_block_mm3':round(shoulder,6),'head_arrival_samples':len(arrival),'head_arrival_max_mm3':max(arrival),'stem_nut_thread_engagement_proxy_mm3':round(engagement,6)})
   captures.append({'seat_y_mm':sign*y,'z_mm':-4.0,'nut_af_mm':5.5,'nut_thickness_mm':2.4,'load_axis':'Y','load_y_mm':[sign*43,sign*25],'samples':len(sweep),'sweep_max_mm3':max(sweep),'rotation30_block_mm3':round(locked,6)})
  antenna_checks=[]
  antenna_targets={'base':b,**others}
  for side in (-1,1):
   for x in (-51.,-17.,17.,51.):
    rod=antenna_proxy(x,side);hits_rod={n:iv(rod,solid) for n,solid in antenna_targets.items()}
    for n,v in hits_rod.items():
     if v>.01:raise RuntimeError(f'{key} antenna proxy conflicts {side}/{x}/{n}: {v}')
    antenna_checks.append({'side_y':side*45,'x':x,'diameter_mm':8,'length_mm':100,'direction':np.round([-np.sqrt(.5),side*np.sqrt(.5),0],5).tolist(),'intersections_mm3':{n:round(v,6) for n,v in hits_rod.items()}})
  # The only source short-end aperture identified from mesh evidence is at -X.
  # In that reversed-base pose, a conservative 30 x 8 x 3-mm plug/cable prism
  # travels from outside, through the base's central U opening to the original
  # 9 x 4-mm source opening without touching either solid.
  port_check=None
  if sign < 0:
   plug=trimesh.creation.box((30,8,3),transform=trimesh.transformations.translation_matrix((-90,0,10)))
   port_check={'prism_mm':[30,8,3],'main_chassis_mm3':round(iv(plug,others['main_chassis']),6),'base_mm3':round(iv(plug,b),6)}
   if max(port_check['main_chassis_mm3'],port_check['base_mm3'])>.01:raise RuntimeError(f'{key} source end-port path is blocked: {port_check}')
  # Body YZ projection (Y±45, Z=-10..29.6) lies inside 100x85 foot support.
  # This is a footprint containment calculation, not a claim about the unknown
  # battery/antenna centre of mass.  The actual body YZ envelope lies within
  # the actual YZ foot contact rectangle after the central U-cut.
  bb=b.bounds; projection=bool(bb[0,1] <= -45 and bb[1,1] >= 45 and bb[0,2] <= -10 and bb[1,2] >= 29.6)
  if not projection:raise RuntimeError(f'{key} body YZ projection exceeds foot: {bb}')
  out[key]={'transform':('native +X lower-end pose' if sign>0 else 'rotate Z=180 for −X lower-end pose'),'base_bounds_mm':np.round(b.bounds,3).tolist(),'intersections_mm3':{n:round(v,6) for n,v in hits.items()},'m3_clamp_chain':clamps,'base_captive_m3_nut_loading':captures,'central_cable_channel_mm':[28,25,10],'source_minus_x_port_cable_path':port_check,'body_projection_inside_foot_yz':projection,'antenna_occupancy_assumption':antenna_checks}
 p=json.load(open(OUT/'cad_validation.json',encoding='utf8'));p['dual_end_base']=out;open(OUT/'cad_validation.json','w',encoding='utf8').write(json.dumps(p,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False),flush=True);os._exit(0)
if __name__=='__main__':main()
