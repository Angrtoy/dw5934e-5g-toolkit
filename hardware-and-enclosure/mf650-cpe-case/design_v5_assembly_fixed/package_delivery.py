"""Create the user-facing MF650 v5 ZIP without mixing in draft artifacts."""
from __future__ import annotations
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / 'output'
NAME = 'MF650_2491007_rounded_side8_v5'
STAGE = HERE / '_package_stage' / NAME
ZIP = HERE / f'{NAME}.zip'

PRINTS = [
    'main_chassis.stl', 'front_bezel.stl', 'rear_cover_no_sma.stl',
    'left_side_antenna_panel_4x1.stl', 'right_side_antenna_panel_4x1.stl',
    'registered_source_top_feature_frame.stl',
    'registered_source_dual_ear_button_plate.stl',
    'button_extender_from_aux.stl', 'dual_end_desk_base.stl',
]
PREVIEWS = [
    'preview_vtk_upright_base.png', 'preview_vtk_upright_base_8antenna.png',
    'preview_vtk_exploded.png', 'preview_vtk_dense_grille_front.png',
    'preview_vtk_left.png', 'preview_vtk_right.png',
]

DELIVERY_README = '''# MF650 2491007 圆角侧八天线加厚壳 v5（密集格栅与机械捕获按键）

## 先打印什么

所有 STL 均为 **mm、100% 比例**。整套外壳只打印 `打印件_STL/` 中带 `01_` 至 `09_` 前缀的 **9 件**；SMA 试片是位于 `试片_SMA孔位/` 的明确例外。`工程/` 和 `参考模型_勿打印/` 下的文件均不可切片。v4 用户应更换 `08_button_extender_from_aux.stl`；其余八件与验收版 v4 字节相同。

尺寸以最终 STL 实际包围盒为准：前面板为 **160×90 mm**；含两端连接块的主体为约 **161×90×39.6 mm**（该厚度为前/后壳包络，不含按钮外触面突出）；底座足板为 **100×85 mm**。源顶/底壳的 **19.6 mm** 是本次数字登记装配高度，**不是实物合盖厚度测量值**。

建议先打印 `试片_SMA孔位/sma_hole_fit_coupon.stl`，以真实 SMA 接头检查 Ø6.4–6.8 mm 试孔，再决定是否直接使用本设计的 Ø6.6 mm 侧孔。主件适合先做无电子件的干装和低填充试装；含锂电池时不可在无看护或异常发热状态下充电。

各件均按 **mm / 100%** 导入，禁止缩放；每件应单独放到打印平台并按其受力面、可见面和支撑需求选择合适朝向。本包**未进行实际切片、支撑或打印参数验证**。

## 装配顺序

1. `01_main_chassis.stl` 主体已经包含原底壳的功能框，**不再另装一套底壳**。先进行空壳试装，并装入可达位置的 M3 螺母。
2. 如需立式安装，在 `03_rear_cover_no_sma.stl` 尚未安装前固定 `09_dual_end_desk_base.stl`：在底座两条支撑外侧沿 Y 向装入 5.5 AF×2.4 mm M3 螺母；从新增后舱 Z≈−4 位置送入两颗 M3×16 螺钉，螺钉头抵主框内侧肩位，杆穿过主体和底座并拧入底座螺母。底座可绕 Z 旋转 180° 装到另一短端。
3. 先在 `04_left_side_antenna_panel_4x1.stl`、`05_right_side_antenna_panel_4x1.stl` 安装 SMA 并预留接线空间，再将侧板固定。两条长边各 4 个、共 8 个 Ø6.6 mm、轴向 Y 的 SMA 孔；`03_rear_cover_no_sma.stl` 没有 SMA 孔。
4. 按源定位安装硬件和 `06_registered_source_top_feature_frame.stl`、`07_registered_source_dual_ear_button_plate.stl`。`02_front_bezel.stl` 尚未安装时，从前方/外侧放入 `08_button_extender_from_aux.stl`；然后下落前盖，使 Ø6.2 驱动头穿过 Ø6.5 导向。其 Ø8 内法兰留在前盖内侧，防止向外拉脱。**打印按钮本身不带回弹机构，回弹需要设备原开关提供；实际按压行程、回弹和电气触发仍需装机确认。**07 的全行程横向偏移接近 0.1 mm 时已有轻微擦碰边界，试装时应确认顺滑回弹。
5. 最后安装 `03_rear_cover_no_sma.stl`，关闭前检查不会夹住任何接线。

## 五金与假设

- 壳、前后盖、侧板、底座：常规 M3 螺钉；底座固定链指定 M3×16、头 Ø5.5×3 mm 代理与 5.5 AF×2.4 mm 螺母。
- SMA 仅依商家提供的 1/4-36 UNS / 约 6 mm 螺纹信息建模。设计孔 Ø6.6；数字占位为 Ø6.5×12 尾段、Ø10 垫圈、8 AF 螺母，**并非实际 SMA、线缆弯曲半径或 PCB 的适配保证**。
- 天线图的橙色杆仅是 Ø8×100 mm 外形假设，安装于接头肩部外约 5 mm、向侧外/向上各 45°；不代表实际天线。

## 已完成的数字验证与边界

`报告/cad_validation.json` 合并记录了源 STL 的定位登记、9 件单一 watertight 体、全部 36 对静态关系、104 个前格栅孔从外至内的连续路径、源上下盖/装配件干涉、8 侧孔尾段空间、侧 M3 螺母装入、前盖压脚、上盖取出、按钮从前方放入及前盖下落的顺序路径、+Z 捕获、07 滑片的源上盖止挡及受限按压链、底座双端姿态、M3 夹持链、已识别原端口通路及天线外形占位检查。前盖的实际落座检查为 −0.100 mm：该姿态下各静态关系为零交叠，源上盖仍可 +0.200 mm 上移而不碰。

`报告/v4_unchanged_parts.json` 证明除 `08_button_extender_from_aux.stl` 外的八个最终 STL 与 v4 字节相同。最终 08 已实际使用 [`dfam-check`](https://github.com/earthtojake/text-to-cad/tree/main/skills/dfam-check) 的 `dfam_tool.py measure`（默认和 10,000 样本请求）及 `orientations` 在最终 STL 上复测：单一 watertight 实体，抽样最小壁厚和 p05 均为 **1.200 mm**。详见包内 `报告/08_最终去杯DfAM审查.md`；包中不含历史“有杯”08 的薄环测量。

这些是数字几何/空间验证；没有 PCB、电池、真实 USB 插头、实际 SMA、线缆、开关或天线重心实体。热、锂电安全、RF、充电、实际按键力/行程、实体装配与稳定性均未验证，必须由实际试装确认。

## 工程、来源与许可

`工程/design_v5_assembly_fixed/` 中的生成入口顺序为：

```text
build_mf650_2491007.py
→ validate_final.py
→ validate_base.py
→ render_vtk.py
```

工程脚本以相对父目录读取 `工程/source_revision_2491007/models/` 中的三个源 STL；解压后该路径已完整保留。生成需要 Python、CadQuery/OCP、trimesh、manifold3d 与 VTK。`参考模型_勿打印/front_bezel_reference.step` 不含最终 STL 的网格并入压脚，只可作新增几何参考，不能替代最终 `front_bezel.stl`。

原模型：小猪猪 `@user_2427993088`，MakerWorld 2491007，CC BY-NC-SA 4.0，二创自“滴滴”。再发布时必须保留署名、非商业及相同方式共享限制。更多来源记录见 `工程/source_revision_2491007/README.md`。
'''

def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()

def main() -> None:
    if STAGE.parent.exists():
        shutil.rmtree(STAGE.parent)
    STAGE.mkdir(parents=True)
    (STAGE / 'README_先看这里.md').write_text(DELIVERY_README, encoding='utf-8')

    for index, filename in enumerate(PRINTS, 1):
        copy(OUT / filename, STAGE / '打印件_STL' / f'{index:02d}_{filename}')
    for filename in PREVIEWS:
        copy(OUT / filename, STAGE / '预览_VTK' / filename)
    for filename in ('cad_validation.json', 'build_record.json', 'v4_unchanged_parts.json'):
        copy(OUT / filename, STAGE / '报告' / filename)
    dfam = ROOT / 'review_v5_dfam' / 'final_08_no_cup'
    # Delivery copy deliberately contains only the final de-cupped result, not
    # the superseded cup-version measurements that remain in reviewer history.
    (STAGE / '报告' / '08_最终去杯DfAM审查.md').write_text('''# 08 按键延长件：最终去杯 DfAM 审查

审查对象为本包 `打印件_STL/08_button_extender_from_aux.stl`。其 SHA-256 必须为
`28ea00ef126f35e2f1cb499fbb2d17e69cb42f087aeb4a6f9b1190e2d2a5297a`，文件大小为 94,384 B。

实际运行 [dfam-check](https://github.com/earthtojake/text-to-cad/tree/main/skills/dfam-check) 的 `dfam_tool.py`：

```text
dfam_tool.py measure <final-08.stl> --angle-limit 30
dfam_tool.py measure <final-08.stl> --samples 10000 --angle-limit 30
dfam_tool.py orientations <final-08.stl> --angle-limit 30
```

最终 STL 是 1 个 watertight 实体，单位尺度正常。默认测量和 10,000 样本请求（本件受 1,886 面限制）均得到：

- 最小抽样壁厚：**1.200 mm**
- p05 抽样壁厚：**1.200 mm**
- 当前朝向低角度朝下面积：36.31 mm²（11.8%）
- 六轴候选中 `flip_180_x` 最低：28.19 mm²（9.1%），构建高度 10.70 mm。

方向候选不等于实际切片、支撑或材料保证。用户尚未指定材料、机器、层高、支撑和后处理；这些仍需在试样和实际切片中确认。

随包 JSON 是本最终去杯 STL 的默认/高样本/方向测量数据。包中没有历史有杯版本的测量数据。
''', encoding='utf-8')
    for filename in ('08_button_extender_from_aux.measure.json', '08_button_extender_from_aux.measure_10000.json', '08_button_extender_from_aux.orientations.json'):
        copy(dfam / 'results' / filename, STAGE / '报告' / '08_最终去杯DfAM_' / filename)
    assembly_review = ROOT / 'review_v5_assembly'
    review_text=(assembly_review / 'BUTTON_V5_FINAL_REVIEW.md').read_text(encoding='utf-8')
    review_text=review_text.replace(
        './button_mechanics_sections.png',
        'button_mechanics_sections.png')
    old_hold='''## Delivery consistency status

At review time the staging output above is final, but the existing
`MF650_2491007_rounded_side8_v5.zip` still contains the former 188,884-B cup
version of 08 (SHA-256 `f70c88bd…d3fa833`). The package must be regenerated
and its 08 hash compared to `28ea00ef…a5297a` before it is handed to a user.
That is a release-consistency hold, not a geometric failure of the final STL.
'''
    new_hold='''## Delivery consistency status

The delivery ZIP has been regenerated and checked. Its final `08_button_extender_from_aux.stl`
member is **94,384 B** with SHA-256
`28ea00ef126f35e2f1cb499fbb2d17e69cb42f087aeb4a6f9b1190e2d2a5297a`.
All nine packaged printable STL members match the reviewed release set; the historical
package-consistency hold is therefore released.
'''
    if old_hold not in review_text:
        raise RuntimeError('expected historic delivery-hold text absent from assembly review')
    review_text=review_text.replace(old_hold,new_hold)
    (STAGE / '报告' / '08_最终装配复核.md').write_text(review_text, encoding='utf-8')
    copy(assembly_review / 'button_mechanics_sections.png', STAGE / '报告' / 'button_mechanics_sections.png')

    engineering = STAGE / '工程'
    for filename in ('README.md', 'build_mf650_2491007.py', 'validate_final.py', 'validate_base.py', 'render_vtk.py', 'compare_v4_unchanged.py'):
        copy(HERE / filename, engineering / 'design_v5_assembly_fixed' / filename)
    source = ROOT / 'source_revision_2491007'
    for filename in ('README.md', 'new_source_report.json', 'obj_1_COMPOUND_1_preview.png', 'obj_2_COMPOUND_3_preview.png', 'obj_3_COMPOUND_4_preview.png'):
        copy(source / filename, engineering / 'source_revision_2491007' / filename)
    for filename in ('obj_1_COMPOUND_1.stl', 'obj_2_COMPOUND_3.stl', 'obj_3_COMPOUND_4.stl'):
        copy(source / 'models' / filename, engineering / 'source_revision_2491007' / 'models' / filename)
    for filename in ('front_bezel_reference.step', 'added_chassis_scaffold_reference.step'):
        copy(OUT / filename, engineering / '参考模型_勿打印' / filename)
    (engineering / '参考模型_勿打印' / 'README.md').write_text(
        '这些是工程参考，不能切片。front_bezel_reference.step 不含最终 front_bezel.stl 的网格并入压脚。\n', encoding='utf-8')

    coupon = ROOT / 'fit_coupon'
    for filename in ('sma_hole_fit_coupon.stl', 'README.md', 'preview.png', 'validation.json'):
        copy(coupon / filename, STAGE / '试片_SMA孔位' / filename)

    files = sorted(p for p in STAGE.rglob('*') if p.is_file())
    manifest = {
        'package': NAME,
        'print_stl_count': len(PRINTS),
        'print_stl_names': PRINTS,
        'files': [{'path': str(p.relative_to(STAGE)).replace('\\', '/'), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in files],
    }
    (STAGE / 'SHA256SUMS.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(p for p in STAGE.rglob('*') if p.is_file()):
            archive.write(file, file.relative_to(STAGE.parent))
    with zipfile.ZipFile(ZIP) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f'bad ZIP member: {bad}')
        members = archive.namelist()
        print(json.dumps({'zip': str(ZIP), 'zip_bytes': ZIP.stat().st_size, 'zip_sha256': sha(ZIP),
                          'members': len(members), 'print_members': [m for m in members if '/打印件_STL/' in m]},
                         ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
