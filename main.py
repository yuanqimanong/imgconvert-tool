import logging
import os
import sys

from imgconvert import ImgConvert

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging():
    """打包成 EXE 后（--noconsole）sys.stderr 是 None，这时把日志写到程序旁边的文件"""
    if sys.stderr is not None:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
        return
    try:
        logging.basicConfig(
            level=logging.INFO,
            format=LOG_FORMAT,
            filename=os.path.join(os.path.dirname(sys.executable), "imgconvert.log"),
            encoding="utf-8",
        )
    except OSError:
        # 连日志都写不出来（比如装在只读目录）也不该拦着程序跑
        logging.disable(logging.CRITICAL)


if __name__ == "__main__":
    setup_logging()
    app = ImgConvert()
    app.mainloop()
