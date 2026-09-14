"""booti 执行插件:引导 Linux raw 内核镜像(Image,arm64/riscv)

U-Boot 语法:booti <kernel_addr> <initrd_addr|-> <fdt_addr>
run 目标附加键:
  fdt    = 设备树加载地址(必需,arm64/riscv 的 booti 必须给 FDT)
  initrd = initrd 加载地址(可选,缺省 '-' 表示无)
示例:
  [run.kernel]
  file = "Image"; exec = "booti"
  fdt = "0x83000000"; initrd = "0x82000000"
"""

import sys

NAME = 'booti'


def build_cmd(addr, t=None):
    t = t or {}
    fdt = t.get('fdt')
    if not fdt:
        sys.exit('booti 需要 run 目标提供 fdt = <设备树加载地址>(arm64/riscv 的 booti 必须给 FDT)')
    initrd = t.get('initrd', '-')
    return f'booti {addr} {initrd} {fdt}'
