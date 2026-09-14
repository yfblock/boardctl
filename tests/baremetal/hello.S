/*
 * SG2002 裸机测试程序 —— 打印标记后死循环
 *
 * 入口: 0x80080000(U-Boot `go 0x80080000` 跳转到文件偏移 0)
 * UART0 基址 0x04140000,是 Synopsys DW APB UART(设备树 reg-shift=<2>):
 *   寄存器步长 4 字节:THR = base+0,LSR = base + (5<<2) = base+0x14,
 *   LSR 用 32 位读(reg-io-width=4);THR 字节写已被 U-Boot mw.b 实证可行
 * 全部代码和数据放在 .text,保证 objcopy 出的 flat binary 连续无空洞。
 */
    .section .text, "ax"
    .globl _start

_start:
    li      sp, 0x82000000        # 栈指针指向 DDR 安全区(实际未压栈,仅防御)

    la      a0, msg_start
    call    puts
    la      a0, msg_c1
    call    puts
    la      a0, msg_c2
    call    puts
    la      a0, msg_c3
    call    puts
    la      a0, msg_done
    call    puts

1:  wfi                             # 打印完毕: 死循环(预期行为,恢复需断电重启)
    j       1b

# ---- 打印 NUL 结尾字符串(a0 = 指针),t0 = UART 基址 ----
puts:
    li      t0, 0x04140000
.Lnext:
    lbu     t1, 0(a0)
    beqz    t1, .Lret
.Lwait:
    lw      t2, 0x14(t0)           # LSR = base + (5<<2),DW APB 32 位访问
    andi    t2, t2, 0x20           # bit5: THR 空
    beqz    t2, .Lwait
    sb      t1, 0(t0)              # THR(base+0)
    addi    a0, a0, 1
    j       .Lnext
.Lret:
    ret

# ---- 标记字符串(严格确定格式,行尾 \n,不含 \r)----
msg_start:
    .asciz  "BM-TEST-START\n"
msg_c1:
    .asciz  "BM-COUNTER-1\n"
msg_c2:
    .asciz  "BM-COUNTER-2\n"
msg_c3:
    .asciz  "BM-COUNTER-3\n"
msg_done:
    .asciz  "BM-TEST-DONE\n"
