# image_view.py
import numpy as np
from PyQt6.QtCore import pyqtSignal
import pyqtgraph as pg

class ImageView(pg.GraphicsView):
    cursor_moved = pyqtSignal(float, float, float) # x,y,value

    def __init__(self, parent=None, show_crosshair=False, title=""):
        super().__init__(parent)
        self.show_crosshair = show_crosshair
        self.title = title
        self.setBackground('w')

        self.image_set = False

        # create display range
        self.plot = pg.PlotItem()
        self.setCentralItem(self.plot)
        self.plot.setTitle(title, color='k', size='12pt')
        self.plot.setLabel('left', 'Y (mm)')
        self.plot.setLabel('bottom', 'X (mm)')
        self.plot.setAspectLocked(True) # ensure not reshape; maybe a bug

        self.image_item = pg.ImageItem()
        self.plot.addItem(self.image_item)

        self.color_bar = pg.ColorBarItem()
        self.color_bar.setImageItem(self.image_item)
        self.color_bar.setColorMap(pg.colormap.get('viridis'))

        if self.show_crosshair:
            self.v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('r', width=1))
            self.h_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('r', width=1))
            self.plot.addItem(self.v_line, ignoreBounds=True)
            self.plot.addItem(self.h_line, ignoreBounds=True)

            self.coord_text = pg.TextItem("", anchor=(1, 1), color='k', fill=(255, 255, 255, 150))
            self.plot.addItem(self.coord_text)

            self.setMouseTracking(True)

        self.proxy = pg.SignalProxy(self.scene().sigMouseMoved, rateLimit=30, slot=self.mouse_moved)
        self.physical_rect = None # (x0, y0, dx, dy)

        self.plot.setXRange(0, 100)
        self.plot.setYRange(0, 100)

    def set_image(self, image, physical_rect=None):
        self.image_item.setImage(image)
        self.image_set = True

        if physical_rect:
            self.physical_rect = physical_rect
            x0, y0, width, height = physical_rect
            self.image_item.setRect(pg.QtCore.QRectF(x0, y0, width, height))

        if np.any(~np.isnan(image)):
            valid_data = image[~np.isnan(image)]
            if len(valid_data) > 0:
                min_val = np.min(valid_data)
                max_val = np.max(valid_data)
                self.image_item.setLevels((min_val, max_val))

        if physical_rect:
            x0, y0, width, height = physical_rect
            self.plot.setXRange(x0, x0 + width)
            self.plot.setYRange(y0, y0 + height)

    def mouse_moved(self, evt):
        if not self.show_crosshair or self.physical_rect is None:
            return

        pos = evt[0]
        mouse_point = self.image_item.mapFromScene(pos)
        x, y = mouse_point.x(), mouse_point.y()

        x0, y0, width, height = self.physical_rect

        if 0 <= x <= width and 0 <= y <= height:
            phys_x = x0 + x
            phys_y = y0 + y

            self.v_line.setPos(phys_x)
            self.h_line.setPos(phys_y)

            image = self.image_item.image
            if image is not None and image.size > 0:
                if image.shape[0] > 0 and image.shape[1] > 0:
                    img_x = int((phys_x - x0) / width * image.shape[1])
                    img_y = int((phys_y - y0) / height * image.shape[0])

                    if (0 <= img_y < image.shape[0] and
                            0 <= img_x < image.shape[1]):
                        value = image[img_y, img_x]

                        self.coord_text.setText(f"X: {phys_x:.2f}mm\nY: {phys_y:.2f}mm\nValue: {value:.4f}")
                        self.coord_text.setPos(phys_x, phys_y)

                        self.cursor_moved.emit(phys_x, phys_y, value)

    def mousePressEvent(self, event):
        if self.image_set:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.image_set:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.image_set:
            super().mouseReleaseEvent(event)


