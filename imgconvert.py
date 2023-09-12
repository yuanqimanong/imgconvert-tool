import webbrowser
from tkinter import (
    Tk,
    Menu,
    messagebox,
    filedialog,
    Label,
    Button,
    Entry,
    StringVar,
    E,
    W,
)

from convertutil import ConvertUtil


class ImgConvert(Tk):
    def __init__(self):
        super().__init__()
        self.file_path = StringVar()
        self.set_window()
        self.create_menu_bar()
        self.create_operating_area()

    """设置窗口界面"""

    def set_window(self):
        self.title("文档转图片工具")
        max_width, max_height = self.maxsize()
        align_center = "620x80+%d+%d" % ((max_width - 620) / 2, (max_height - 80) / 3)
        self.geometry(align_center)
        # 热键绑定
        self.bind("<Control-O>", self.open_file)
        self.bind("<Control-o>", self.open_file)

    """创建菜单项目"""

    def create_menu_bar(self):
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

    """创建操作区"""

    def create_operating_area(self):
        path_label = Label(self, text="文件路径:", font=("微软雅黑", 12), fg="black")
        path_entry = Entry(
            self, font=("微软雅黑", 10), width=43, textvariable=self.file_path
        )
        path_button = Button(self, text="选择文件", width=10, command=self.open_file)
        convert_button = Button(self, text="转  换", width=10, command=self.convert_img)

        path_label.grid(row=0, column=1, padx=10, pady=20, sticky=W)
        path_entry.grid(row=0, column=2)
        path_button.grid(row=0, column=3, padx=3, pady=3, sticky=E)
        convert_button.grid(row=0, column=4, padx=3, pady=3, sticky=E)

    """定义功能"""

    # 关于菜单
    def show_messagebox(self, _type):
        if _type == "GitHub":
            webbrowser.open("https://github.com/yuanqimanong/imgconvert-tool")
        if _type == "版本":
            messagebox.showinfo("版本", "Version - 2.0 ")
        if _type == "帮助":
            messagebox.showinfo(
                "帮助",
                "打开想要转换的”PDF文档“后，点击转换按钮即可在程序所在 ”输出目录“下 生成图片文件（tmp_images是存放PDF单张图片的目录）",
                icon="question",
            )

    # 打开文件
    def open_file(self, event=None):
        # 打开文件并设置类型
        input_file = filedialog.askopenfilename(filetypes=[("PDF文件", "*.pdf")])
        self.file_path.set(input_file)
        print("input_file ==>", input_file)

    # 转换文件
    def convert_img(self):
        result = ConvertUtil().convert_img(pdf_file_path=self.file_path.get())
        print("result ==>", result)
        if "转换成功！" == result:
            messagebox.showinfo(title="转换结果", message=result)
        elif "转换失败！" == result:
            messagebox.showerror("失败", message=f"转换失败，请查看”菜单中的帮助说明“ 或 反馈Github寻求帮助")
        else:
            messagebox.showwarning(title="???", message=result)
