import os

import fitz
from PIL import Image


class ConvertUtil:
    out_images_path = './tmp_images'

    @staticmethod
    def convert_img(pdf_file_path):
        if pdf_file_path:
            ConvertUtil.del_file(ConvertUtil.out_images_path)

            print('pdf file ===> ', pdf_file_path)
            print()
            ConvertUtil.pyMuPDF_fitz(pdfPath=pdf_file_path, imagePath=ConvertUtil.out_images_path)
            file_dir = './tmp_images'
            file_list = os.listdir(file_dir)
            file_list.sort(key=lambda x: int(x.split('.')[0]))

            img_list = []
            for filename in file_list:
                img_list.append(file_dir + '\\' + filename)

            ConvertUtil.image_merge(images=img_list, output_dir='./out',
                                    output_name=pdf_file_path[pdf_file_path.rindex('/'):-4] + '.jpg')
            return '转换成功'
        return '请检查输入！'

    def pyMuPDF_fitz(pdfPath, imagePath):
        print("imagePath=" + imagePath)
        pdfDoc = fitz.open(pdfPath)
        for pg in range(pdfDoc.pageCount):
            page = pdfDoc[pg]
            rotate = int(0)
            # 每个尺寸的缩放系数为1.3，这将为我们生成分辨率提高2.6的图像。
            # 此处若是不做设置，默认图片大小为：792X612, dpi=96
            zoom_x = 1.33333333  # (1.33333333-->1056x816)   (2-->1584x1224)
            zoom_y = 1.33333333
            mat = fitz.Matrix(zoom_x, zoom_y).preRotate(rotate)
            pix = page.getPixmap(matrix=mat, alpha=False)

            if not os.path.exists(imagePath):  # 判断存放图片的文件夹是否存在
                os.makedirs(imagePath)  # 若图片文件夹不存在就创建

            pix.writePNG(imagePath + '/' + '%s.jpg' % pg)  # 将图片写入指定的文件夹内

    def image_resize(img, size=(1000, 2000)):
        """
        调整图片大小
        """
        try:
            if img.mode not in ('L', 'RGB'):
                img = img.convert('RGB')
            img = img.resize(size)
        except Exception as e:
            pass
        return img

    def image_merge(images, output_dir='output', output_name='merge.jpg', \
                    restriction_max_width=None, restriction_max_height=None):
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
        new_img = Image.new('RGB', (max_width, total_height), 255)
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
            new_img = image_resize(new_img, size=(max_width, total_height))

        if restriction_max_height and total_height >= restriction_max_height:
            # 如果高度超过限制
            # 等比例缩小
            ratio = restriction_max_height / float(total_height)
            max_width = int(max_width * ratio)
            total_height = restriction_max_height
            new_img = ConvertUtil.image_resize(new_img, size=(max_width, total_height))

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        save_path = '%s/%s' % (output_dir, output_name)
        new_img.save(save_path)
        return save_path

    def del_file(path):
        if os.path.exists(path):
            ls = os.listdir(path)
            for i in ls:
                c_path = os.path.join(path, i)
                if os.path.isdir(c_path):
                    ConvertUtil.del_file(c_path)
                else:
                    os.remove(c_path)
