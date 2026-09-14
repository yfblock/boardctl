"""source 执行插件:把加载的 uImage 脚本当 U-Boot 命令序列执行,结束回提示符"""

NAME = 'source'


def build_cmd(addr):
    return f'source {addr}'
