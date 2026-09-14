#!/bin/sh
# 构建 SG2002 裸机测试: hello.S -> hello.elf -> hello.bin(flat, 链接于 0x80080000)
set -e
cd "$(dirname "$0")"
P=riscv64-linux-gnu

$P-gcc -march=rv64imac -mabi=lp64 -mcmodel=medany \
       -fno-pie -fno-pic -no-pie \
       -nostdlib -static -Ttext=0x80080000 -Wl,--build-id=none \
       -o hello.elf hello.S
# 只导出 .text(build-id 等 NOTE 段地址很低,会把 flat binary 撑到 GB 级)
$P-objcopy -O binary -j .text hello.elf hello.bin
$P-objdump -d hello.elf > hello.dis

ls -l hello.bin
echo "--- 入口 ---"
$P-readelf -h hello.elf | grep Entry
