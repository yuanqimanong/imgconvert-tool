import logging

from imgconvert import ImgConvert

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = ImgConvert()
    app.mainloop()
