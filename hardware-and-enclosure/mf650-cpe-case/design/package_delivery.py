"""Create the reproducible delivery ZIP without the local virtual environment."""
from __future__ import annotations
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/"MF650_CPE_registered_v2_delivery.zip"
INCLUDE=[ROOT/"README.md",ROOT/"design"/"README.md",ROOT/"design"/"ASSEMBLY_AND_SLICING.md",
         ROOT/"design"/"build_mf650_cpe.py",ROOT/"design"/"validate_and_render.py",ROOT/"design"/"output",
         ROOT/"source_downloads"/"底壳.STEP",ROOT/"source_downloads"/"上盖.STEP",ROOT/"source_downloads"/"按钮.STEP",
         ROOT/"fit_coupon"]
with ZipFile(DEST,"w",ZIP_DEFLATED) as z:
    for p in INCLUDE:
        if p.is_file(): z.write(p,p.relative_to(ROOT))
        elif p.exists():
            for f in p.rglob("*"):
                if f.is_file() and ".venv" not in f.parts and "__pycache__" not in f.parts: z.write(f,f.relative_to(ROOT))
if not DEST.exists() or any(".venv" in n for n in ZipFile(DEST).namelist()): raise RuntimeError("invalid delivery archive")
print(f"{DEST} ({DEST.stat().st_size} bytes), files={len(ZipFile(DEST).namelist())}")
os._exit(0)
