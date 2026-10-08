"""Strict final geometry checks. Fails rather than merely reporting a conflict."""
from __future__ import annotations
import json, os
from itertools import combinations
from pathlib import Path
import numpy as np
import trimesh

OUT=Path(__file__).resolve().parent/'output'
PRINT=['main_chassis','front_bezel','rear_cover_no_sma','left_side_antenna_panel_4x1','right_side_antenna_panel_4x1','registered_source_top_feature_frame','registered_source_dual_ear_button_plate','button_extender_from_aux','dual_end_desk_base']
ASSEMBLED=[x for x in PRINT if x!='dual_end_desk_base']
def load(n):return trimesh.load_mesh(OUT/(n+'.stl'),process=True)
def iv(a,b):
 q=trimesh.boolean.intersection([a,b],engine='manifold');return 0. if q is None else abs(float(q.volume))
def cyl_y(radius,length,x,y,z,sections=32):
 m=trimesh.creation.cylinder(radius,length,sections=sections);m.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2,[1,0,0]));m.apply_translation((x,y,z));return m
def hex_y(flat,length,x,y,z):return cyl_y(flat/1.7320508,length,x,y,z,6)
def cyl_z(radius,length,x,y,z,sections=48):
 m=trimesh.creation.cylinder(radius,length,sections=sections);m.apply_translation((x,y,z));return m
def info(m):return {'watertight':bool(m.is_watertight),'is_volume':bool(m.is_volume),'connected_components':len(m.split()),'faces':len(m.faces),'volume_mm3':round(abs(float(m.volume)),3),'bounds_mm':np.round(m.bounds,4).tolist()}
def require_zero(label,val,tol=.01):
 if val>tol:raise RuntimeError(f'{label}: unexpected solid intersection {val:.6f} mm3')
def main():
    M={n:load(n) for n in PRINT}
    bottom=load('inspection_registered_source_bottom_open_frame')
    data={n:info(m) for n,m in M.items()}
    for n,d in data.items():
        if not (d['watertight'] and d['is_volume'] and d['connected_components']==1):
            raise RuntimeError(f'{n} is not a one-piece printable volume')

    top=M['registered_source_top_feature_frame']
    aux=M['registered_source_dual_ear_button_plate']
    main=M['main_chassis']
    front=M['front_bezel']
    btn=M['button_extender_from_aux']
    source_iv=iv(bottom,top)
    require_zero('registered source bottom/top',source_iv,.001)
    aux_iv=iv(aux,top)
    require_zero('aux ear/button plate to top',aux_iv,.001)

    # Each Ø2.8 nominal grille hole is examined with a Ø2.76 probe.  The three
    # segments establish outside -> source-front module cavity, not a claim of
    # through-bottom/rear perforation.
    grille=[]
    grille_specs=(
        ('front_bezel_including_press_feet',[19.5,29.7],front),
        ('source_top_open_module',[13.0,19.7],top),
        ('main_front_module_cavity',[13.0,19.7],main),
    )
    for i in range(8):
        for j in range(13):
            x=28.4+4.8*i; y=-28.8+4.8*j; hits={}
            for label,(z0,z1),solid in grille_specs:
                v=iv(cyl_z(1.38,z1-z0,x,y,(z0+z1)/2),solid)
                require_zero(f'v5 grille {i}/{j} {label}',v)
                hits[label]=round(v,6)
            grille.append({'i':i,'j':j,'x_mm':round(x,3),'y_mm':round(y,3),
                           'probe_diameter_mm':2.76,'segment_intersections_mm3':hits})
    if len(grille)!=104: raise RuntimeError(f'v5 grille count wrong: {len(grille)}')

    # The complete 9 choose 2 static relation matrix is a release gate.
    pairs={}
    for a,b in combinations(PRINT,2):
        v=iv(M[a],M[b]); pairs[f'{a}__{b}']=round(v,6)
        require_zero(f'{a}/{b}',v)

    # Actual 12mm SMA tail, round Ø10 washer and 8AF nut placeholders.
    tails=[]; washers=[]; sma_nuts=[]; tail_hits=[]
    for side in (-1,1):
        for x in (-51.,-17.,17.,51.):
            tail=cyl_y(3.25,12,x,side*36.6,-3.5)
            washer=cyl_y(5.0,1.0,x,side*45.5,-3.5)
            nut=hex_y(8.0,3.0,x,side*41.1,-3.5)
            tails.append(tail); washers.append(washer); sma_nuts.append(nut)
            probe=cyl_y(3.10,20,x,side*37.0,-3.5)
            panel=M['left_side_antenna_panel_4x1'] if side<0 else M['right_side_antenna_panel_4x1']
            checks={'panel':iv(probe,panel),'main_window':iv(probe,main),'source_bottom':iv(tail,bottom),
                    'source_top':iv(tail,top),'main_tail':iv(tail,main),'washer_main':iv(washer,main),'nut_main':iv(nut,main)}
            for k,v in checks.items(): require_zero(f'SMA {side}/{x} {k}',v)
            tail_hits.append({'side_y':side*45,'x':x,**{k:round(v,6) for k,v in checks.items()}})

    # Four M3 captive nuts travel from the central rear cavity into real traps.
    m3=[]
    for side in (-1,1):
        for x in (-61.,61.):
            y=side*35.
            nut=hex_y(5.6,2.5,x,y,-3.0)
            clear=iv(nut,main); require_zero(f'side M3 nut {side}/{x}',clear)
            sweep=[]
            for yy in np.arange(30,35.01,.25):
                test=hex_y(5.5,2.4,x,side*yy,-3.0)
                v=iv(test,main); require_zero(f'side M3 load {side}/{x}/{yy}',v)
                sweep.append(round(v,6))
            rot=hex_y(5.5,2.4,x,side*35,-3.0)
            rot.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(30),[0,1,0],point=[x,side*35,-3.0]))
            block=iv(rot,main)
            if block<.01: raise RuntimeError(f'side M3 rotation not retained {side}/{x}')
            m3.append({'side_y':side*45,'x':x,'nut_intersection_mm3':round(clear,6),
                       'load_sweep_samples':len(sweep),'load_sweep_max_mm3':max(sweep),
                       'rotation30_block_mm3':round(block,6)})

    # Front-mounted source top: nominal mesh design leaves .30 release / .40
    # stop. A separately checked actual bezel seating allowance is -0.10.
    press0=iv(top,front)
    t30=top.copy(); t30.apply_translation((0,0,.30)); press30=iv(t30,front)
    t40=top.copy(); t40.apply_translation((0,0,.40)); press40=iv(t40,front)
    require_zero('front press .30',press30)
    if press40<.01: raise RuntimeError('front press does not stop top at .40')
    front_seated=front.copy(); front_seated.apply_translation((0,0,-.10))
    seated_static={n:iv(front_seated,s) for n,s in {
        'main_chassis':main,'source_top':top,'source_aux':aux,'button':btn,
        'rear':M['rear_cover_no_sma'],'left':M['left_side_antenna_panel_4x1'],
        'right':M['right_side_antenna_panel_4x1'],'base':M['dual_end_desk_base']}.items()}
    for n,v in seated_static.items(): require_zero(f'front seated -0.10 {n}',v)
    t20=top.copy(); t20.apply_translation((0,0,.20)); seated_top20=iv(t20,front_seated)
    require_zero('seated front top +.20',seated_top20)
    t21=top.copy(); t21.apply_translation((0,0,.21)); seated_top21=iv(t21,front_seated)
    if seated_top21<.01: raise RuntimeError('seated front does not stop top at +.21')

    # Source top may be removed after front removal along +Z.
    top_sweep=[]
    for dz in np.arange(0,13.01,.25):
        q=top.copy(); q.apply_translation((0,0,float(dz)))
        v=iv(q,main); require_zero(f'top +Z extraction at {dz}',v)
        top_sweep.append(round(v,6))

    # V5 one-piece button mechanics. With the bezel removed, the Ø6.2 driver
    # is lowered from the front/exterior; then 02 descends over its Ø6.5 guide.
    # The Ø8 inner flange is the actual +Z pull-out stop.
    non_drive={'front_bezel':front,'registered_source_top_feature_frame':top,'main_chassis':main,
               'rear_cover_no_sma':M['rear_cover_no_sma'],'left_side_antenna_panel_4x1':M['left_side_antenna_panel_4x1'],
               'right_side_antenna_panel_4x1':M['right_side_antenna_panel_4x1'],'dual_end_desk_base':M['dual_end_desk_base']}
    release=iv(aux,btn); require_zero('v5 aux/button release',release)
    release_non={n:iv(btn,s) for n,s in non_drive.items()}
    for n,v in release_non.items(): require_zero(f'v5 button release {n}',v)
    install=[]
    for dz in np.arange(10.0,-.001,-.25):
        q=btn.copy(); q.apply_translation((0,0,float(dz)))
        hits={n:iv(q,s) for n,s in {'main':main,'source_top':top,'source_aux':aux}.items()}
        for n,v in hits.items(): require_zero(f'v5 button exterior install {dz} {n}',v)
        install.append({n:round(v,6) for n,v in hits.items()})
    front_install=[]
    for dz in list(np.arange(10.0,-.001,-.25))+[-.10]:
        q=front.copy(); q.apply_translation((0,0,float(dz)))
        hits={n:iv(q,s) for n,s in {'button':btn,'source_aux':aux,'source_top':top,'main':main}.items()}
        for n,v in hits.items(): require_zero(f'v5 bezel descent {dz} {n}',v)
        front_install.append({n:round(v,6) for n,v in hits.items()})
    pull10=btn.copy(); pull10.apply_translation((0,0,.10)); pull10v=iv(pull10,front); require_zero('v5 button pull +.10',pull10v)
    pull11=btn.copy(); pull11.apply_translation((0,0,.11)); pull11v=iv(pull11,front)
    if pull11v<.01: raise RuntimeError('v5 button inner flange does not prevent +Z pull-out')
    seated_btn=iv(btn,front_seated); require_zero('v5 button with front seated -0.10',seated_btn)

    # Drive down to the real source-plate first contact (.30), then a 0.50mm
    # geometrical working-travel envelope. After contact the *source slider*
    # moves with the pusher; no test falsely permits 08 to pass through 07.
    presses=[]
    travels=[round(float(v),3) for v in np.arange(0,.801,.05)]
    for travel in travels:
        q=btn.copy(); q.apply_translation((0,0,-float(travel)))
        hits={n:iv(q,s) for n,s in non_drive.items()}
        for n,v in hits.items(): require_zero(f'v5 button press {travel} {n}',v)
        aux_q=aux.copy(); aux_q.apply_translation((0,0,-max(0.0,float(travel)-.30)))
        aux_hit=iv(q,aux_q)
        require_zero(f'v5 button/source-slider contact-chain {travel}',aux_hit)
        presses.append({'downward_mm':round(float(travel),3),
                        'non_drive_intersections_mm3':{n:round(v,6) for n,v in hits.items()},
                        'source_slider_down_mm':round(max(0.0,float(travel)-.30),3),
                        'button_to_moving_source_slider_mm3':round(aux_hit,6)})

    # 07 is an axial slider on the source locating posts. The original source
    # top (not a new thin button cup) blocks its +Z motion at +.15, while the
    # ears still retain .45mm of their original .60mm post engagement.
    aux_dn=aux.copy(); aux_dn.apply_translation((0,0,-.50)); aux_dn_top=iv(aux_dn,top); require_zero('v5 aux geometric -.50 travel to top',aux_dn_top)
    aux_up15=aux.copy(); aux_up15.apply_translation((0,0,.15)); aux_up15_top=iv(aux_up15,top)
    if aux_up15_top<.01: raise RuntimeError('source aux has no +Z source-top retention')
    # Worst accepted seating/motion combination: bezel seated -0.10, source
    # frame lifted +0.20, button fully pressed -0.80 and source slider global
    # -0.50.  It remains a zero-volume mesh chain (06/02's near contact is
    # separately recorded above as a numerical boundary, not a crush).
    cfront=front.copy(); cfront.apply_translation((0,0,-.10))
    ctop=top.copy(); ctop.apply_translation((0,0,.20))
    cbtn=btn.copy(); cbtn.apply_translation((0,0,-.80))
    caux=aux.copy(); caux.apply_translation((0,0,-.50))
    combined={'button_front':iv(cbtn,cfront),'button_top':iv(cbtn,ctop),'button_main':iv(cbtn,main),
              'button_aux':iv(cbtn,caux),'aux_top':iv(caux,ctop),'aux_front':iv(caux,cfront),'top_front':iv(ctop,cfront)}
    for n,v in combined.items(): require_zero(f'v5 seated/raised/full-press {n}',v,.001)

    rear_land=9.0-np.hypot(80-9-74,45-9-40)-1.7
    if rear_land<=0: raise RuntimeError(f'rear M3 holes break outer corner: land={rear_land}')
    side_m3_land=65.0-61.0-1.7
    if side_m3_land<=0: raise RuntimeError(f'side M3 holes break panel end: land={side_m3_land}')

    result={
      'revision':'MF650_2491007_rounded_side8_v5','mesh_validation':data,
      'source_registration':{'transform':'top=(x+0.016750, -y-0.227875, 19.600-z) after B0/T0 XY normalization; rigid Rx180','bottom_top_intersection_mm3':round(source_iv,6),'locator_fit_mm':{'rms':.005792,'max':.009674},'pillar_insert_mm':3.5,'note':'19.6 mm is this digital assembly height, not a physically measured closed-case thickness.'},
      'source_auxiliary':{'ear_pair_registration':'after top mapping, local additional XY=(-37.555,-0.475); 17.11mm ear pair maps to unique top pair','orientation':'ear plate inside / centre boss toward front; base Z=17.3, boss top Z=19.6','top_intersection_mm3':round(aux_iv,6),'physical_trial_required':'source switch/aux travel is not supplied as a separate electrical model.'},
      'dense_front_grille':{'layout':'8 columns x 13 rows','hole_count':104,'nominal_hole_diameter_mm':2.8,'pitch_mm':4.8,'centres_x_mm':[28.4,62.0],'centres_y_mm':[-28.8,28.8],'nominal_open_area_mm2':round(104*np.pi*1.4**2,6),'probe_diameter_mm':2.76,'radial_mesh_tolerance_mm':.02,'module_cavity_endpoint_z_mm':13.0,'all_104_outer_to_front_module_cavity_clear':True,'not_claimed':'This does not claim each grille hole passes through the original bottom frame or corresponds to a rear-cover hole.','per_hole':grille,'press_foot_min_x_edge_clearance_mm':.6},
      'all_required_print_parts_one_piece_watertight':True,'all_9_print_part_pair_intersections_mm3':pairs,
      'side_sma':{'diameter_mm':6.6,'axis':'Y','sides_y_mm':[-45,45],'x_each_side_mm':[-51,-17,17,51],'count':8,'tail_start':'panel inner face Y=±42.6, inward 12mm','tail_z_mm':-3.5,'assumption':{'shank_diameter_mm':6.5,'tail_mm':12,'washer':'round Ø10','nut':'8mm AF'},'geometry_checks':tail_hits},
      'side_m3_traps':m3,
      'front_press_feet':{'static_mm3':round(press0,6),'top_plus_0_30_mm3':round(press30,6),'top_plus_0_40_block_mm3':round(press40,6),'seated_front_minus_0_10_all_static_mm3':{n:round(v,6) for n,v in seated_static.items()},'seated_top_plus_0_20_mm3':round(seated_top20,6),'seated_top_plus_0_21_block_mm3':round(seated_top21,6),'reference_step':'front_bezel_reference.step intentionally lacks mesh-added print feet'},
      'top_removal_sweep':{'axis':'+Z','range_mm':[0,13],'increment_mm':.25,'maximum_intersection_mm3':max(top_sweep),'complete_clearance':'top lower bound 14.4 + 13 = 27.4mm exceeds chassis upper bound 26.9mm'},
      'button_chain_v5':{'axis_xy_mm':[-40.395,-.231],'release_gap_mm':.30,'driver_diameter_mm':6.20,'bezel_guide_diameter_mm':6.50,'continuous_contact_stem_diameter_mm':5.30,'internal_capture_flange_diameter_mm':8.0,'inner_flange_to_bezel_release_mm':.10,'exterior_button_install_sweep_mm':[10,0],'exterior_button_install_samples':len(install),'exterior_button_install_max_mm3':max(max(s.values()) for s in install),'bezel_descent_after_button_sweep_mm':[10,-.10],'bezel_descent_samples':len(front_install),'bezel_descent_max_mm3':max(max(s.values()) for s in front_install),'pull_plus_0_10_front_mm3':round(pull10v,6),'pull_plus_0_11_front_block_mm3':round(pull11v,6),'front_seated_minus_0_10_mm3':round(seated_btn,6),'initial_source_contact_down_mm':.30,'requested_working_travel_after_contact_mm':.50,'press_to_down_mm':.80,'press_samples':presses,'source_aux_geometric_minus_0_50_to_top_mm3':round(aux_dn_top,6),'source_aux_upward_retention':{'source_top_block_plus_0_15_mm3':round(aux_up15_top,6),'source_ear_post_insert_mm':.60,'minimum_post_insert_before_source_top_stop_mm':.45,'note':'No redundant thin button cup is used. Actual source-top geometry blocks the source slider before its ear holes can leave the posts.'},'v4_failure_regression':{'v4_outer_cap_diameter_mm':9.0,'v4_cap_bottom_z_mm':29.6,'v4_down_minus_0_01_front_intersection_mm3':.304,'v4_down_minus_0_10_front_intersection_mm3':3.0416,'v4_down_minus_0_30_front_intersection_mm3':9.1248,'purpose':'The v4 geometry must fail this physical-cap regression; v5 avoids that cap/bezel collision.'},'note':'07/source switch hardware was not supplied. The .50mm geometric clearance is not proof of switch actuation force, electrical actuation, return force, or physical print fit.'},
      'button_chain_v5':{'axis_xy_mm':[-40.395,-.231],'release_gap_mm':.30,'driver_diameter_mm':6.20,'bezel_guide_diameter_mm':6.50,'continuous_contact_stem_diameter_mm':5.30,'internal_capture_flange_diameter_mm':8.0,'inner_flange_to_bezel_release_mm':.10,'exterior_button_install_sweep_mm':[10,0],'exterior_button_install_samples':len(install),'exterior_button_install_max_mm3':max(max(s.values()) for s in install),'bezel_descent_after_button_sweep_mm':[10,-.10],'bezel_descent_samples':len(front_install),'bezel_descent_max_mm3':max(max(s.values()) for s in front_install),'pull_plus_0_10_front_mm3':round(pull10v,6),'pull_plus_0_11_front_block_mm3':round(pull11v,6),'front_seated_minus_0_10_mm3':round(seated_btn,6),'initial_source_contact_down_mm':.30,'requested_working_travel_after_contact_mm':.50,'press_to_down_mm':.80,'press_samples':presses,'source_aux_geometric_minus_0_50_to_top_mm3':round(aux_dn_top,6),'source_aux_upward_retention':{'source_top_block_plus_0_15_mm3':round(aux_up15_top,6),'source_ear_post_insert_mm':.60,'minimum_post_insert_before_source_top_stop_mm':.45,'note':'No redundant thin button cup is used. Actual source-top geometry blocks the source slider before its ear holes can leave the posts.'},'seated_front_minus_0_10_source_top_plus_0_20_full_press':{n:round(v,6) for n,v in combined.items()},'v4_failure_regression':{'v4_outer_cap_diameter_mm':9.0,'v4_cap_bottom_z_mm':29.6,'v4_bezel_top_z_mm':29.6,'v4_down_minus_0_01_front_intersection_mm3':.304,'v4_down_minus_0_10_front_intersection_mm3':3.0416,'v4_down_minus_0_30_front_intersection_mm3':9.1248,'purpose':'The v4 geometry must fail this physical-cap regression; v5 avoids that cap/bezel collision.'},'note':'07/source switch hardware was not supplied. The .50mm geometric clearance is not proof of switch actuation force, electrical actuation, return force, or physical print fit.'},
      'rear_cover_m3_closed_edge_land_mm':round(float(rear_land),6),'side_panel_m3_end_edge_land_mm':round(float(side_m3_land),6),
      'limits':['No PCB, battery, USB plug, actual SMA or cable solid was supplied. Thermal, lithium safety, RF, cable bend, real press force/travel and physical fit remain unverified.']}
    (OUT/'cad_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':True,'pairs':len(pairs),'top_sweep':len(top_sweep),'grille_holes':len(grille)},ensure_ascii=False),flush=True)
    os._exit(0)
if __name__=='__main__': main()
