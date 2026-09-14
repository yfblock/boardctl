"""bootm 执行插件:引导 legacy uImage 镜像(头内自带入口/加载地址)

U-Boot 语法:bootm <addr> [initrd_addr] [fdt_addr](initrd/fdt 可选,经 run 目标的
initrd / fdt 键附加)
"""

NAME = 'bootm'


def build_cmd(addr, t=None):
    t = t or {}
    parts = [addr]
    if t.get('initrd'):
        parts.append(t['initrd'])
        if t.get('fdt'):
            parts.append(t['fdt'])
    return ' '.join(['bootm'] + parts)
