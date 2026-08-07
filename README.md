# imgconvert-tool

> `imgconvert-tool` 是一款“将PDF文档转换合成为一张图片”的小工具

## 使用方法

1. 打开软件
2. 选择“PDF文件”
3. 点击“转换”
4. 输出结果见程序“out”目录

## 一些说明

* `out`是合成一张图后的目录，文件名与 PDF 同名；同名文件已存在时会自动加 `_1`、`_2` 后缀，不会覆盖
* 勾选“保留单页图片”后，PDF 的单页图片会存放在 `tmp_images` 目录（默认不保留，直接在内存中合成，更快）
* 页面宽度不一致时，窄的页面会在白色底上水平居中
* 页数很多时，为了不超出 JPEG 的尺寸上限（单边 65500 像素）会自动等比降低渲染倍率
* 如果万一有报错，可以自己改下代码，重新生成EXE :)

## requirement

```shell
pip install -r requirements.txt
```

## 测试

```shell
python -m unittest discover -s tests -v
```
