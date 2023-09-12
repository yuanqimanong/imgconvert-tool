import os

import fitz
from PIL import Image

OUT_IMAGES_PATH: str = os.path.abspath("./tmp_images")


def del_file(_path):
    if os.path.exists(_path):
        ls = os.listdir(_path)
        for i in ls:
            c_path = os.path.join(_path, i)
            if os.path.isdir(c_path):
                del_file(c_path)
            else:
                os.remove(c_path)


class ConvertUtil:
    def convert_img(self, pdf_file_path):
        if pdf_file_path:
            try:
                del_file(OUT_IMAGES_PATH)

                print("pdf file ===> ", pdf_file_path)
                self.deal_with_pdf(pdf_file_path)

                file_list = os.listdir(OUT_IMAGES_PATH)
                file_list.sort(key=lambda x: int(x.split(".")[0]))

                img_list = []
                for filename in file_list:
                    img_list.append(OUT_IMAGES_PATH + "\\" + filename)

                self.image_merge(
                    images=img_list,
                    output_dir="./out",
                    output_name=pdf_file_path[pdf_file_path.rindex("/") : -4] + ".jpg",
                )
                return "转换成功！"
            except Exception as e:
                print(e)
                return "转换失败！"
        return "请选择文件！"

    def deal_with_pdf(self, pdf_file_path):
        pdf_doc = fitz.open(pdf_file_path)
        for pg in range(pdf_doc.pageCount):
            page = pdf_doc[pg]
            rotate = int(0)
            # 每个尺寸的缩放系数为1.3，这将为我们生成分辨率提高2.6的图像。
            # 此处若是不做设置，默认图片大小为：792X612, dpi=96
            zoom_x = 1.33333333  # (1.33333333-->1056x816)   (2-->1584x1224)
            zoom_y = 1.33333333
            mat = fitz.Matrix(zoom_x, zoom_y).preRotate(rotate)
            pix = page.getPixmap(matrix=mat, alpha=False)

            if not os.path.exists(OUT_IMAGES_PATH):  # 判断存放图片的文件夹是否存在
                os.makedirs(OUT_IMAGES_PATH)  # 若图片文件夹不存在就创建

            pix.writePNG(OUT_IMAGES_PATH + "/" + "%s.jpg" % pg)  # 将图片写入指定的文件夹内

    def image_resize(self, img, size=(1000, 2000)):
        """
        调整图片大小
        """
        try:
            if img.mode not in ("L", "RGB"):
                img = img.convert("RGB")
            img = img.resize(size)
        except Exception as e:
            print(e)
        return img

    def image_merge(
        self,
        images,
        output_dir="output",
        output_name="merge.jpg",
        restriction_max_width=None,
        restriction_max_height=None,
    ):
        """垂直合并多张图片
        images - 要合并的图片路径列表
        ouput_dir - 输出路径
        output_name - 输出文件名
        restriction_max_width - 限制合并后的图片最大宽度，如果超过将等比缩小
        restriction_max_height - 限制合并后的图片最大高度，如果超过将等比缩小
        """
        max_width = 0
        total_height = 0
        # 计算合成后图片的宽度（以最宽的为准）和高度
        for img_path in images:
            if os.path.exists(img_path):
                img = Image.open(img_path)
                width, height = img.size
                if width > max_width:
                    max_width = width
                total_height += height

                # 产生一张空白图
        new_img = Image.new("RGB", (max_width, total_height), 255)
        # 合并
        x = y = 0
        for img_path in images:
            if os.path.exists(img_path):
                img = Image.open(img_path)
                width, height = img.size
                new_img.paste(img, (x, y))
                y += height

        if restriction_max_width and max_width >= restriction_max_width:
            # 如果宽带超过限制
            # 等比例缩小
            ratio = restriction_max_height / float(max_width)
            max_width = restriction_max_width
            total_height = int(total_height * ratio)
            new_img = self.image_resize(new_img, size=(max_width, total_height))

        if restriction_max_height and total_height >= restriction_max_height:
            # 如果高度超过限制
            # 等比例缩小
            ratio = restriction_max_height / float(total_height)
            max_width = int(max_width * ratio)
            total_height = restriction_max_height
            new_img = self.image_resize(new_img, size=(max_width, total_height))

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        save_path = "%s/%s" % (output_dir, output_name)
        new_img.save(save_path)
        return save_path
