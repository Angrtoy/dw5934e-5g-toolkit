"""Record byte-identical proof that v5 changes only the printable button extender."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;V4=HERE.parent/'design_v4_dense_grille'/'output';V5=HERE/'output'
PARTS=['main_chassis','front_bezel','rear_cover_no_sma','left_side_antenna_panel_4x1','right_side_antenna_panel_4x1','registered_source_top_feature_frame','registered_source_dual_ear_button_plate','dual_end_desk_base']
def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1<<20),b''):h.update(block)
 return h.hexdigest()
def main():
 rows=[]
 for part in PARTS:
  a,b=V4/(part+'.stl'),V5/(part+'.stl')
  if not(a.exists() and b.exists()):raise FileNotFoundError(f'missing v4/v5 comparison STL: {part}')
  ha,hb=sha(a),sha(b);rows.append({'part':part,'v4_sha256':ha,'v5_sha256':hb,'byte_identical':ha==hb})
 result={'comparison':'v5 against accepted v4 printable parts','changed_printable_part_only':'button_extender_from_aux.stl','all_other_eight_byte_identical':all(r['byte_identical'] for r in rows),'parts':rows}
 if not result['all_other_eight_byte_identical']:raise RuntimeError('a non-button printable part differs from v4')
 (V5/'v4_unchanged_parts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'passed':True,'parts':len(rows)},ensure_ascii=False))
if __name__=='__main__':main()
