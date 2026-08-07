"""GUI 层测试：需要图形环境，没有 DISPLAY 时自动跳过。"""

import logging
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import convertutil  # noqa: E402
from test_convertutil import LETTER, make_pdf  # noqa: E402

try:
    import tkinter

    _probe = tkinter.Tk()
    _probe.destroy()
    HAS_DISPLAY = True
except Exception:  # 无 DISPLAY / 没装 tk
    HAS_DISPLAY = False


def setUpModule():
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)


class FakeMessagebox:
    """替掉真正的弹窗，否则测试会卡在模态对话框上"""

    def __init__(self):
        self.calls = []
        self.askyesno_result = False

    def showinfo(self, *args, **kwargs):
        self.calls.append(("showinfo", args, kwargs))

    def showwarning(self, *args, **kwargs):
        self.calls.append(("showwarning", args, kwargs))

    def showerror(self, *args, **kwargs):
        self.calls.append(("showerror", args, kwargs))

    def askyesno(self, *args, **kwargs):
        self.calls.append(("askyesno", args, kwargs))
        return self.askyesno_result

    def kinds(self):
        return [call[0] for call in self.calls]

    def texts(self):
        return [str(call[2].get("message", call[1])) for call in self.calls]


class FakeFileDialog:
    """替掉真正的文件选择框"""

    def __init__(self, result=""):
        self.result = result
        self.calls = []

    def askopenfilename(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


@unittest.skipUnless(HAS_DISPLAY, "没有图形环境，跳过 GUI 测试")
class ImgConvertGuiTestCase(unittest.TestCase):
    def setUp(self):
        import imgconvert

        self.imgconvert = imgconvert
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.out = os.path.join(self.tmp, "out")

        # GUI 不传 output_dir，靠改默认常量把产物导到临时目录
        self._orig_out = convertutil.DEFAULT_OUTPUT_DIR
        self._orig_pages = convertutil.DEFAULT_PAGES_DIR
        convertutil.DEFAULT_OUTPUT_DIR = self.out
        convertutil.DEFAULT_PAGES_DIR = os.path.join(self.tmp, "tmp_images")

        self.fake_box = FakeMessagebox()
        self.fake_dialog = FakeFileDialog()
        self._orig_box = imgconvert.messagebox
        self._orig_dialog = imgconvert.filedialog
        imgconvert.messagebox = self.fake_box
        imgconvert.filedialog = self.fake_dialog

        self.app = imgconvert.ImgConvert()
        self.app.withdraw()  # 不真的弹窗到屏幕上
        self.opened_dirs = []
        self.app.open_in_file_manager = self.opened_dirs.append

    def tearDown(self):
        self.app.destroy()
        self.imgconvert.messagebox = self._orig_box
        self.imgconvert.filedialog = self._orig_dialog
        convertutil.DEFAULT_OUTPUT_DIR = self._orig_out
        convertutil.DEFAULT_PAGES_DIR = self._orig_pages
        self._tmp.cleanup()

    def pump(self, timeout=60):
        """跑事件循环直到后台线程结束且结果已处理"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.app.update()
            worker = self.app.worker
            if worker and not worker.is_alive() and self.fake_box.calls:
                self.app.update()
                return True
            time.sleep(0.01)
        return False

    def test_initial_state(self):
        self.assertEqual(self.app.title(), "文档转图片工具")
        self.assertEqual(self.app.convert_button["state"], "normal")
        self.assertFalse(self.app.keep_pages.get())
        self.assertIn("PDF", self.app.status_text.get())

    def test_window_is_large_enough_for_its_content(self):
        """按需求尺寸开窗，换字体也不会把状态行裁掉"""
        self.app.update_idletasks()
        self.assertGreaterEqual(self.app.winfo_width(), self.app.winfo_reqwidth())
        self.assertGreaterEqual(self.app.winfo_height(), self.app.winfo_reqheight())

    def test_progress_bar_only_visible_while_converting(self):
        # 窗口在测试里是隐藏的，用 winfo_manager 判断有没有被布局，比 ismapped 可靠
        self.assertEqual(self.app.progress.winfo_manager(), "")
        self.app.set_busy(True)
        self.assertEqual(self.app.progress.winfo_manager(), "pack")
        self.app.set_busy(False)
        self.assertEqual(self.app.progress.winfo_manager(), "")

    def test_progress_area_does_not_shift_layout(self):
        """进度条出现/消失时窗口内容不应该跟着跳动"""
        self.app.update_idletasks()
        before = self.app.winfo_reqheight()
        self.app.set_busy(True)
        self.app.update_idletasks()
        self.assertEqual(self.app.winfo_reqheight(), before)

    def test_status_dot_reflects_result(self):
        dot = lambda: self.app.status_dot.itemcget(self.app._dot, "fill")  # noqa: E731
        self.assertEqual(dot(), self.imgconvert.MUTED)
        pdf = make_pdf(os.path.join(self.tmp, "gui.pdf"))
        self.app.file_path.set(pdf)
        self.app.convert_img()
        self.assertTrue(self.pump())
        self.assertEqual(dot(), self.imgconvert.SUCCESS)

    def test_status_dot_turns_red_on_failure(self):
        broken = os.path.join(self.tmp, "broken.pdf")
        with open(broken, "wb") as fp:
            fp.write(b"nope")
        self.app.file_path.set(broken)
        self.app.convert_img()
        self.assertTrue(self.pump())
        self.assertEqual(
            self.app.status_dot.itemcget(self.app._dot, "fill"),
            self.imgconvert.DANGER,
        )

    def test_rounded_button_disabled_ignores_clicks(self):
        clicked = []
        button = self.imgconvert.RoundedButton(
            self.app, text="x", command=lambda: clicked.append(1), font=("", 9)
        )
        event = type("E", (), {"x": 0, "y": 0})()  # 未映射的控件宽高只有 1px
        button._on_release(event)
        self.assertEqual(len(clicked), 1)
        button.config(state="disabled")
        self.assertEqual(button["state"], "disabled")
        button._on_release(event)
        self.assertEqual(len(clicked), 1, "禁用后仍然响应了点击")
        button.destroy()

    def test_convert_without_file_warns_and_starts_no_thread(self):
        self.app.convert_img()
        self.assertEqual(self.fake_box.kinds(), ["showwarning"])
        self.assertIsNone(self.app.worker)
        self.assertEqual(self.app.convert_button["state"], "normal")

    def test_convert_success_runs_in_background(self):
        pdf = make_pdf(os.path.join(self.tmp, "gui.pdf"), sizes=[LETTER, LETTER])
        self.app.file_path.set(pdf)

        self.app.convert_img()
        # 主线程必须立刻拿回控制权，界面在转换期间不能假死
        self.assertIsNotNone(self.app.worker)
        self.assertTrue(self.app.worker.daemon)
        self.assertEqual(self.app.convert_button["state"], "disabled")

        self.assertTrue(self.pump(), "转换没有在超时内完成")
        self.assertIn("askyesno", self.fake_box.kinds())
        self.assertIn("转换成功", self.app.status_text.get())
        self.assertTrue(os.path.isfile(os.path.join(self.out, "gui.jpg")))
        # 结束后按钮恢复可用
        self.assertEqual(self.app.convert_button["state"], "normal")
        self.assertEqual(self.app.path_button["state"], "normal")
        self.assertEqual(self.opened_dirs, [])

    def test_success_dialog_can_open_output_dir(self):
        self.fake_box.askyesno_result = True
        pdf = make_pdf(os.path.join(self.tmp, "gui.pdf"))
        self.app.file_path.set(pdf)
        self.app.convert_img()
        self.assertTrue(self.pump())
        self.assertEqual(self.opened_dirs, [self.out])

    def test_keep_pages_checkbox_is_passed_through(self):
        pdf = make_pdf(os.path.join(self.tmp, "gui.pdf"), sizes=[LETTER, LETTER])
        self.app.file_path.set(pdf)
        self.app.keep_pages.set(True)
        self.app.convert_img()
        self.assertTrue(self.pump())
        self.assertEqual(
            sorted(os.listdir(convertutil.DEFAULT_PAGES_DIR)), ["0.png", "1.png"]
        )

    def test_convert_failure_shows_message_and_restores_buttons(self):
        broken = os.path.join(self.tmp, "broken.pdf")
        with open(broken, "wb") as fp:
            fp.write(b"not a pdf at all")
        self.app.file_path.set(broken)

        self.app.convert_img()
        self.assertTrue(self.pump())
        self.assertIn("showwarning", self.fake_box.kinds())
        self.assertEqual(self.app.convert_button["state"], "normal")
        self.assertFalse(os.path.exists(self.out))

    def test_missing_file_shows_message(self):
        self.app.file_path.set(os.path.join(self.tmp, "nope.pdf"))
        self.app.convert_img()
        self.assertTrue(self.pump())
        self.assertIn("不存在", " ".join(self.fake_box.texts()))

    def test_double_click_convert_does_not_start_second_thread(self):
        pdf = make_pdf(os.path.join(self.tmp, "gui.pdf"), sizes=[LETTER] * 3)
        self.app.file_path.set(pdf)
        self.app.convert_img()
        first_worker = self.app.worker
        self.app.convert_img()  # 转换中再点一次
        self.assertIs(self.app.worker, first_worker)
        self.assertTrue(self.pump())
        # 只生成一个文件，没有并发写坏
        self.assertEqual(os.listdir(self.out), ["gui.jpg"])

    def test_progress_is_reported(self):
        pdf = make_pdf(os.path.join(self.tmp, "gui.pdf"), sizes=[LETTER] * 3)
        self.app.file_path.set(pdf)
        seen = []
        original = self.app.status_text.set
        self.app.status_text.set = lambda value: (seen.append(value), original(value))[1]
        self.app.convert_img()
        self.assertTrue(self.pump())
        self.assertTrue(
            any("页" in text for text in seen), "没有看到页进度提示：%s" % seen
        )

    def test_about_menu_dialogs(self):
        self.app.show_messagebox("版本")
        self.app.show_messagebox("帮助")
        self.assertEqual(self.fake_box.kinds(), ["showinfo", "showinfo"])
        self.assertIn(self.imgconvert.VERSION, " ".join(self.fake_box.texts()))

    def test_open_file_cancel_keeps_previous_path(self):
        self.app.file_path.set("/some/old.pdf")
        self.fake_dialog.result = ""  # 用户点了取消
        self.app.open_file()
        self.assertEqual(self.app.file_path.get(), "/some/old.pdf")

    def test_open_file_sets_path_and_offers_pdf_filter(self):
        self.fake_dialog.result = "/tmp/picked.pdf"
        self.app.open_file()
        self.assertEqual(self.app.file_path.get(), "/tmp/picked.pdf")
        self.assertIn("picked.pdf", self.app.status_text.get())
        filetypes = self.fake_dialog.calls[0]["filetypes"]
        self.assertEqual(filetypes[0], ("PDF文件", "*.pdf"))


if __name__ == "__main__":
    unittest.main()
