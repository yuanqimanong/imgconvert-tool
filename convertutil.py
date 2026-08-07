"""PDF 转长图的核心逻辑，不依赖任何界面代码。"""

import itertools
import logging
import math
import os

try:
    import pymupdf
except ImportError:  # PyMuPDF < 1.24.3 只提供 fitz 这个模块名
    import fitz as pymupdf

from PIL import Image

logger = logging.getLogger(__name__)

# 渲染分辨率。96dpi 对应缩放系数 96/72≈1.333，A4/Letter 页面约 816x1056
DEFAULT_DPI = 96
# JPEG 每边最多 65535 像素，留一点余量
JPEG_MAX_SIDE = 65500
# 合成图的像素总量上限，超过就整体等比缩小。
# Pillow 认为超过 89478485 像素的图片可能是解压炸弹，读取时会告警甚至拒绝，
# 控制在这个值以下，生成的图才能被 Pillow 和多数看图软件正常打开
DEFAULT_MAX_PIXELS = 80_000_000

DEFAULT_OUTPUT_DIR = "./out"
DEFAULT_PAGES_DIR = "./tmp_images"


class ConvertError(Exception):
    """转换过程中的可预期错误，message 可以直接展示给用户。"""


def _check_pymupdf():
    """1.19 之前的 PyMuPDF 是 getPixmap 那套驼峰接口，这里给一句人能看懂的提示。"""
    if not hasattr(pymupdf.Page, "get_pixmap"):
        raise ConvertError(
            "PyMuPDF 版本过旧（需要 1.19 及以上），请执行：pip install -U -r requirements.txt"
        )


def _unique_path(path):
    """如果目标文件已存在，返回 xxx_1.jpg / xxx_2.jpg，避免静默覆盖。"""
    if not os.path.exists(path):
        return path
    stem, suffix = os.path.splitext(path)
    for index in itertools.count(1):
        candidate = "%s_%d%s" % (stem, index, suffix)
        if not os.path.exists(candidate):
            return candidate


def _fit_scale(width, height, max_pixels):
    """算出让画布同时满足 JPEG 边长限制和像素总量限制的缩放系数（<=1）。"""
    scale = 1.0
    if width > JPEG_MAX_SIDE:
        scale = min(scale, JPEG_MAX_SIDE / width)
    if height > JPEG_MAX_SIDE:
        scale = min(scale, JPEG_MAX_SIDE / height)
    if max_pixels and width * height * scale * scale > max_pixels:
        scale = min(scale, math.sqrt(max_pixels / (width * height)))
    return scale


def _target_size(width, height, max_width, max_height, max_pixels):
    """算出同时满足所有限制的目标尺寸，只缩小不放大。"""
    ratio = _fit_scale(width, height, max_pixels)
    if max_width and width > max_width:
        ratio = min(ratio, max_width / width)
    if max_height and height > max_height:
        ratio = min(ratio, max_height / height)
    if ratio >= 1.0:
        return width, height

    target_width = max(1, round(width * ratio))
    target_height = max(1, round(height * ratio))
    # 取整可能反过来越过上限，这里再硬夹一次
    if max_width:
        target_width = min(target_width, max_width)
    if max_height:
        target_height = min(target_height, max_height)
    target_width = min(target_width, JPEG_MAX_SIDE)
    target_height = min(target_height, JPEG_MAX_SIDE)
    while max_pixels and target_width * target_height > max_pixels:
        shrink = math.sqrt(max_pixels / (target_width * target_height))
        target_width = max(1, int(target_width * shrink))
        target_height = max(1, int(target_height * shrink))
    return target_width, target_height


def _resize_keep_ratio(img, max_width=None, max_height=None, max_pixels=None):
    """在限制范围内等比缩小图片，不放大。"""
    size = _target_size(img.size[0], img.size[1], max_width, max_height, max_pixels)
    if size == img.size:
        return img
    logger.info("合成图超出限制，等比缩小 %s -> %s", img.size, size)
    return img.resize(size, Image.LANCZOS)


class ConvertUtil:
    """把 PDF 的所有页面竖向拼成一张图片。"""

    def convert_img(
        self,
        pdf_file_path,
        output_dir=None,
        dpi=DEFAULT_DPI,
        max_width=None,
        max_height=None,
        max_pixels=DEFAULT_MAX_PIXELS,
        keep_pages=False,
        pages_dir=None,
        progress=None,
    ):
        """转换并返回生成的图片路径。

        pdf_file_path - 待转换的 PDF 路径
        output_dir - 合成图的输出目录，默认程序目录下的 out
        dpi - 渲染分辨率，越大越清晰也越慢
        max_width / max_height - 合成图的尺寸上限，超过则等比缩小
        max_pixels - 合成图的像素总量上限，超过则等比缩小
        keep_pages - 是否把每一页单独存成 PNG 保留下来
        pages_dir - keep_pages 为真时单页图片的存放目录
        progress - 可选回调 progress(已完成页数, 总页数)

        失败时抛出 ConvertError，message 可直接展示给用户。
        """
        _check_pymupdf()
        # 默认目录在这里解析而不是写在默认参数里，保证跟随当前工作目录
        output_dir = os.path.abspath(output_dir or DEFAULT_OUTPUT_DIR)
        pages_dir = os.path.abspath(pages_dir or DEFAULT_PAGES_DIR)
        if not pdf_file_path:
            raise ConvertError("请选择文件！")
        pdf_file_path = os.path.abspath(os.path.expanduser(pdf_file_path))
        if not os.path.isfile(pdf_file_path):
            raise ConvertError("文件不存在：%s" % pdf_file_path)

        doc = self._open_pdf(pdf_file_path)
        try:
            page_count = doc.page_count
            if page_count == 0:
                raise ConvertError("这个 PDF 没有任何页面。")

            zoom = dpi / 72.0
            # 先按页面尺寸算出画布大小，不用真的渲染，省一半时间和内存
            sizes = self._page_sizes(doc, zoom)
            canvas_width = max(width for width, _ in sizes)
            canvas_height = sum(height for _, height in sizes)

            # 画布太大就降低渲染倍率，避免先吃掉几个 G 内存再缩小
            scale = _fit_scale(canvas_width, canvas_height, max_pixels)
            if scale < 1.0:
                zoom *= scale
                logger.info("合成图过大，渲染倍率下调为 %.4f（约 %d dpi）", zoom, zoom * 72)
                sizes = self._page_sizes(doc, zoom)
                canvas_width = max(width for width, _ in sizes)
                canvas_height = sum(height for _, height in sizes)

            pages_out_dir = None
            if keep_pages:
                pages_out_dir = pages_dir
                self._reset_pages_dir(pages_out_dir)

            logger.info(
                "开始转换 %s：%d 页，合成图 %dx%d",
                pdf_file_path,
                page_count,
                canvas_width,
                canvas_height,
            )
            merged = self._render_and_merge(
                doc, zoom, sizes, canvas_width, canvas_height, pages_out_dir, progress
            )
        finally:
            doc.close()

        try:
            # 渲染前已经按 max_pixels 压过一轮，这里是逐页取整后的最终兜底
            resized = _resize_keep_ratio(merged, max_width, max_height, max_pixels)
            try:
                return self._save(resized, pdf_file_path, output_dir)
            finally:
                if resized is not merged:
                    resized.close()
        finally:
            merged.close()

    def _open_pdf(self, pdf_file_path):
        try:
            doc = pymupdf.open(pdf_file_path)
        except Exception as exc:  # 文件损坏、不是 PDF、没有读权限等
            logger.exception("打开 PDF 失败")
            raise ConvertError("无法打开该文件，可能不是有效的 PDF：%s" % exc) from exc
        if doc.needs_pass:
            doc.close()
            raise ConvertError("这个 PDF 有密码保护，无法转换。")
        return doc

    def _page_sizes(self, doc, zoom):
        """返回每页渲染后的像素尺寸，与 get_pixmap 的结果一致。"""
        matrix = pymupdf.Matrix(zoom, zoom)
        sizes = []
        for page in doc:
            rect = (page.rect * matrix).irect
            sizes.append((max(1, rect.width), max(1, rect.height)))
        return sizes

    def _reset_pages_dir(self, pages_dir):
        """清空单页图片目录，只删自己生成的 PNG，不碰用户的其它文件。"""
        if not os.path.isdir(pages_dir):
            os.makedirs(pages_dir, exist_ok=True)
            return
        for name in os.listdir(pages_dir):
            path = os.path.join(pages_dir, name)
            if os.path.isfile(path) and name.lower().endswith(".png"):
                try:
                    os.remove(path)
                except OSError:
                    # 图片正被看图软件占用之类，删不掉就跳过，不影响这次转换
                    logger.warning("旧的单页图片删不掉，已跳过：%s", path)

    def _render_and_merge(
        self, doc, zoom, sizes, canvas_width, canvas_height, pages_dir, progress
    ):
        """逐页渲染并贴到白底画布上，页面比画布窄时水平居中。"""
        matrix = pymupdf.Matrix(zoom, zoom)
        merged = Image.new("RGB", (canvas_width, canvas_height), (255, 255, 255))
        try:
            self._paste_pages(
                doc, matrix, merged, canvas_width, sizes, pages_dir, progress
            )
        except BaseException:
            merged.close()  # 中途失败就别把这块大画布留在内存里
            raise
        return merged

    def _paste_pages(
        self, doc, matrix, merged, canvas_width, sizes, pages_dir, progress
    ):
        """把每一页渲染出来贴到画布上，窄页水平居中"""
        y = 0
        total = len(sizes)
        for index, page in enumerate(doc):
            try:
                pix = page.get_pixmap(
                    matrix=matrix, alpha=False, colorspace=pymupdf.csRGB
                )
            except Exception as exc:  # 某一页的内容损坏时，指明是第几页
                logger.exception("第 %d 页渲染失败", index + 1)
                raise ConvertError(
                    "第 %d 页渲染失败，这一页的内容可能已损坏：%s" % (index + 1, exc)
                ) from exc
            page_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            if pages_dir:
                page_img.save(os.path.join(pages_dir, "%d.png" % index))
            # 理论上单页不会比画布宽，真遇到了也别让 paste 收到负坐标把图裁掉
            merged.paste(page_img, (max(0, (canvas_width - pix.width) // 2), y))
            y += pix.height
            page_img.close()
            pix = None  # 及早释放，长文档下内存占用差别很明显
            if progress:
                progress(index + 1, total)

    def _save(self, img, pdf_file_path, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        name = os.path.splitext(os.path.basename(pdf_file_path))[0] + ".jpg"
        save_path = _unique_path(os.path.join(output_dir, name))
        img.save(save_path, quality=90, subsampling=0)
        logger.info("已保存 %s", save_path)
        return save_path
