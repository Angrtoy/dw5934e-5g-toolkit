# 禁止直接执行
本目录是审阅副本；每个 .reference.txt 的前两行是防执行封套：#!/bin/false 与 exit 126。直接执行由 /bin/false 拒绝；bash 在源内容前 exit 126；python 在源内容前产生 SyntaxError。ZIP 元数据为 0644；不要依赖 NTFS chmod。
