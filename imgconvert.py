import logging
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from tkinter import (
    Tk,
    Canvas,
    Frame,
    Menu,
    messagebox,
    filedialog,
    font as tkfont,
    ttk,
    Label,
    Entry,
    StringVar,
    BooleanVar,
    DISABLED,
    NORMAL,
    FLAT,
    LEFT,
    RIGHT,
    X,
    BOTH,
)

from convertutil import ConvertError, ConvertUtil

VERSION = "2.1"
GITHUB_URL = "https://github.com/yuanqimanong/imgconvert-tool"
MIN_WIDTH = 660

logger = logging.getLogger(__name__)

# 配色：扁平、单一强调色、克制的灰阶
BG = "#F4F6F9"
CARD = "#FFFFFF"
FIELD = "#F7F9FC"
BORDER = "#E1E5EB"
TEXT = "#1D2129"
LABEL = "#5F6672"
MUTED = "#8A9099"
ACCENT = "#2F6FED"
ACCENT_HOVER = "#2560D6"
ACCENT_PRESSED = "#1F51B5"
ACCENT_LIGHT = "#B8CCF7"
TROUGH = "#E9EDF3"
SUCCESS = "#1B9C57"
DANGER = "#D93F4C"

# 优先用系统自带的现代无衬线字体，Windows/macOS/Linux 依次回退
FONT_CANDIDATES = (
    "Microsoft YaHei UI",
    "微软雅黑",
    "PingFang SC",
    "Helvetica Neue",
    "Segoe UI",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "Droid Sans Fallback",
    "DejaVu Sans",
)


def pick_font_family(root):
    """挑一个当前系统真的装了的字体，挑不到就用 Tk 默认"""
    available = set(tkfont.families(root))
    for family in FONT_CANDIDATES:
        if family in available:
            return family
    return tkfont.nametofont("TkTextFont").actual("family")


def round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    """Canvas 没有圆角矩形，用平滑多边形模拟"""
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1,
        x2, y1 + radius, x2, y2 - radius, x2, y2,
        x2 - radius, y2, x1 + radius, y2, x1, y2,
        x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundedButton(Canvas):
    """圆角扁平按钮，带 hover / pressed / disabled 四态"""

    def __init__(
        self,
        master,
        text,
        command,
        font,
        width=124,
        height=40,
        radius=10,
        fill=ACCENT,
        hover=ACCENT_HOVER,
        pressed=ACCENT_PRESSED,
        disabled=ACCENT_LIGHT,
        fg=CARD,
        disabled_fg="#F0F4FD",
        outline="",
        parent_bg=BG,
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=parent_bg,
            cursor="hand2",
        )
        self.command = command
        self._colors = {
            "normal": fill,
            "hover": hover,
            "pressed": pressed,
            "disabled": disabled,
        }
        self._fg = fg
        self._disabled_fg = disabled_fg
        self._enabled = True
        self._shape = round_rect(
            self, 1, 1, width - 1, height - 1, radius, fill=fill, outline=outline
        )
        self._text = self.create_text(
            width / 2, height / 2, text=text, fill=fg, font=font
        )
        self.bind("<Enter>", lambda _e: self._paint("hover"))
        self.bind("<Leave>", lambda _e: self._paint("normal"))
        self.bind("<ButtonPress-1>", lambda _e: self._paint("pressed"))
        self.bind("<ButtonRelease-1>", self._on_release)

    def _paint(self, state):
        if not self._enabled:
            return
        self.itemconfig(self._shape, fill=self._colors[state])

    def _on_release(self, event):
        if not self._enabled:
            return
        self._paint("hover")
        # 只有松手时鼠标还在按钮上才算点击，和常规按钮行为一致
        if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def configure(self, **kwargs):
        """接住 state / text 自己处理，其余选项交给 Canvas"""
        if not kwargs:  # 无参调用是查询用法，别把返回值吞掉
            return super().configure()
        state = kwargs.pop("state", None)
        text = kwargs.pop("text", None)
        if state is not None:
            self._enabled = state == NORMAL
            self.itemconfig(
                self._shape,
                fill=self._colors["normal" if self._enabled else "disabled"],
            )
            self.itemconfig(
                self._text, fill=self._fg if self._enabled else self._disabled_fg
            )
            self.config(cursor="hand2" if self._enabled else "")
        if text is not None:
            self.itemconfig(self._text, text=text)
        if kwargs:
            super().configure(**kwargs)

    config = configure

    def __getitem__(self, key):
        if key == "state":
            return NORMAL if self._enabled else DISABLED
        return super().__getitem__(key)


class ImgConvert(Tk):
    def __init__(self):
        super().__init__()
        self.file_path = StringVar()
        self.status_text = StringVar(value="选择一个 PDF 文件后点击“开始转换”")
        self.keep_pages = BooleanVar(value=False)
        # 后台线程通过队列把结果回传给主线程，tkinter 只能在主线程里操作控件
        self.result_queue = queue.Queue()
        self.worker = None
        self.set_window()
        self.create_menu_bar()
        self.create_operating_area()
        self.center_window()

    def set_window(self):
        """设置窗口界面"""
        self.title("文档转图片工具")
        self.configure(bg=BG)

        self.font_family = pick_font_family(self)
        self.f_title = (self.font_family, 17, "bold")
        self.f_sub = (self.font_family, 10)
        self.f_body = (self.font_family, 10)
        self.f_small = (self.font_family, 9)
        self.f_button = (self.font_family, 11, "bold")
        self.init_styles()

        # 热键绑定
        self.bind("<Control-o>", self.open_file)
        self.bind("<Control-O>", self.open_file)
        self.bind("<Return>", lambda _e: self.convert_img())

    def center_window(self):
        """按控件实际需要的尺寸开窗并居中，换字体/换平台都不会裁掉内容"""
        self.update_idletasks()
        width = max(MIN_WIDTH, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        # 某些窗口管理器给出的可用区域会偏小，夹一下避免窗口跑到屏幕外
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 3)
        self.geometry("%dx%d+%d+%d" % (width, height, x, y))
        self.minsize(width, height)

    def init_styles(self):
        """ttk 默认主题太复古，换 clam 再手工配色"""
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "Modern.Horizontal.TProgressbar",
            troughcolor=TROUGH,
            background=ACCENT,
            bordercolor=TROUGH,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            borderwidth=0,
            thickness=6,
        )
        style.configure(
            "Modern.TCheckbutton",
            background=CARD,
            foreground=LABEL,
            font=self.f_small,
            focuscolor=CARD,
            indicatorbackground=CARD,
            indicatorforeground=ACCENT,
            bordercolor=BORDER,
            padding=2,
        )
        style.map(
            "Modern.TCheckbutton",
            background=[("active", CARD)],
            foreground=[("active", TEXT)],
            indicatorbackground=[("selected", ACCENT), ("!selected", CARD)],
            indicatorforeground=[("selected", CARD)],
            bordercolor=[("selected", ACCENT), ("!selected", BORDER)],
        )

    def create_menu_bar(self):
        """创建菜单项目"""
        menu_bar = Menu(self)
        # 添加菜单项目
        file_menu = Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="打开", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_separator()
        file_menu.add_command(label="退出", accelerator="Alt+F4", command=self.destroy)
        menu_bar.add_cascade(label="文件", menu=file_menu)

        about_menu = Menu(menu_bar, tearoff=0)
        about_menu.add_command(label="版本", command=lambda: self.show_messagebox("版本"))
        about_menu.add_command(label="帮助", command=lambda: self.show_messagebox("帮助"))
        about_menu.add_command(
            label="GitHub", command=lambda: self.show_messagebox("GitHub")
        )
        menu_bar.add_cascade(label="关于", menu=about_menu)

        self["menu"] = menu_bar

    def create_operating_area(self):
        """创建操作区：浅灰页面上放一张白色卡片，层级清楚一些"""
        content = Frame(self, bg=BG)
        content.pack(fill=BOTH, expand=True, padx=26, pady=(22, 18))

        Label(
            content, text="PDF 转长图", font=self.f_title, bg=BG, fg=TEXT, anchor="w"
        ).pack(fill=X)
        Label(
            content,
            text="把 PDF 的每一页竖向拼接，合成为一张图片",
            font=self.f_sub,
            bg=BG,
            fg=MUTED,
            anchor="w",
        ).pack(fill=X, pady=(5, 16))

        card = Frame(
            content, bg=CARD, highlightthickness=1, highlightbackground=BORDER
        )
        card.pack(fill=X)
        inner = Frame(card, bg=CARD)
        inner.pack(fill=X, padx=18, pady=16)

        Label(
            inner, text="PDF 文件", font=self.f_small, bg=CARD, fg=MUTED, anchor="w"
        ).pack(fill=X, pady=(0, 6))
        self.create_file_field(inner)

        actions = Frame(inner, bg=CARD)
        actions.pack(fill=X, pady=(16, 0))
        ttk.Checkbutton(
            actions,
            text="保留单页图片（tmp_images）",
            variable=self.keep_pages,
            style="Modern.TCheckbutton",
            takefocus=False,
        ).pack(side=LEFT, anchor="center")
        self.convert_button = RoundedButton(
            actions,
            text="开始转换",
            command=self.convert_img,
            font=self.f_button,
            parent_bg=CARD,
        )
        self.convert_button.pack(side=RIGHT)

        # 进度条的位置一直留着，避免转换开始时整个界面往下跳；
        # 但空闲时不画出来，免得多一条没有意义的灰色色块
        self.progress_holder = Frame(inner, bg=CARD, height=18)
        self.progress_holder.pack(fill=X, pady=(14, 0))
        self.progress_holder.pack_propagate(False)
        self.progress = ttk.Progressbar(
            self.progress_holder,
            style="Modern.Horizontal.TProgressbar",
            mode="determinate",
        )

        self.create_status_bar(content)

    def create_file_field(self, parent):
        """路径输入框 + 浏览按钮，外面套一层描边容器充当输入框边框"""
        field = Frame(
            parent,
            bg=FIELD,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        field.pack(fill=X)
        self.field = field

        entry = Entry(
            field,
            textvariable=self.file_path,
            font=self.f_body,
            bg=FIELD,
            fg=TEXT,
            relief=FLAT,
            bd=0,
            insertbackground=ACCENT,
            highlightthickness=0,
        )
        entry.pack(side=LEFT, fill=BOTH, expand=True, padx=(12, 8), pady=10)
        # 输入框获得焦点时整个容器描边变成强调色
        entry.bind("<FocusIn>", lambda _e: field.config(highlightbackground=ACCENT))
        entry.bind("<FocusOut>", lambda _e: field.config(highlightbackground=BORDER))

        self.path_button = RoundedButton(
            field,
            text="浏览",
            command=self.open_file,
            font=self.f_small,
            width=68,
            height=28,
            radius=8,
            fill=CARD,
            hover="#EDF2FC",
            pressed="#E1E9F8",
            disabled="#F6F7F9",
            fg=ACCENT,
            disabled_fg=MUTED,
            outline=BORDER,
            parent_bg=FIELD,
        )
        self.path_button.pack(side=RIGHT, padx=(0, 7), pady=7)

    def create_status_bar(self, parent):
        """状态行：一个小圆点 + 一句话，比纯文字更容易一眼看出状态"""
        bar = Frame(parent, bg=BG)
        bar.pack(fill=X, pady=(14, 0))
        self.status_dot = Canvas(
            bar, width=8, height=8, bg=BG, highlightthickness=0, bd=0
        )
        self._dot = self.status_dot.create_oval(0, 0, 8, 8, fill=MUTED, outline="")
        self.status_dot.pack(side=LEFT, pady=(4, 0))
        Label(
            bar,
            textvariable=self.status_text,
            font=self.f_small,
            bg=BG,
            fg=MUTED,
            anchor="w",
            justify=LEFT,
        ).pack(side=LEFT, fill=X, expand=True, padx=(8, 0))

    def set_status(self, text, color=MUTED):
        self.status_text.set(text)
        self.status_dot.itemconfig(self._dot, fill=color)

    """定义功能"""

    # 关于菜单
    def show_messagebox(self, _type):
        if _type == "GitHub":
            webbrowser.open(GITHUB_URL)
        if _type == "版本":
            messagebox.showinfo("版本", "Version - %s " % VERSION)
        if _type == "帮助":
            messagebox.showinfo(
                "帮助",
                "打开想要转换的”PDF文档“后，点击转换按钮即可在程序所在 ”out 目录“下 "
                "生成图片文件（勾选”保留单页图片“时，PDF 的单张图片会存在 tmp_images 目录）",
                icon="question",
            )

    # 打开文件
    def open_file(self, event=None):
        if self.worker and self.worker.is_alive():
            return
        # 打开文件并设置类型
        input_file = filedialog.askopenfilename(
            filetypes=[("PDF文件", "*.pdf"), ("所有文件", "*.*")]
        )
        if not input_file:
            return
        self.file_path.set(input_file)
        self.set_status("已选择 %s" % os.path.basename(input_file), ACCENT)
        logger.info("input_file ==> %s", input_file)

    # 转换文件
    def convert_img(self):
        if self.worker and self.worker.is_alive():
            return
        pdf_file_path = self.file_path.get().strip()
        if not pdf_file_path:
            self.set_status("请先选择一个 PDF 文件", DANGER)
            messagebox.showwarning(title="提示", message="请选择文件！")
            return

        self.set_busy(True)
        self.set_status("正在转换…", ACCENT)
        # 放到后台线程，否则大文档转换期间界面会整个卡住假死
        self.worker = threading.Thread(
            target=self.run_convert,
            args=(pdf_file_path, self.keep_pages.get()),
            daemon=True,
        )
        self.worker.start()
        self.after(100, self.poll_result)

    def run_convert(self, pdf_file_path, keep_pages):
        """后台线程：只做转换，结果丢进队列，不碰任何控件"""
        try:
            save_path = ConvertUtil().convert_img(
                pdf_file_path=pdf_file_path,
                keep_pages=keep_pages,
                progress=lambda done, total: self.result_queue.put(
                    ("progress", (done, total))
                ),
            )
            self.result_queue.put(("ok", save_path))
        except ConvertError as exc:
            self.result_queue.put(("fail", str(exc)))
        except Exception as exc:  # 兜底，避免线程里静默失败
            logger.exception("转换出现未预期的错误")
            self.result_queue.put(("error", str(exc)))

    def poll_result(self):
        """主线程：定时取队列消息，刷新界面"""
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "progress":
                    done, total = payload
                    self.progress.config(maximum=total, value=done)
                    self.set_status("正在转换… 第 %d / %d 页" % (done, total), ACCENT)
                    continue
                self.set_busy(False)
                if kind == "ok":
                    self.set_status("转换成功 · %s" % payload, SUCCESS)
                    self.show_success(payload)
                elif kind == "fail":
                    self.set_status(payload, DANGER)
                    messagebox.showwarning(title="转换结果", message=payload)
                else:
                    self.set_status("转换失败 · %s" % payload, DANGER)
                    messagebox.showerror(
                        "失败",
                        message="转换失败，请查看”菜单中的帮助说明“ 或 反馈Github寻求帮助\n\n%s"
                        % payload,
                    )
                return
        except queue.Empty:
            pass
        self.after(100, self.poll_result)

    def show_success(self, save_path):
        if messagebox.askyesno(
            title="转换结果", message="转换成功！\n\n%s\n\n是否打开所在目录？" % save_path
        ):
            self.open_in_file_manager(os.path.dirname(save_path))

    @staticmethod
    def open_in_file_manager(directory):
        try:
            if sys.platform == "win32":
                os.startfile(directory)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", directory])
            else:
                subprocess.Popen(["xdg-open", directory])
        except Exception:
            logger.exception("打开目录失败：%s", directory)

    def set_busy(self, busy):
        state = DISABLED if busy else NORMAL
        self.path_button.config(state=state)
        self.convert_button.config(state=state, text="转换中…" if busy else "开始转换")
        if busy:
            self.progress.config(maximum=100, value=0)
            self.progress.pack(fill=X, pady=(6, 0))
        else:
            self.progress.pack_forget()
