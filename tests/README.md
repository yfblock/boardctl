# SG2002 上板测试

两套测试,验证 boardctl 工具链(传输 → 执行 → 串口回读)端到端一致。

## 1. 裸机测试(tests/baremetal/)

RISC-V 汇编,链接于 0x80080000,通过 UART0 打印五行标记后 `wfi` 死循环。
UART0 是 **Synopsys DW APB UART**(设备树 `reg-shift=<2>`, `reg-io-width=<4>`):
寄存器步长 4 字节,LSR 在 `base+0x14` 且必须 32 位读;THR 在 `base+0`,字节写可行
(U-Boot `mw.b 0x04140000 0x41` 实证)。构建:

    cd tests/baremetal && ./build.sh        # 产出 hello.bin(约 178 字节)

构建要点(踩过的坑,改动前先看):
- `-fno-pie -fno-pic -no-pie`:该工具链默认 PIE,否则 `la` 会变成 GOT 间接寻址,
  GOT 不在 .text 里,flat binary 上板即崩
- `-Wl,--build-id=none` + `objcopy -j .text`:否则 build-id NOTE 段(低地址)会把
  flat binary 零填充撑到 ~2GB
- 所有字符串放在 .text 内,保证 binary 连续无空洞

部署与验证(主会话执行):

    ./.venv/bin/python boardctl.py -b sg2002 send tests/baremetal/hello.bin --method tftp --addr 0x80080000
    ./.venv/bin/python boardctl.py -b sg2002 cmd 'go 0x80080000'

期望输出见 EXPECTED.txt(五行 BM- 标记,行尾 \n)。打印完后设备死循环属预期,
恢复: `boardctl.py -b sg2002 reset`。

## 2. U-Boot 脚本测试(tests/script/)

U-Boot 命令脚本(echo 标记 + setenv 静默命令),包成 legacy uImage script 镜像后用
`source` 执行——注意:该构建的 `source` **不接受纯文本**(报 Wrong image format),
必须带 uImage 头;且该构建**没有 itest 命令**,脚本里只放必有命令。先构建:

    cd tests/script && ./build_script.sh        # test_uboot.txt -> test_uboot.scr

部署与验证(主会话执行,send 的对象是 .scr 不是 .txt):

    ./.venv/bin/python boardctl.py -b sg2002 send tests/script/test_uboot.scr --method tftp --addr 0x80080000
    ./.venv/bin/python boardctl.py -b sg2002 cmd 'source 0x80080000'

期望输出见 EXPECTED.txt(## Executing script 行 + 三行 SCRIPT- 标记 + 回到 soph#)。
镜像数据布局 = 64 字节 uImage 头 + 8 字节尺寸表(u32 长度 + NUL 终止)+ 脚本文本,
已对照 v2021.10 cmd/source.c 的 legacy 解析路径(uimage_to_cpu(*data) + while(*data++))
确认兼容;mkimage 版本差异不影响该布局(它一直是 multi-image 尺寸表格式)。

## 预期行为差异

| | 裸机测试 | 脚本测试 |
|---|---|---|
| 执行方式 | go 0x80080000 | source 0x80080000 |
| 结束状态 | 死循环,需 reset | 回到 soph# |
| 行尾 | \n | \r\n(U-Boot echo) |
| 附加输出 | 无 | "## Executing script at 80080000" |
