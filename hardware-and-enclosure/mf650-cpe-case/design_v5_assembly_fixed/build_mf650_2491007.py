"""MF650 / MakerWorld 2491007 derived printable enclosure.

All generated parts use X=long axis, Y=width, Z=thickness (mm).  This file
deliberately keeps the supplied STL as mesh geometry: the source has no CAD
history and re-modelling its locator/port details would be less faithful.
"""
from __future__ import annotations
import json, os, shutil
from pathlib import Path
import numpy as np
import trimesh
import cadquery as cq
from cadquery import exporters

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'source_revision_2491007'/'models'
OUT=Path(__file__).resolve().parent/'output'

# Geometric registration, found from the two matching rounded perimeter planes.
# obj_2 needs a Z flip: its locator pillars point +Z in the supplied print pose,
# whereas they must point down toward the open obj_1 cavity.
B0=np.array([141.4087563,174.1987152,0.0])
T0=np.array([126.9405746,81.9875374,0.0])
SOURCE_BOTTOM_H=17.9; SOURCE_TOP_H=5.2; SOURCE_ASSEMBLED_H=19.6
P={
 'revision':'MF650_2491007_rounded_side8_v5','units':'mm',
 'coordinate':'X long / Y wide / Z thick; front is +Z',
 'source_bottom_bbox_mm':[149.5,72.0,17.9], 'source_top_bbox_mm':[146.45,68.45,5.2],
 'source_assembled_z':[0.0,19.6], 'outer_mm':[160.0,90.0,39.6],
 'outer_z':[-10.0,29.6], 'outer_corner_radius':9.0, 'wall_mm':2.5,
 'sma_diameter':6.6,'sma_panel_thickness':2.4,
 'sma_x':[-51.0,-17.0,17.0,51.0],'sma_sides_y':[-45.0,45.0],
 'front_hole_diameter':2.8,'front_hole_pitch':4.8,
 'sma_assumption':{'thread':'1/4-36 UNS (vendor statement)','shank_diameter_mm':6.5,
                   'tail_length_mm':12.0,'washer_diameter_mm':10.0,'nut_af_mm':8.0},
}

def mesh_source(name, center, flip=False, zshift=0, aux=False, flip_z=True):
    m=trimesh.load_mesh(SRC/name, process=True)
    v=m.vertices.copy(); v[:,:2]-=center[:2]
    if flip:
        # Actual rigid Rx180 registration: reverse both Y and Z. Source-top
        # locator axes then meet source-bottom receiver axes (not just bbox).
        v[:,1]*=-1
        if flip_z: v[:,2]=SOURCE_ASSEMBLED_H-v[:,2]
        else:
            # Y-only reflection for the separately oriented aux reverses winding.
            m.invert()
        # Eight actual top locator / bottom receiver centres give this common
        # residual, not an envelope-centre assumption.
        v[:,0]+=.016750
        v[:,1]-=.227875
        if aux:
            # obj_3's 17.11-mm ear-hole pair maps to the unique top pair only
            # after this placement from its separate slicing-plate layout.
            v[:,0]-=37.555
            v[:,1]-=.475
    v[:,2]+=zshift
    m.vertices=v; m.remove_unreferenced_vertices()
    return m

def cad_box(x,y,z,xc=0,yc=0,zc=0):
    return cq.Workplane('XY').box(x,y,z).translate((xc,yc,zc))
def cylz(r,h,x=0,y=0,z=0):
    return cq.Workplane('XY').center(x,y).circle(r).extrude(h/2,both=True).translate((0,0,z))
def cyly(r,h,x=0,y=0,z=0):
    return cq.Workplane('XZ').center(x,z).circle(r).extrude(h/2,both=True).translate((0,y,0))
def cylx(r,h,x=0,y=0,z=0):
    return cq.Workplane('YZ').center(y,z).circle(r).extrude(h/2,both=True).translate((x,0,0))
def hexz(flat,h,x,y,z):
    return cq.Workplane('XY').center(x,y).polygon(6,flat/.8660254).extrude(h/2,both=True).translate((0,0,z))
def hexy(flat,h,x,y,z):
    """Hexagonal prism whose *total* axial depth is h, never both-sided doubled."""
    return cq.Workplane('XZ').center(x,z).polygon(6,flat/.8660254).extrude(h/2,both=True).translate((0,y,0))
def hexx(flat,h,x,y,z):
    return cq.Workplane('YZ').center(y,z).polygon(6,flat/.8660254).extrude(h/2,both=True).translate((x,0,0))
def rounded_plate(x,y,z,zc=0,r=9):
    return cad_box(x,y,z,zc=zc).edges('|Z').fillet(r)
def export_cad(name,shape,step=True):
    stl=OUT/f'{name}.stl'; exporters.export(shape,str(stl),tolerance=.08,angularTolerance=.12)
    if step: exporters.export(shape,str(OUT/f'{name}.step'))
    return stl
def export_mesh(name,m):
    m.remove_unreferenced_vertices(); m.export(OUT/f'{name}.stl')

def make_chassis():
    # Outer structural ring occupies Z=-7.4..30.5 only: covers sit directly
    # outside it at -10..-7.4 and 30.5..33.1. No accidental 60-mm posts.
    outer=rounded_plate(160,90,34.2,zc=9.8,r=9)  # Z=-7.3..26.9, 0.1mm cover clearance
    s=outer.cut(cad_box(152,82,39,zc=11.55))
    # Recessed side-panel seats: panel exterior is flush at Y=±45, with a
    # deliberate 0.25-mm edge seam. The whole 2.4-mm panel thickness replaces
    # this section of the chassis wall, so every SMA axis reaches the rear bay.
    # 130.5-mm seat supports the 130-mm side panels while preserving a 0.25-mm
    # end seam. This gives the panel M3 holes actual end material rather than
    # placing them 0.3mm from a 126-mm panel edge.
    for yy in (-41.0,41.0): s=s.cut(cad_box(130.5,8.0,19.5,0,yy,2.3))
    # Front/rear screw posts: total height 4.8mm, immediately behind each cover.
    for x in (-74,74):
      for y in (-40,40):
       s=s.union(cylz(4.8,4.8,x,y,24.45)).cut(cylz(1.7,6,x,y,24.45))
       s=s.union(cylz(4.8,4.8,x,y,-4.9)).cut(cylz(1.7,6,x,y,-4.9))
       # Nut slots open to central cavity in Z, with 5.8AF anti-rotation trap.
       s=s.cut(hexz(5.8,2.7,x,y,22.65)).cut(cad_box(6.2,6.2,3.1,x,y,21.15))
       s=s.cut(hexz(5.8,2.7,x,y,-3.1)).cut(cad_box(6.2,6.2,3.1,x,y,-1.6))
    # Matched side-panel M3 posts live outside the original source XY envelope.
    # Bore, hex trap and 6.3-mm loading throat share the actual Y screw axis.
    for yy in (-38,38):
      for x in (-61,61):
       s=s.union(cad_box(9,9,7,x,yy,-3.0)).cut(cyly(1.7,14,x,yy,-3.0))
       trap_y=yy-3 if yy>0 else yy+3
       # throat overlaps the hex cavity by >0.3mm; a M3 nut has a continuous
       # straight insertion route from the central cavity, not a 0.05 wall.
       s=s.cut(hexy(5.8,2.7,x,trap_y,-3.0)).cut(cad_box(6.3,3.2,7,x,yy-1.5 if yy>0 else yy+1.5,-3.0))
       # Full 6.5-wide load tunnel overlaps the hex capture by 1.6mm and runs
       # to the accessible central cavity; final hex walls retain nut rotation.
       s=s.cut(cad_box(6.5,5.5,6.5,x,33.8 if yy>0 else -33.8,-3.0))
    # Base-interface bores at both short ends; base selects one end at assembly.
    for xx in (-77,77):
      for y in (-25,25):
       # Base hardware intentionally lives in added rear-bay space at Z=-4,
       # below the supplied source frame (Z>=0).  A M3 x16 screw head seats
       # against the inner shoulder; its shank exits through the short end.
       s=s.union(cad_box(7,10,10,xx,y,-2.0))
       s=s.cut(cylx(1.7,11.0,xx,y,-4.0))
       head_x=75.5 if xx>0 else -75.5
       # A rear-bay counterbore (X≈60..77) lets the pan head arrive from the
       # removable rear-cover cavity. Its 3.1-mm-deep outward end seats the
       # head; the following narrow bore carries only the Ø3 stem.
       s=s.cut(cylx(2.85,17.1,68.5 if xx>0 else -68.5,y,-4.0))
    # Preserve source's measured short-end port opening (X≈-74.75, Y=-5..4,
    # Z=8.5..11.5): outer channel is deliberately larger for plug fingers.
    s=s.cut(cad_box(22,18,8,-80,0,10))
    # Preserve the source +Y service slot (X≈-43..-29, Z≈13..14.5) to exterior.
    # It is above the removable antenna-panel field, so it cannot weaken its M3 posts.
    s=s.cut(cad_box(18,10,4,-36,41,14))
    # Four real source-frame fusion bridges. They overlap the source's outer
    # shell at X≈±74/Y≈±25 while joining the added end rails at X≥76.
    for xx in (-75,75):
      for yy in (-25,25): s=s.union(cad_box(6,10,10,xx,yy,5))
    return s

def make_front():
    p=rounded_plate(160,90,2.6,zc=28.3,r=9).edges('>Z').fillet(.9)
    # The supplied source screen opening measures ~38.75x32.25mm.  The derived
    # bezel keeps its established 49x41 clearance window centred at X=-5,Y=-1.
    p=p.cut(cad_box(49,41,5,-5,-1,28.3))
    # Source's circular feature is retained; the derived auxiliary plate is not a
    # D7 substitute. Its guide has generous installation clearance.
    # Source auxiliary's double-ear pair fixes this real button axis.
    p=p.cut(cylz(3.25,5,-40.395,-.231,28.3))
    for x in (-74,74):
      for y in (-40,40): p=p.cut(cylz(1.7,5,x,y,28.3))
    # Regular front module / grille, entirely on the screen-opposite +X field.
    holes=[]
    # Dense v4 field: 8 columns x 13 rows, 104 through holes. Its X edge
    # remains 0.6mm short of the fixed X=64..72 press-feet footprint.
    for i in range(8):
      for j in range(13):
        x=28.4+4.8*i; y=-28.8+4.8*j
        holes.append((round(float(x),2),round(float(y),2)))
        p=p.cut(cylz(1.4,5,x,y,28.3))
    return p,holes

def make_side(side):
    # Exterior plane y=±45; the 2.4mm part sits in a chassis stop recess.
    y=side*43.8
    q=cad_box(130,2.4,19,0,y,2.3).edges('|Y').fillet(2.2)
    # SMA axes are genuinely side-facing, along Y, and tails occupy rear added bay.
    for x in P['sma_x']: q=q.cut(cyly(3.3,5,x,y,-3.5))
    for x in (-61,61): q=q.cut(cyly(1.7,5,x,y,-3.0))
    return q

def make_rear():
    # Match the 160x90/R9 front planform.  With M3 centres at ±74/±40 this
    # leaves a closed 2.30-mm minimum corner land beyond each Ø3.4 through hole
    # instead of breaking the former smaller R8 rear-corner outline.
    q=rounded_plate(160,90,2.6,zc=-8.7,r=9).edges('<Z').fillet(.8)
    # rear panel is intentionally free of SMA holes
    for x in (-74,74):
      for y in (-40,40):q=q.cut(cylz(1.7,5,x,y,-8.7))
    # 2 x 4 rear vents go to rear bay -> source bottom service aperture.
    for x in (-53,53):
      for y in (-22,-7,7,22):
        # capsule cut: a straight 6.8-mm segment plus two circular ends
        slot=cad_box(6.8,3.2,5,x,y,-8.7).union(cylz(1.6,5,x-3.4,y,-8.7)).union(cylz(1.6,5,x+3.4,y,-8.7))
        q=q.cut(slot)
    return q

def make_base():
    # True upright dock, defaulting to +X as the lower short end / ground
    # normal. The 7mm YZ foot is 100mm wide by 85mm deep, not an XY back plate.
    foot=cad_box(7,100,85,xc=106,yc=0,zc=9.8).edges('|X').fillet(7)
    # 25mm central U channel directly aligns the measured X-end port space.
    foot=foot.cut(cad_box(10,28,25,xc=106,yc=0,zc=10))
    # two short structural wings leave central USB / cable approach clear
    wings=cad_box(21.9,12,14,xc=91.55,yc=-25,zc=0).union(cad_box(21.9,12,14,xc=91.55,yc=25,zc=0))
    b=foot.union(wings)
    for y in (-25,25):
      # X-axis bore, captive M3 hex recess, and its open-end loading route.
      # A real 5.5-AF x 2.4-mm nut enters from the outward wing face (X>0),
      # moves to X=89, then is held by two hex flats while an M3 bolt arrives
      # through the chassis end bore.  This is deliberately not two bare
      # co-axial 3.4-mm holes.
      b=b.cut(cq.Workplane('YZ').center(y,-4.0).circle(1.7).extrude(15,both=True).translate((91.55,0,0)))
      b=b.cut(hexx(5.8,2.7,89.0,y,-4.0))
      # The 6.8-mm side loading throat opens at the exterior flank of each
      # short support (Y=±31), not through the wide vertical foot plate.  It
      # clears the 5.5-AF nut's 6.35-mm point circle on a real installation
      # path, while the M3 bolt continues along X through the chassis bore.
      # It reaches the pocket centreline so that the nut's full 2.4-mm axial
      # thickness stays clear at the hand-off, while the opposite hex faces
      # remain to prevent rotation after seating.
      b=b.cut(cad_box(7.2,18.0,7.2,89.0,34.0 if y>0 else -34.0,-4.0))
    return b

def make_button_extender():
    """One-piece mechanically captured extension for the actual source boss.

    The 0.30-mm release gap is retained.  Unlike v4's Ø9 cap which sat on the
    bezel top plane, v5 has a Ø6.2 driver head that passes the Ø6.5 guide and
    an Ø8 internal flange below the bezel.  With the bezel removed it is put
    in from the front/exterior, then the bezel descends over its Ø6.2 driver;
    that flange is the actual +Z pull-out stop.  The
    source top itself is the verified 07 upward-slider stop; no thin redundant
    cup is retained around the source boss.
    """
    x,y=-40.395,-.231
    # A continuous Ø5.3 solid contact/stem has no .25-mm peripheral lip.  Its
    # lower face is Z=19.90, preserving the actual 0.30-mm source-boss release.
    contact=cylz(2.65,.25,x,y,20.025)
    shaft=cylz(2.65,9.25,x,y,24.775)       # Z=20.15..29.40
    inner_flange=cylz(4.00,1.20,x,y,26.30) # Z=25.70..26.90, 0.10 below bezel
    driver=cylz(3.10,1.20,x,y,30.00)       # Z=29.40..30.60, through Ø6.5 guide
    return contact.union(shaft).union(inner_flange).union(driver)

def make_source_frames():
    bottom=mesh_source('obj_1_COMPOUND_1.stl',B0)
    top=mesh_source('obj_2_COMPOUND_3.stl',T0,flip=True)
    # The auxiliary part gets the same rigid candidate transform; its physical
    # locating pair / travel is checked separately and is not guessed from z.
    aux=mesh_source('obj_3_COMPOUND_4.stl',T0,flip=True,aux=True,flip_z=False,zshift=17.3)
    # Manifold exact mesh cuts. Source bottom central aperture actually removes
    # the original floor; top +X module zone opens to its original cavity.
    cut_b=trimesh.creation.box((120,48,9),transform=trimesh.transformations.translation_matrix((0,0,1.5)))
    # Covers every Ø3 module-grid path including its 1.5-mm radius at Y=±27.5.
    cut_t=trimesh.creation.box((44,62,8),transform=trimesh.transformations.translation_matrix((48,0,17)))
    bottom=trimesh.boolean.difference([bottom,cut_b],engine='manifold')
    top=trimesh.boolean.difference([top,cut_t],engine='manifold')
    return bottom,top,aux

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for f in OUT.iterdir():
        if f.is_file(): f.unlink()
    chassis=make_chassis(); front,holes=make_front(); rear=make_rear(); left=make_side(-1); right=make_side(1); base=make_base(); button=make_button_extender()
    # This is a construction/reference STEP for the parametric added skeleton;
    # the actual printable chassis below is an exact manifold union with the
    # registered source bottom, so the source functional frame is not a loose part.
    export_cad('added_chassis_scaffold_reference',chassis)
    for name,s in {'front_bezel_reference':front,'rear_cover_no_sma':rear,
                   'left_side_antenna_panel_4x1':left,'right_side_antenna_panel_4x1':right,
                   'dual_end_desk_base':base,'button_extender_from_aux':button}.items(): export_cad(name,s)
    bottom,top,aux=make_source_frames()
    # Manifold union makes the actual printable front a one-piece STL with
    # four press feet. Reference STEP intentionally excludes mesh-added feet.
    front_ref=trimesh.load_mesh(OUT/'front_bezel_reference.stl',process=True)
    feet=[]
    for x in (-68.,68.):
      for y in (-30.,30.):
        feet.append(trimesh.creation.box((8,8,7.4),transform=trimesh.transformations.translation_matrix((x,y,23.6))))
    front_print=trimesh.boolean.union([front_ref,*feet],engine='manifold')
    if not(front_print.is_watertight and front_print.is_volume and len(front_print.split())==1):
        raise RuntimeError('manifold front feet did not form one printable body')
    export_mesh('front_bezel',front_print)
    export_mesh('inspection_registered_source_bottom_open_frame',bottom)
    scaffold=trimesh.load_mesh(OUT/'added_chassis_scaffold_reference.stl',process=True)
    fused=trimesh.boolean.union([scaffold,bottom],engine='manifold')
    # Manifold can emit zero-area sliver shells around coplanar STL triangles.
    # Keep the single positive-volume connected union, reject any second real body.
    comps=fused.split(only_watertight=False)
    real=[q for q in comps if float(q.volume)>1.0]
    if len(real)!=1: raise RuntimeError(f'source/chassis union produced {len(real)} real bodies')
    fused=real[0]
    if not(fused.is_watertight and fused.is_volume and len(fused.split())==1):
        raise RuntimeError('source bottom did not fuse to added chassis as one printable body')
    export_mesh('main_chassis',fused)
    export_mesh('registered_source_top_feature_frame',top)
    export_mesh('registered_source_dual_ear_button_plate',aux)
    rec={'parameters':P,'front_grille_centers_xy':holes,
         'front_grille':{'revision':'v4 dense grille','layout':[8,13],'hole_count':len(holes),'diameter_mm':2.8,'pitch_mm':4.8,'centres_x_mm':[28.4,62.0],'centres_y_mm':[-28.8,28.8],'nominal_open_area_mm2':round(len(holes)*np.pi*1.4**2,6)},
         'button_extender_v5':{'axis_xy_mm':[-40.395,-.231],'outer_driver_diameter_mm':6.2,'guide_diameter_mm':6.5,
           'inner_capture_flange_diameter_mm':8.0,'source_boss_contact_diameter_mm':5.3,
           'release_to_source_boss_mm':.3,'note':'With the front bezel removed, install from the front/exterior; then lower the bezel over the Ø6.2 driver. The continuous solid contact/stem removes the former thin cup; source-top geometry is the verified source-slider upward stop.'},
         'source_registration':{'bottom_transform':'subtract obj_1 perimeter-plane centre B0 from XY; preserve Z',
          'top_transform':'after T0 XY normalization: (x+0.016750, -y-0.227875, 19.600-z); rigid Rx180; locator pillars face original-bottom receivers',
          'aux_transform':'obj_3 uses the top XY correction plus local (-37.555,-0.475); its ear plate remains inside and boss faces front; Z=17.3..19.6',
          'geometric_basis':'matching long/short rounded perimeter planes centre source XY; actual locator-pillar fit requires Rx180; this is a digital 19.6mm assembly height, not a physical closed-case measurement.'},
         'functional_openings':{'bottom_service_cut_mm':[120,48,9],'top_module_cut_mm':[44,62,8],
          'air_path':'front round grille -> opened +X source-top module region -> original cavity -> bottom 120x48 service cut -> rear vents'},
         'hardware_assumptions':P['sma_assumption']}
    (OUT/'build_record.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(OUT),'grille_holes':len(holes)},ensure_ascii=False),flush=True)
    os._exit(0)
if __name__=='__main__': main()
