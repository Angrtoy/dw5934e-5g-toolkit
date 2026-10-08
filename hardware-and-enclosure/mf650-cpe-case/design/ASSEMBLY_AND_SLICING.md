# 生产前清单

先打印 `../fit_coupon`，用实际 SMA 确认 Ø6.6 mm 孔。默认孔径位于
`build_mf650_cpe.py` 的 `P["sma_diameter"]`；“6 mm 螺纹直径”不是已知穿板长度。

硬件为 10 颗 M3 螺栓与 10 颗 M3 六角螺母：前后板各四颗，底座两颗。螺栓长度应
先由实际打印件、螺母和垫片堆叠测量选定，确保螺纹吃满螺母且不进入电池/PCB 区。

完整顺序、捕获槽方向与边界见 [README.md](README.md)。`output/` 中 STEP/STL
与 `cad_validation.json` 均由同一脚本本次导出生成。
