import sys
import os
import cv2
import numpy as np
import csv
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QSlider, QLabel, QGraphicsView,
    QGraphicsScene, QTableWidget, QTableWidgetItem, QLineEdit,
    QFileDialog, QMessageBox, QDialog, QSizePolicy
)
from PySide6.QtGui import QPixmap, QImage, QTransform, QPainter, QColor, QPen
from PySide6.QtCore import Qt, Signal

# 自定义可缩放图像视图类（完整显示整张图片+实时更新）
class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        
        # 缩放参数
        self.zoom_factor = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 10.0
        self.zoom_step = 0.1

    def wheelEvent(self, event):
        """滚轮事件实现图像缩放"""
        delta = event.angleDelta().y()
        if delta > 0:
            new_zoom = self.zoom_factor + self.zoom_step
        else:
            new_zoom = self.zoom_factor - self.zoom_step
        
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))
        
        if new_zoom != self.zoom_factor:
            scale_ratio = new_zoom / self.zoom_factor
            self.scale(scale_ratio, scale_ratio)
            self.zoom_factor = new_zoom
        
        event.accept()

    def set_image(self, cv_image):
        """完整显示整张图像，实时更新无裁剪"""
        self.scene().clear()
        if cv_image is None:
            return
        
        # 处理灰度图像（转为3通道BGR，确保显示逻辑统一）
        if len(cv_image.shape) == 2:
            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_GRAY2BGR)
        
        # 转换OpenCV图像（BGR）到Qt图像（RGB）
        height, width, channel = cv_image.shape
        bytes_per_line = 3 * width
        q_image = QImage(
            cv_image.data, width, height, bytes_per_line,
            QImage.Format.Format_RGB888
        )
        
        # 创建像素图并添加到场景（确保完整加载整张图片）
        pixmap = QPixmap.fromImage(q_image)
        self.scene().addPixmap(pixmap)
        self.scene().setSceneRect(pixmap.rect())
        
        # 自适应视图：自动缩放图像以适配视图，同时保留完整内容
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_factor = 1.0

    def reset_transform(self):
        """重置图像变换，恢复整张图片显示"""
        self.setTransform(QTransform())
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

# 剪裁对话框类（无改动）
class ImageCropDialog(QDialog):
    crop_completed = Signal(np.ndarray)

    def __init__(self, parent=None, image=None):
        super().__init__(parent)
        self.setWindowTitle("图像剪裁 - 拖动四条边调整区域")
        self.setFixedSize(800, 600)
        self.original_image = image
        self.cropped_image = None

        self.is_dragging = False
        self.drag_type = None
        self.drag_threshold = 10
        self.min_crop_size = 20

        self.crop_left = 0
        self.crop_top = 0
        self.crop_right = 0
        self.crop_bottom = 0

        self.scaled_qt_img = None
        self.scale_w = 1.0
        self.scale_h = 1.0
        self.img_offset_x = 0
        self.img_offset_y = 0

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)

        self.btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("确认剪裁")
        self.cancel_btn = QPushButton("取消剪裁")
        self.reset_btn = QPushButton("重置剪裁区域")
        self.btn_layout.addWidget(self.confirm_btn)
        self.btn_layout.addWidget(self.cancel_btn)
        self.btn_layout.addWidget(self.reset_btn)

        self.main_layout = QVBoxLayout()
        self.main_layout.addWidget(self.image_label)
        self.main_layout.addLayout(self.btn_layout)
        self.setLayout(self.main_layout)

        self.confirm_btn.clicked.connect(self.on_confirm_crop)
        self.cancel_btn.clicked.connect(self.reject)
        self.reset_btn.clicked.connect(self.on_reset)
        self.image_label.mousePressEvent = self.on_mouse_press
        self.image_label.mouseMoveEvent = self.on_mouse_move
        self.image_label.mouseReleaseEvent = self.on_mouse_release
        self.showEvent = self.on_show_event

    def on_show_event(self, event):
        if self.original_image is not None:
            self._init_image_display()
            dummy_x = self.crop_left
            dummy_y = self.crop_top
            self._update_mouse_cursor(self._judge_drag_type(dummy_x, dummy_y))
        event.accept()

    def _init_image_display(self):
        if self.original_image is None:
            return

        rgb_img = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_img.shape
        qt_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)
        self.scaled_qt_img = qt_img.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(QPixmap.fromImage(self.scaled_qt_img))

        self.scale_w = w / self.scaled_qt_img.width()
        self.scale_h = h / self.scaled_qt_img.height()
        self.img_offset_x = (self.image_label.width() - self.scaled_qt_img.width()) // 2
        self.img_offset_y = (self.image_label.height() - self.scaled_qt_img.height()) // 2

        img_w, img_h = self.scaled_qt_img.width(), self.scaled_qt_img.height()
        self.crop_left = 20
        self.crop_top = 20
        self.crop_right = img_w - 20
        self.crop_bottom = img_h - 20

        self._draw_crop_rect()
        self.image_label.repaint()

    def _get_valid_image_coords(self, mouse_x, mouse_y):
        img_x = mouse_x - self.img_offset_x
        img_y = mouse_y - self.img_offset_y
        img_x = max(0, min(img_x, self.scaled_qt_img.width()))
        img_y = max(0, min(img_y, self.scaled_qt_img.height()))
        return img_x, img_y

    def _judge_drag_type(self, img_x, img_y):
        left_ok = abs(img_x - self.crop_left) <= self.drag_threshold and self.crop_top <= img_y <= self.crop_bottom
        right_ok = abs(img_x - self.crop_right) <= self.drag_threshold and self.crop_top <= img_y <= self.crop_bottom
        top_ok = abs(img_y - self.crop_top) <= self.drag_threshold and self.crop_left <= img_x <= self.crop_right
        bottom_ok = abs(img_y - self.crop_bottom) <= self.drag_threshold and self.crop_left <= img_x <= self.crop_right

        if left_ok:
            return "left"
        elif right_ok:
            return "right"
        elif top_ok:
            return "top"
        elif bottom_ok:
            return "bottom"
        else:
            return None

    def _update_crop_coords(self, img_x, img_y):
        img_w, img_h = self.scaled_qt_img.width(), self.scaled_qt_img.height()
        if self.drag_type == "left":
            self.crop_left = max(0, min(img_x, self.crop_right - self.min_crop_size))
        elif self.drag_type == "right":
            self.crop_right = min(img_w, max(img_x, self.crop_left + self.min_crop_size))
        elif self.drag_type == "top":
            self.crop_top = max(0, min(img_y, self.crop_bottom - self.min_crop_size))
        elif self.drag_type == "bottom":
            self.crop_bottom = min(img_h, max(img_y, self.crop_top + self.min_crop_size))

    def _draw_crop_rect(self):
        if self.scaled_qt_img is None:
            return
        draw_img = self.scaled_qt_img.copy()
        painter = QPainter(draw_img)

        painter.setBrush(QColor(0, 0, 0, 80))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, draw_img.width(), self.crop_top)
        painter.drawRect(0, self.crop_bottom, draw_img.width(), draw_img.height() - self.crop_bottom)
        painter.drawRect(0, self.crop_top, self.crop_left, self.crop_bottom - self.crop_top)
        painter.drawRect(self.crop_right, self.crop_top, draw_img.width() - self.crop_right, self.crop_bottom - self.crop_top)

        painter.setPen(QPen(Qt.red, 4, Qt.SolidLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.crop_left, self.crop_top, self.crop_right - self.crop_left, self.crop_bottom - self.crop_top)
        painter.end()

        self.image_label.setPixmap(QPixmap.fromImage(draw_img))

    def _update_mouse_cursor(self, drag_type):
        if drag_type in ["left", "right"]:
            self.image_label.setCursor(Qt.SizeHorCursor)
        elif drag_type in ["top", "bottom"]:
            self.image_label.setCursor(Qt.SizeVerCursor)
        else:
            self.image_label.setCursor(Qt.ArrowCursor)

    def on_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            mouse_x, mouse_y = event.pos().x(), event.pos().y()
            img_x, img_y = self._get_valid_image_coords(mouse_x, mouse_y)
            self.drag_type = self._judge_drag_type(img_x, img_y)
            self.is_dragging = self.drag_type is not None
            self._update_mouse_cursor(self.drag_type)

    def on_mouse_move(self, event):
        if self.is_dragging and self.drag_type is not None:
            mouse_x, mouse_y = event.pos().x(), event.pos().y()
            img_x, img_y = self._get_valid_image_coords(mouse_x, mouse_y)
            self._update_crop_coords(img_x, img_y)
            self._draw_crop_rect()
            return
        mouse_x, mouse_y = event.pos().x(), event.pos().y()
        img_x, img_y = self._get_valid_image_coords(mouse_x, mouse_y)
        self._update_mouse_cursor(self._judge_drag_type(img_x, img_y))

    def on_mouse_release(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            self.drag_type = None
            self._update_mouse_cursor(None)

    def on_confirm_crop(self):
        if self.original_image is None or self.scaled_qt_img is None:
            QMessageBox.warning(self, "警告", "无有效图像可剪裁！")
            return
        orig_left = int(self.crop_left * self.scale_w)
        orig_top = int(self.crop_top * self.scale_h)
        orig_right = int(self.crop_right * self.scale_w)
        orig_bottom = int(self.crop_bottom * self.scale_h)
        orig_h, orig_w = self.original_image.shape[:2]
        if orig_left < 0 or orig_top < 0 or orig_right > orig_w or orig_bottom > orig_h:
            QMessageBox.warning(self, "警告", "剪裁区域超出原始图像范围！")
            return
        self.cropped_image = self.original_image[orig_top:orig_bottom, orig_left:orig_right]
        self.crop_completed.emit(self.cropped_image)
        QMessageBox.information(self, "提示", "剪裁成功")
        self.accept()

    def on_reset(self):
        self._init_image_display()
        self._update_mouse_cursor(None)

# 主窗口类
class CircularityCalculator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("岩土颗粒圆形度计算程序")
        
        # 设置默认窗口尺寸
        self.default_width = 1200
        self.default_height = 800
        self.resize(self.default_width, self.default_height)
        
        # 设置窗口最小尺寸
        self.setMinimumSize(800, 600)
        
        # 全局变量初始化
        self.original_image_path = ""
        self.original_image = None
        self.cropped_image = None
        self.gray_image = None
        self.binary_image = None
        self.processed_image = None
        self.particle_data = []
        self.current_threshold = 160
        
        # 创建堆叠窗口
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        
        # 创建三个页面
        self.page1 = self.create_page1()
        self.page2 = self.create_page2()
        self.page3 = self.create_page3()
        
        self.stacked_widget.addWidget(self.page1)
        self.stacked_widget.addWidget(self.page2)
        self.stacked_widget.addWidget(self.page3)
        
        # 初始化页面1的图像视图
        self.view1.set_image(np.zeros((480, 640, 3), dtype=np.uint8))
        
        # 添加重置窗口尺寸按钮
        self.add_reset_button()
        
        # 绑定下一步按钮事件
        self.next1_btn.clicked.connect(self.goto_page2)

    def add_reset_button(self):
        """添加重置窗口尺寸的按钮"""
        reset_btn = QPushButton("重置窗口尺寸")
        reset_btn.clicked.connect(self.reset_window_size)
        self.statusBar().addPermanentWidget(reset_btn)

    def reset_window_size(self):
        """将窗口尺寸重置为默认尺寸"""
        self.resize(self.default_width, self.default_height)

    def create_page1(self):
        """页面1：图像上传+剪裁+阈值调整"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title_label = QLabel("步骤1：上传图像→剪裁→调整二值化阈值")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        main_layout.addWidget(title_label)
        
        self.view1 = ZoomableGraphicsView()
        self.view1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self.view1)
        
        # 阈值调整区域
        threshold_layout = QHBoxLayout()
        threshold_label = QLabel("二值化阈值：")
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(0, 255)
        self.threshold_slider.setValue(self.current_threshold)
        self.threshold_value_label = QLabel(str(self.current_threshold))
        
        threshold_layout.addWidget(threshold_label)
        threshold_layout.addWidget(self.threshold_slider)
        threshold_layout.addWidget(self.threshold_value_label)
        main_layout.addLayout(threshold_layout)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        self.upload_btn = QPushButton("1. 上传图像")
        self.crop_btn = QPushButton("2. 剪裁图像")
        self.next1_btn = QPushButton("3. 完成，进入下一步")
        self.crop_btn.setEnabled(False)
        self.next1_btn.setEnabled(False)
        
        button_layout.addWidget(self.upload_btn)
        button_layout.addWidget(self.crop_btn)
        button_layout.addWidget(self.next1_btn)
        main_layout.addLayout(button_layout)
        
        # 绑定信号与槽
        self.upload_btn.clicked.connect(self.upload_image)
        self.crop_btn.clicked.connect(self.open_crop_dialog)
        self.threshold_slider.valueChanged.connect(self.update_threshold)
        
        return widget

    def create_page2(self):
        """页面2：颗粒分析+表格展示"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        title_label = QLabel("步骤2：颗粒数据分析与过滤")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        main_layout.addWidget(title_label)
        
        # 左右布局
        content_layout = QHBoxLayout()
        self.view2 = ZoomableGraphicsView()
        self.view2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_layout.addWidget(self.view2)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["序号", "周长", "面积", "圆形度"])
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_layout.addWidget(self.table)
        main_layout.addLayout(content_layout)
        
        # 面积过滤区域
        filter_layout = QHBoxLayout()
        filter_label = QLabel("最小颗粒面积阈值：")
        self.area_threshold_input = QLineEdit()
        self.area_threshold_input.setText("0")
        self.area_threshold_input.setFixedWidth(100)
        self.confirm2_btn = QPushButton("确认过滤，进入下一步")
        
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.area_threshold_input)
        filter_layout.addWidget(self.confirm2_btn)
        main_layout.addLayout(filter_layout)
        
        self.confirm2_btn.clicked.connect(self.filter_particles)
        return widget

    def create_page3(self):
        """页面3：结果保存（支持自定义路径和文件名）"""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        title_label = QLabel("步骤3：保存处理结果")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        main_layout.addWidget(title_label)
        
        self.view3 = ZoomableGraphicsView()
        self.view3.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self.view3)
        
        # 保存按钮区域
        save_layout = QHBoxLayout()
        self.save_image_btn = QPushButton("保存处理后图像")
        self.save_csv_btn = QPushButton("保存数据为CSV")
        
        save_layout.addWidget(self.save_image_btn)
        save_layout.addWidget(self.save_csv_btn)
        main_layout.addLayout(save_layout)
        
        # 绑定保存函数
        self.save_image_btn.clicked.connect(self.save_processed_image)
        self.save_csv_btn.clicked.connect(self.save_processed_csv)
        
        return widget

    # 页面功能函数（保持不变）
    def upload_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择图像文件", "", 
            "图像文件 (*.png *.jpg *.jpeg *.bmp *.tiff)"
        )
        if not file_path:
            return
        self.original_image_path = file_path
        self.original_image = cv2.imread(file_path)
        self.cropped_image = None
        if self.original_image is None:
            QMessageBox.warning(self, "错误", "无法读取选中的图像文件！")
            return
        self.view1.set_image(self.original_image)
        self.gray_image = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2GRAY)
        self.update_binary_image(self.current_threshold)
        self.crop_btn.setEnabled(True)
        self.next1_btn.setEnabled(True)

    def open_crop_dialog(self):
        if self.original_image is None:
            QMessageBox.warning(self, "错误", "请先上传图像！")
            return
        self.crop_dialog = ImageCropDialog(self, self.original_image)
        self.crop_dialog.crop_completed.connect(self.on_crop_completed)
        self.crop_dialog.exec_()

    def on_crop_completed(self, cropped_img):
        self.cropped_image = cropped_img
        self.gray_image = cv2.cvtColor(self.cropped_image, cv2.COLOR_BGR2GRAY)
        self.update_binary_image(self.current_threshold)
        self.view1.set_image(self.binary_image)
        self.next1_btn.setEnabled(True)

    def update_threshold(self, value):
        self.current_threshold = value
        self.threshold_value_label.setText(str(value))
        target_image = self.cropped_image if self.cropped_image is not None else self.original_image
        if target_image is not None:
            self.gray_image = cv2.cvtColor(target_image, cv2.COLOR_BGR2GRAY)
            self.update_binary_image(value)
            self.view1.set_image(self.binary_image)
            self.next1_btn.setEnabled(True)

    def update_binary_image(self, threshold):
        if self.gray_image is None:
            return
        _, self.binary_image = cv2.threshold(
            self.gray_image, threshold, 255, 
            cv2.THRESH_BINARY_INV
        )

    def goto_page2(self):
        if self.binary_image is None:
            QMessageBox.warning(self, "错误", "请先完成图像上传和阈值调整！")
            return
        contours, _ = cv2.findContours(
            self.binary_image.copy(), cv2.RETR_EXTERNAL, 
            cv2.CHAIN_APPROX_SIMPLE
        )
        self.particle_data = []
        target_original = self.cropped_image if self.cropped_image is not None else self.original_image
        self.processed_image = target_original.copy()
        for idx, contour in enumerate(contours, 1):
            perimeter = cv2.arcLength(contour, closed=True)
            area = cv2.contourArea(contour)
            if perimeter <= 0 or area <= 0:
                continue
            circularity = (4 * np.pi * area) / (perimeter ** 2)
            self.particle_data.append({
                "index": idx,
                "perimeter": round(perimeter, 4),
                "area": round(area, 4),
                "circularity": round(circularity, 4)
            })
            cv2.drawContours(self.processed_image, [contour], 0, (0, 255, 0), 3)
            M = cv2.moments(contour)
            if M["m00"] > 0:
                cX = int(M["m10"] / M["m00"])
                cY = int(M["m01"] / M["m00"])
                text = f"C:{round(circularity,4)} A:{round(area,4)} L:{round(perimeter,4)}"
                cv2.putText(
                    self.processed_image, text, (cX, cY),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
                )
        self.view2.set_image(cv2.cvtColor(self.processed_image, cv2.COLOR_BGR2RGB))
        self.fill_table(self.particle_data)
        self.stacked_widget.setCurrentIndex(1)

    def fill_table(self, data):
        self.table.setRowCount(len(data))
        for row, item in enumerate(data):
            self.table.setItem(row, 0, QTableWidgetItem(str(item["index"])))
            self.table.setItem(row, 1, QTableWidgetItem(str(item["perimeter"])))
            self.table.setItem(row, 2, QTableWidgetItem(str(item["area"])))
            self.table.setItem(row, 3, QTableWidgetItem(str(item["circularity"])))
        self.table.horizontalHeader().setStretchLastSection(True)
        for col in range(4):
            self.table.resizeColumnToContents(col)

    def filter_particles(self):
        try:
            min_area = float(self.area_threshold_input.text())
            if min_area < 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "错误", "请输入有效的非负数字作为最小面积阈值！")
            return
        filtered_data = [item for item in self.particle_data if item["area"] >= min_area]
        target_original = self.cropped_image if self.cropped_image is not None else self.original_image
        self.processed_image = target_original.copy()
        contours, _ = cv2.findContours(self.binary_image.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filtered_contours = [contour for contour in contours if cv2.contourArea(contour) >= min_area]
        for contour in filtered_contours:
            cv2.drawContours(self.processed_image, [contour], 0, (0, 255, 0), 3)
            perimeter = cv2.arcLength(contour, closed=True)
            area = cv2.contourArea(contour)
            circularity = (4 * np.pi * area) / (perimeter ** 2) if perimeter > 0 else 0
            M = cv2.moments(contour)
            if M["m00"] > 0:
                cX = int(M["m10"] / M["m00"])
                cY = int(M["m01"] / M["m00"])
                text = f"C:{round(circularity,4)} A:{round(area,4)} L:{round(perimeter,4)}"
                cv2.putText(self.processed_image, text, (cX, cY), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        self.fill_table(filtered_data)
        self.view3.set_image(cv2.cvtColor(self.processed_image, cv2.COLOR_BGR2RGB))
        self.filtered_particle_data = filtered_data
        self.stacked_widget.setCurrentIndex(2)

    def save_processed_image(self):
        if not self.original_image_path or self.processed_image is None:
            QMessageBox.warning(self, "错误", "没有可保存的处理后图像！")
            return
        dir_name, file_name = os.path.split(self.original_image_path)
        file_base, file_ext = os.path.splitext(file_name)
        default_name = f"{file_base}_processed{file_ext}"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存处理后图像", os.path.join(dir_name, default_name),
            f"图像文件 (*{file_ext});;所有文件 (*.*)"
        )
        if not save_path:
            return
        cv2.imwrite(save_path, self.processed_image)
        QMessageBox.information(self, "成功", f"图像已保存至：\n{save_path}")

    def save_processed_csv(self):
        if not self.original_image_path or not hasattr(self, "filtered_particle_data"):
            QMessageBox.warning(self, "错误", "没有可保存的颗粒数据！")
            return
        dir_name, file_name = os.path.split(self.original_image_path)
        file_base, _ = os.path.splitext(file_name)
        default_name = f"{file_base}_processed.csv"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存CSV数据", os.path.join(dir_name, default_name),
            "CSV文件 (*.csv);;所有文件 (*.*)"
        )
        if not save_path:
            return
        with open(save_path, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["序号", "周长", "面积", "圆形度"])
            for item in self.filtered_particle_data:
                writer.writerow([
                    item["index"], item["perimeter"], item["area"], item["circularity"]
                ])
        QMessageBox.information(self, "成功", f"CSV数据已保存至：\n{save_path}")

if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    window = CircularityCalculator()
    window.show()
    sys.exit(app.exec())