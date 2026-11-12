"""造梦西游4活动工具箱统一入口。

开发运行：python run.py
打包构建：PyInstaller 以本文件为入口，业务代码仍在 zm4_toolbox.py。
"""
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    if not getattr(sys, "frozen", False):
        # 允许从任意目录启动，模块和配置都按本文件所在目录解析。
        os.chdir(APP_DIR)
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    import zm4_toolbox
    zm4_toolbox.main()


if __name__ == "__main__":
    main()
