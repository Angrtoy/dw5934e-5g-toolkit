"""Full-triangle VTK previews; no face sampling or hand-drawn substitute."""
from __future__ import annotations
import math
import os
from pathlib import Path
import vtk

OUT = Path(__file__).resolve().parent / 'output'
COL = {
    'main_chassis': (.07, .11, .17),
    'registered_source_top_feature_frame': (.22, .31, .41),
    'front_bezel': (.78, .81, .85),
    'rear_cover_no_sma': (.12, .17, .24),
    'left_side_antenna_panel_4x1': (.11, .16, .23),
    'right_side_antenna_panel_4x1': (.11, .16, .23),
    'registered_source_dual_ear_button_plate': (.92, .30, .05),
    'dual_end_desk_base': (.17, .24, .34),
    'button_extender_from_aux': (.92, .30, .05),
}

def actor(name, shift=(0, 0, 0)):
    reader = vtk.vtkSTLReader(); reader.SetFileName(str(OUT / f'{name}.stl')); reader.Update()
    mapper = vtk.vtkPolyDataMapper(); mapper.SetInputConnection(reader.GetOutputPort())
    result = vtk.vtkActor(); result.SetMapper(mapper); result.SetPosition(*shift)
    result.GetProperty().SetColor(*COL[name]); result.GetProperty().SetInterpolationToPhong()
    result.GetProperty().SetSpecular(.18); result.GetProperty().SetSpecularPower(28)
    return result

def cylinder_y(x, y, z, length=12, radius=3.25, opacity=1):
    source = vtk.vtkCylinderSource(); source.SetRadius(radius); source.SetHeight(length); source.SetResolution(36); source.CappingOn(); source.Update()
    mapper = vtk.vtkPolyDataMapper(); mapper.SetInputConnection(source.GetOutputPort())
    result = vtk.vtkActor(); result.SetMapper(mapper); result.RotateX(90); result.SetPosition(x, y, z)
    result.GetProperty().SetColor(.88, .39, .06); result.GetProperty().SetOpacity(opacity)
    return result

def antenna(x, side):
    """100-mm occupancy proxy beginning at its actual external side SMA plane."""
    source = vtk.vtkCylinderSource(); source.SetRadius(4); source.SetHeight(100); source.SetResolution(28); source.CappingOn(); source.Update()
    mapper = vtk.vtkPolyDataMapper(); mapper.SetInputConnection(source.GetOutputPort())
    result = vtk.vtkActor(); result.SetMapper(mapper)
    # +X is lower/groundward in this view, so -X is visually upward. Each bank
    # is parallel; banks mirror outward in Y. This is only a Ø8 x 100 assumption.
    direction = (-math.sqrt(.5), side * math.sqrt(.5), 0.0)
    # 5 mm exterior connector shoulder before the flexible antenna proxy.
    start = (x, side * 50.0, -3.5)
    # vtkCylinderSource is aligned with +Y. This axis-angle maps +Y to direction.
    angle = math.degrees(math.acos(max(-1.0, min(1.0, direction[1]))))
    result.RotateWXYZ(angle, 0.0, 0.0, -direction[0])
    result.SetPosition(*(start[i] + 50 * direction[i] for i in range(3)))
    result.GetProperty().SetColor(.86, .42, .08); result.GetProperty().SetSpecular(.2)
    return result

def screen():
    source = vtk.vtkCubeSource(); source.SetXLength(47); source.SetYLength(39); source.SetZLength(.35); source.SetCenter(-5, -1, 26.82); source.Update()
    mapper = vtk.vtkPolyDataMapper(); mapper.SetInputConnection(source.GetOutputPort())
    result = vtk.vtkActor(); result.SetMapper(mapper); result.GetProperty().SetColor(.015, .025, .04)
    return result

def render(name, view, explode=False, base=False, antennas=True):
    renderer = vtk.vtkRenderer(); renderer.SetBackground(.93, .95, .98)
    explode_shift = {
        'front_bezel': (0, 0, 10), 'rear_cover_no_sma': (0, 0, -8),
        'left_side_antenna_panel_4x1': (0, -12, 0), 'right_side_antenna_panel_4x1': (0, 12, 0),
        'dual_end_desk_base': (-20, 0, -14),
    } if explode else {}
    for component in COL:
        if component == 'dual_end_desk_base':
            if base or explode:
                renderer.AddActor(actor(component, explode_shift.get(component, (0, 0, 0))))
        else:
            renderer.AddActor(actor(component, explode_shift.get(component, (0, 0, 0))))
    if not explode:
        renderer.AddActor(screen())
        for side in (-1, 1):
            for x in (-51, -17, 17, 51):
                renderer.AddActor(cylinder_y(x, side * 39.1, -3.5, 12, 3.25, .9))
        if base and antennas:
            for side in (-1, 1):
                for x in (-51, -17, 17, 51):
                    renderer.AddActor(antenna(x, side))
    window = vtk.vtkRenderWindow(); window.SetOffScreenRendering(1); window.SetSize(1800, 1400); window.AddRenderer(renderer)
    renderer.ResetCamera()
    camera = renderer.GetActiveCamera(); camera.ParallelProjectionOn(); camera.SetFocalPoint(-5, 0, 10)
    # About 15% extra scale leaves a visible margin around the highest antenna.
    camera.SetParallelScale(104 if explode else (167 if base else 76))
    if view == 'front':
        camera.SetPosition(0, 0, 360); camera.SetViewUp(0, 1, 0)
    elif view == 'left':
        camera.SetPosition(0, -360, 4); camera.SetViewUp(0, 0, 1)
    elif view == 'right':
        camera.SetPosition(0, 360, 4); camera.SetViewUp(0, 0, 1)
    else:
        camera.SetPosition(185, -300, 260)
        # Native long axis is upright: +X points toward the foot/ground.
        camera.SetViewUp(-1, 0, 0) if base else camera.SetViewUp(0, 0, 1)
    renderer.ResetCameraClippingRange(); window.Render()
    grab = vtk.vtkWindowToImageFilter(); grab.SetInput(window); grab.Update()
    png = vtk.vtkPNGWriter(); png.SetFileName(str(OUT / name)); png.SetInputConnection(grab.GetOutputPort()); png.Write()

def main():
    render('preview_vtk_front.png', 'front')
    render('preview_vtk_dense_grille_front.png', 'front')
    render('preview_vtk_left.png', 'left')
    render('preview_vtk_right.png', 'right')
    render('preview_vtk_assembled.png', 'perspective')
    render('preview_vtk_exploded.png', 'perspective', True)
    render('preview_vtk_upright_base_8antenna.png', 'perspective', base=True)
    render('preview_vtk_upright_base.png', 'perspective', base=True, antennas=False)
    print('full-triangle VTK previews written', flush=True)
    os._exit(0)

if __name__ == '__main__':
    main()
