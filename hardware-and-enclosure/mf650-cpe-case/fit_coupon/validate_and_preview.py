"""Validate the exported coupon mesh and render it from its actual triangles."""

from __future__ import annotations

import json
from pathlib import Path

import trimesh
import vtk


OUT = Path(__file__).resolve().parent
mesh = trimesh.load_mesh(OUT / "sma_hole_fit_coupon.stl", force="mesh")
if not mesh.is_watertight:
    raise RuntimeError("exported coupon STL is not watertight")
if mesh.volume <= 0:
    raise RuntimeError("exported coupon STL has non-positive volume")

# VTK renders the actual STL with smooth shading, avoiding the distracting
# triangle-grid artefacts of a matplotlib mesh plot.
reader = vtk.vtkSTLReader()
reader.SetFileName(str(OUT / "sma_hole_fit_coupon.stl"))
reader.Update()
mapper = vtk.vtkPolyDataMapper()
mapper.SetInputConnection(reader.GetOutputPort())
actor = vtk.vtkActor()
actor.SetMapper(mapper)
actor.GetProperty().SetColor(0.27, 0.35, 0.45)
actor.GetProperty().SetInterpolationToPhong()
renderer = vtk.vtkRenderer()
renderer.SetBackground(1.0, 1.0, 1.0)
renderer.AddActor(actor)
window = vtk.vtkRenderWindow()
window.SetOffScreenRendering(1)
window.SetSize(1400, 650)
window.AddRenderer(renderer)
renderer.ResetCamera()
camera = renderer.GetActiveCamera()
camera.Elevation(35)
camera.Azimuth(-45)
renderer.ResetCameraClippingRange()
window.Render()
capture = vtk.vtkWindowToImageFilter()
capture.SetInput(window)
capture.Update()
png = vtk.vtkPNGWriter()
png.SetFileName(str(OUT / "preview.png"))
png.SetInputConnection(capture.GetOutputPort())
png.Write()
bounds = mesh.bounds

validation_path = OUT / "validation.json"
record = json.loads(validation_path.read_text(encoding="utf-8"))
record["stl_mesh"] = {
    "watertight": bool(mesh.is_watertight),
    "is_volume": bool(mesh.is_volume),
    "euler_number": int(mesh.euler_number),
    "volume_mm3": round(float(mesh.volume), 3),
    "bounds_mm": [[round(float(v), 3) for v in row] for row in bounds],
    "face_count": int(len(mesh.faces)),
}
record["preview"] = str(OUT / "preview.png")
validation_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(record["stl_mesh"], ensure_ascii=False, indent=2))
