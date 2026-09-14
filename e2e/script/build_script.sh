#!/bin/sh
# 把 test_uboot.txt 包成 U-Boot legacy uImage script 镜像
# (该构建的 `source` 只接受带镜像头的脚本,纯文本会报 Wrong image format)
set -e
cd "$(dirname "$0")"
mkimage -A riscv -T script -C none -n 'sg2002-test' -d test_uboot.txt test_uboot.scr
echo "--- 校验 ---"
mkimage -l test_uboot.scr
