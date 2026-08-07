"""convertutil 的单元测试：python -m unittest discover -s tests -v"""

import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

import convertutil  # noqa: E402
from convertutil import ConvertError, ConvertUtil, _unique_path, pymupdf  # noqa: E402

LETTER = (612, 792)
NARROW = (400, 500)


def setUpModule():
    # 测试里会故意触发失败路径，屏蔽日志免得刷屏
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)


def make_pdf(path, sizes=(LETTER,), text="hello", **save_kwargs):
    """生成一个测试用 PDF，sizes 为每页的点尺寸"""
    doc = pymupdf.open()
    for index, (width, height) in enumerate(sizes):
        page = doc.new_page(width=width, height=height)
        page.insert_text((40, 80), "%s page %d" % (text, index + 1), fontsize=36)
    doc.save(path, **save_kwargs)
    doc.close()
    return path


def expected_size(sizes, dpi=96):
    zoom = dpi / 72.0
    pixels = [(round(w * zoom), round(h * zoom)) for w, h in sizes]
    return max(w for w, _ in pixels), sum(h for _, h in pixels)


class ConvertUtilTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.out = os.path.join(self.tmp, "out")
        self.pages = os.path.join(self.tmp, "tmp_images")
        self.util = ConvertUtil()

    def tearDown(self):
        self._tmp.cleanup()

    def pdf(self, name="sample.pdf", sizes=(LETTER,), **kwargs):
        return make_pdf(os.path.join(self.tmp, name), sizes=sizes, **kwargs)

    # ---------- 正常流程 ----------

    def test_single_page(self):
        save_path = self.util.convert_img(self.pdf(), output_dir=self.out)
        self.assertTrue(os.path.isfile(save_path))
        self.assertEqual(os.path.basename(save_path), "sample.jpg")
        with Image.open(save_path) as img:
            self.assertEqual(img.size, expected_size([LETTER]))

    def test_multi_page_merged_vertically(self):
        sizes = [LETTER, LETTER, LETTER]
        save_path = self.util.convert_img(self.pdf(sizes=sizes), output_dir=self.out)
        with Image.open(save_path) as img:
            self.assertEqual(img.size, expected_size(sizes))
            # 每一页的区域里都应该有深色文字，说明页面真的渲染上去了
            page_height = img.size[1] // 3
            for index in range(3):
                band = img.crop(
                    (0, index * page_height, img.size[0], (index + 1) * page_height)
                )
                darkest = band.convert("L").getextrema()[0]
                self.assertLess(darkest, 128, "第 %d 页是空白的" % index)

    def test_narrow_page_centered_on_white_background(self):
        """页面宽度不一致时，空白处必须是白色（旧版本这里是红色）"""
        sizes = [LETTER, NARROW]
        save_path = self.util.convert_img(self.pdf(sizes=sizes), output_dir=self.out)
        with Image.open(save_path) as img:
            width, height = img.size
            narrow_row = height - 10
            self.assertEqual(img.getpixel((2, narrow_row)), (255, 255, 255))
            self.assertEqual(img.getpixel((width - 3, narrow_row)), (255, 255, 255))
            # 居中：窄页两侧留白宽度一致
            narrow_width = round(NARROW[0] * 96 / 72)
            left = (width - narrow_width) // 2
            self.assertEqual(img.getpixel((left + 2, narrow_row)), (255, 255, 255))

    def test_output_name_keeps_dots_and_case(self):
        """旧版本用 path[-4:] 截扩展名，遇到 .PDF 或名字里带点就出错"""
        save_path = self.util.convert_img(
            self.pdf(name="my.report v2.PDF"), output_dir=self.out
        )
        self.assertEqual(os.path.basename(save_path), "my.report v2.jpg")

    def test_does_not_overwrite_existing_output(self):
        pdf = self.pdf()
        first = self.util.convert_img(pdf, output_dir=self.out)
        second = self.util.convert_img(pdf, output_dir=self.out)
        self.assertNotEqual(first, second)
        self.assertEqual(os.path.basename(second), "sample_1.jpg")
        self.assertTrue(os.path.isfile(first))

    def test_progress_callback(self):
        calls = []
        self.util.convert_img(
            self.pdf(sizes=[LETTER] * 4),
            output_dir=self.out,
            progress=lambda done, total: calls.append((done, total)),
        )
        self.assertEqual(calls, [(1, 4), (2, 4), (3, 4), (4, 4)])

    def test_dpi_scales_output(self):
        pdf = self.pdf()
        low = self.util.convert_img(pdf, output_dir=self.out, dpi=96)
        high = self.util.convert_img(pdf, output_dir=self.out, dpi=192)
        with Image.open(low) as low_img, Image.open(high) as high_img:
            self.assertEqual(high_img.size[0], low_img.size[0] * 2)
            self.assertEqual(high_img.size[1], low_img.size[1] * 2)

    # ---------- 单页图片目录 ----------

    def test_keep_pages_writes_page_images(self):
        self.util.convert_img(
            self.pdf(sizes=[LETTER] * 3),
            output_dir=self.out,
            keep_pages=True,
            pages_dir=self.pages,
        )
        self.assertEqual(
            sorted(os.listdir(self.pages)), ["0.png", "1.png", "2.png"]
        )

    def test_keep_pages_disabled_by_default(self):
        self.util.convert_img(self.pdf(), output_dir=self.out, pages_dir=self.pages)
        self.assertFalse(os.path.exists(self.pages))

    def test_keep_pages_cleans_stale_pages_but_keeps_other_files(self):
        os.makedirs(self.pages)
        stale = os.path.join(self.pages, "99.png")
        keeper = os.path.join(self.pages, "note.txt")
        with open(stale, "wb") as fp:
            fp.write(b"stale")
        with open(keeper, "w", encoding="utf-8") as fp:
            fp.write("别删我")

        self.util.convert_img(
            self.pdf(), output_dir=self.out, keep_pages=True, pages_dir=self.pages
        )
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.isfile(keeper))
        self.assertTrue(os.path.isfile(os.path.join(self.pages, "0.png")))

    # ---------- 尺寸限制 ----------

    def test_max_pixels_downscales(self):
        sizes = [LETTER] * 6
        save_path = self.util.convert_img(
            self.pdf(sizes=sizes), output_dir=self.out, max_pixels=1_000_000
        )
        with Image.open(save_path) as img:
            self.assertLessEqual(img.size[0] * img.size[1], 1_000_000)
            # 长宽比基本不变
            full_w, full_h = expected_size(sizes)
            self.assertAlmostEqual(
                img.size[0] / img.size[1], full_w / full_h, delta=0.02
            )

    def test_max_width_restriction_keeps_ratio(self):
        """旧版本这里用 max_height 去除 max_width，比例是错的"""
        save_path = self.util.convert_img(
            self.pdf(sizes=[LETTER, LETTER]), output_dir=self.out, max_width=200
        )
        with Image.open(save_path) as img:
            self.assertEqual(img.size[0], 200)
            self.assertAlmostEqual(img.size[1] / img.size[0], 1056 * 2 / 816, delta=0.02)

    def test_max_height_restriction_keeps_ratio(self):
        save_path = self.util.convert_img(
            self.pdf(sizes=[LETTER, LETTER]), output_dir=self.out, max_height=300
        )
        with Image.open(save_path) as img:
            self.assertEqual(img.size[1], 300)
            self.assertAlmostEqual(img.size[1] / img.size[0], 1056 * 2 / 816, delta=0.02)

    def test_restriction_does_not_upscale(self):
        pdf = self.pdf()
        plain = self.util.convert_img(pdf, output_dir=self.out)
        limited = self.util.convert_img(pdf, output_dir=self.out, max_width=99999)
        with Image.open(plain) as a, Image.open(limited) as b:
            self.assertEqual(a.size, b.size)

    # ---------- 错误处理 ----------

    def test_empty_path(self):
        with self.assertRaises(ConvertError) as ctx:
            self.util.convert_img("")
        self.assertIn("请选择文件", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(ConvertError) as ctx:
            self.util.convert_img(os.path.join(self.tmp, "nope.pdf"))
        self.assertIn("不存在", str(ctx.exception))

    def test_directory_instead_of_file(self):
        with self.assertRaises(ConvertError):
            self.util.convert_img(self.tmp)

    def test_broken_pdf(self):
        path = os.path.join(self.tmp, "broken.pdf")
        with open(path, "wb") as fp:
            fp.write(b"this is definitely not a pdf")
        with self.assertRaises(ConvertError) as ctx:
            self.util.convert_img(path, output_dir=self.out)
        self.assertIn("PDF", str(ctx.exception))

    def test_broken_pdf_does_not_keep_the_file_open(self):
        """异常链一旦引用 pymupdf 的栈帧，损坏的 PDF 在 Windows 上就会被一直占用"""
        path = os.path.join(self.tmp, "broken.pdf")
        with open(path, "wb") as fp:
            fp.write(b"not a pdf")
        with self.assertRaises(ConvertError) as ctx:
            self.util.convert_img(path, output_dir=self.out)
        # 这两条在任何平台都成立，是「句柄不会被攥住」的直接原因
        self.assertIsNone(ctx.exception.__cause__)
        self.assertIsNone(ctx.exception.__context__)
        # Windows 上句柄没释放的话，下面这行会抛 PermissionError
        os.remove(path)

    def test_page_render_failure_does_not_keep_the_file_open(self):
        pdf = self.pdf()

        def boom(*args, **kwargs):
            raise RuntimeError("mupdf exploded")

        with mock.patch.object(convertutil.pymupdf.Page, "get_pixmap", boom):
            with self.assertRaises(ConvertError) as ctx:
                self.util.convert_img(pdf, output_dir=self.out)
        self.assertIsNone(ctx.exception.__cause__)
        self.assertIsNone(ctx.exception.__context__)
        os.remove(pdf)

    def test_encrypted_pdf(self):
        path = self.pdf(
            name="locked.pdf",
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )
        with self.assertRaises(ConvertError) as ctx:
            self.util.convert_img(path, output_dir=self.out)
        self.assertIn("密码", str(ctx.exception))

    def test_page_render_failure_reports_page_number(self):
        pdf = self.pdf(sizes=[LETTER, LETTER, LETTER])
        calls = []

        def boom(self_page, *args, **kwargs):
            calls.append(1)
            if len(calls) == 2:  # 让第 2 页炸
                raise RuntimeError("mupdf exploded")
            return original(self_page, *args, **kwargs)

        original = convertutil.pymupdf.Page.get_pixmap
        with mock.patch.object(convertutil.pymupdf.Page, "get_pixmap", boom):
            with self.assertRaises(ConvertError) as ctx:
                self.util.convert_img(pdf, output_dir=self.out)
        self.assertIn("第 2 页", str(ctx.exception))
        self.assertFalse(os.path.exists(self.out))

    def test_undeletable_stale_page_image_does_not_abort(self):
        """旧单页图片被占用删不掉时，转换仍然要能走完"""
        os.makedirs(self.pages)
        stale = os.path.join(self.pages, "0.png")
        open(stale, "wb").close()
        with mock.patch.object(convertutil.os, "remove", side_effect=OSError("busy")):
            save_path = self.util.convert_img(
                self.pdf(), output_dir=self.out, keep_pages=True, pages_dir=self.pages
            )
        self.assertTrue(os.path.isfile(save_path))

    def test_failure_leaves_no_output_dir_garbage(self):
        path = os.path.join(self.tmp, "broken.pdf")
        with open(path, "wb") as fp:
            fp.write(b"nope")
        with self.assertRaises(ConvertError):
            self.util.convert_img(path, output_dir=self.out)
        self.assertFalse(os.path.exists(self.out))


class BaseDirTestCase(unittest.TestCase):
    """默认输出目录的落脚点：跑源码用 CWD，打包成 EXE 用 EXE 所在目录"""

    def test_uses_cwd_when_running_from_source(self):
        self.assertEqual(convertutil.base_dir(), os.getcwd())

    def test_uses_executable_dir_when_frozen(self):
        with mock.patch.object(convertutil.sys, "frozen", True, create=True):
            with mock.patch.object(
                convertutil.sys, "executable", os.path.join("/opt", "app", "tool.exe")
            ):
                self.assertEqual(
                    convertutil.base_dir(), os.path.abspath(os.path.join("/opt", "app"))
                )

    def test_explicit_dir_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "custom")
            save_path = ConvertUtil().convert_img(
                make_pdf(os.path.join(tmp, "a.pdf")), output_dir=out
            )
            self.assertEqual(os.path.dirname(save_path), out)


class PyMuPDFVersionTestCase(unittest.TestCase):
    def test_old_pymupdf_gets_readable_message(self):
        with mock.patch.object(convertutil.pymupdf, "Page", object):
            with self.assertRaises(ConvertError) as ctx:
                ConvertUtil().convert_img("whatever.pdf")
        self.assertIn("版本过旧", str(ctx.exception))

    def test_current_pymupdf_passes_the_check(self):
        convertutil._check_pymupdf()  # 不应抛异常


class UniquePathTestCase(unittest.TestCase):
    def test_returns_same_path_when_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "a.jpg")
            self.assertEqual(_unique_path(target), target)

    def test_increments_until_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a.jpg", "a_1.jpg", "a_2.jpg"):
                open(os.path.join(tmp, name), "w").close()
            self.assertEqual(
                _unique_path(os.path.join(tmp, "a.jpg")),
                os.path.join(tmp, "a_3.jpg"),
            )


if __name__ == "__main__":
    unittest.main()
