"""go 执行插件:跳转到加载地址执行裸机代码(不保证返回,程序常以死循环结束)"""

NAME = 'go'


def build_cmd(addr, t=None):
    return f'go {addr}'
