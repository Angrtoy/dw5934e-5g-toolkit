"""Parametric SMA-like bulkhead hole fit coupon; independent of the MF650 shell."""

from __future__ import annotations

import json
import os
from pathlib import Path

import cadquery as cq
from cadquery import exporters, importers


OUT = Path(__file__).resolve().parent
PARAMETERS = {
    "units": "mm",
    "thickness": 2.4,
    "plate_length": 142.0,
    "plate_width": 32.0,
    "corner_radius": 4.0,
    "hole_diameters": [6.4, 6.5, 6.6, 6.7, 6.8],
    "hole_pitch": 25.0,
    "engraving_depth": 0.4,
    "label_font_height": 4.5,
}


def build() -> cq.Workplane:
    p = PARAMETERS
    # Rounded rectangular plate, in XY, extruded upwards. The circles have no
    # claimed relationship to the user's exact connector beyond being a test
    # range for printed clearance.
    plate = (
        cq.Workplane("XY")
        .rect(p["plate_length"] - 2 * p["corner_radius"], p["plate_width"])
        .extrude(p["thickness"])
        .edges("|Z")
        .fillet(p["corner_radius"])
    )
    centers = [
        (i - (len(p["hole_diameters"]) - 1) / 2) * p["hole_pitch"]
        for i in range(len(p["hole_diameters"]))
    ]
    for x, diameter in zip(centers, p["hole_diameters"], strict=True):
        # Use cutters referenced to the global XY origin.  Chaining
        # faces().workplane().center() would make later centers relative to a
        # prior selected face and can silently stack all holes at one location.
        hole = cq.Workplane("XY").center(x, 0).circle(diameter / 2).extrude(p["thickness"] + 2, both=True)
        plate = plate.cut(hole)
        # Engraved text stays on the printable top face.  It identifies the
        # nominal CAD diameter, not a confirmed connector specification.
        label = (
            cq.Workplane("XY")
            .workplane(offset=p["thickness"] - p["engraving_depth"])
            .center(x, 10.0)
            .text(f"{diameter:.1f}", p["label_font_height"], p["engraving_depth"] + 0.01,
                  halign="center", valign="center")
        )
        plate = plate.cut(label)
    return plate


def main() -> None:
    OUT.mkdir(exist_ok=True)
    model = build()
    if not model.val().isValid():
        raise RuntimeError("fit coupon solid is invalid")
    step_path = OUT / "sma_hole_fit_coupon.step"
    stl_path = OUT / "sma_hole_fit_coupon.stl"
    exporters.export(model, str(step_path))
    exporters.export(model, str(stl_path), tolerance=0.08, angularTolerance=0.1)
    reopened = importers.importStep(str(step_path))
    if not reopened.val().isValid():
        raise RuntimeError("reopened fit coupon STEP is invalid")
    expected_radii = {round(d / 2, 3) for d in PARAMETERS["hole_diameters"]}
    exported_holes = sorted(
        (round(edge.Center().x, 3), round(edge.radius() * 2, 3))
        for edge in reopened.val().Edges()
        if edge.geomType() == "CIRCLE"
        and round(edge.radius(), 3) in expected_radii
        and abs(edge.Center().z - PARAMETERS["thickness"]) < 0.01
    )
    if len(exported_holes) != len(PARAMETERS["hole_diameters"]):
        raise RuntimeError(f"expected {len(PARAMETERS['hole_diameters'])} distinct top-hole circles, got {exported_holes}")
    result = {
        "purpose": "Mechanical printed-hole trial coupon only; not an MF650 shell or RF validation fixture.",
        "parameters": PARAMETERS,
        "outputs": {"step": str(step_path), "stl": str(stl_path)},
        "cad_valid": bool(model.val().isValid()),
        "reopened_step_valid": bool(reopened.val().isValid()),
        "volume_mm3": round(float(model.val().Volume()), 3),
        "hole_count": len(PARAMETERS["hole_diameters"]),
        "reopened_step_top_holes_x_and_diameter_mm": exported_holes,
    }
    (OUT / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    # See source_analysis/analyze_source.py for the Windows CadQuery teardown
    # workaround. All outputs are synchronously closed before this call.
    os._exit(0)


if __name__ == "__main__":
    main()
