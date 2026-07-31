import argparse
import re
import sys


def configure_utf8_output():
    """确保被 Hermes 捕获的中文脚本输出在各平台都使用 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            continue


def _translate_error(message):
    required = re.fullmatch(r"the following arguments are required: (.+)", message)
    if required:
        return "缺少必需参数：{}".format(required.group(1))

    unrecognized = re.fullmatch(r"unrecognized arguments: (.+)", message)
    if unrecognized:
        return "无法识别的参数：{}".format(unrecognized.group(1))

    argument = re.fullmatch(r"argument (.+?): (.+)", message)
    if argument:
        detail = argument.group(2)
        detail = detail.replace("invalid choice", "无效选项")
        detail = detail.replace("choose from", "可选值")
        detail = detail.replace("expected one argument", "需要一个值")
        return "参数 {}：{}".format(argument.group(1), detail)

    return message


class ChineseArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._positionals.title = "位置参数"
        self._optionals.title = "参数"

    def format_help(self):
        help_text = super().format_help()
        replacements = {
            "usage:": "用法：",
            "positional arguments:": "位置参数：",
            "optional arguments:": "参数：",
            "options:": "参数：",
            "show this help message and exit": "显示帮助并退出",
        }
        for source, target in replacements.items():
            help_text = help_text.replace(source, target)
        help_text = help_text.replace("参数:\n", "参数：\n")
        help_text = help_text.replace("）:\n", "）：\n")
        return help_text

    def format_usage(self):
        return super().format_usage().replace("usage:", "用法：")

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "{}: 错误：{}\n".format(self.prog, _translate_error(message)))
