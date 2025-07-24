# main_window.py
import os
import threading
import time
from datetime import datetime

import h5py
import numpy as np
import serial
from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from PyQt6.QtNetwork import QTcpSocket
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QGroupBox, QLabel, QLineEdit, QComboBox,
                             QProgressBar, QStatusBar, QFileDialog, QMessageBox)
import pyqtgraph as pg
import serial.tools.list_ports
from .image_view import ImageView
from .widgets import StyledButton
from .motor_controller import MotorController

class HumidityReader(QThread):
    humidity_updated = pyqtSignal(float)
    connection_status = pyqtSignal(str)
    
    def __init__(self, port_name):
        super().__init__()
        self.port_name = port_name
        self.serial = None
        self.running = False
        self.humidity_value = 0.0
        self.buffer = ""
        
    def run(self):
        try:
            self.serial = serial.Serial(
                port=self.port_name,
                baudrate=4800,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1
            )
            self.running = True
            self.connection_status.emit("Connected")
            
            while self.running:
                if not self.serial.is_open:
                    break
                    
                try:
                    data = self.serial.readline().decode('ascii', errors='ignore')
                    if data:
                        print(f"Raw data received: {repr(data)}")
                        self.buffer += data
                        if '$' in self.buffer:
                            data_block, self.buffer = self.buffer.split('$', 1)
                            print(f"Data block: {repr(data_block)}")
                        lines = data_block.split('\r')

                        for line in lines:
                            line = line.strip()
                            print(f"Processing line: {repr(line)}")

                            if line.startswith('V01') or line.startswith('V02'):
                                if len(line) >= 7:  
                                    humidity_hex = line[3:7]
                                    print(f"Extracted hex: {humidity_hex}")
                                    try:
                                        self.humidity_value = int(humidity_hex, 16) * 0.005
                                        #print(f"Calculated humidity: {humidity_value:.2f}%")
                                        self.humidity_updated.emit(self.humidity_value)
                                    except ValueError:
                                        print(f"ValueError on line: {line}")

                except Exception as e:
                    print(f"Humidity read error: {str(e)}")
                    time.sleep(0.1)
                    
        except serial.SerialException as e:
            self.connection_status.emit(f"Port error: {str(e)}")
        finally:
            if self.serial and self.serial.is_open:
                self.serial.close()
            self.connection_status.emit("Disconnected")
            
    def stop(self):
        self.running = False
        self.wait(1000)
        
    def get_current_humidity(self):
        return self.humidity_value

class ScanThread(QThread):
    progress_updated = pyqtSignal(int)
    position_updated = pyqtSignal(float, float)
    status_updated = pyqtSignal(str)
    scan_completed = pyqtSignal(bool, str)
    spectrum_acquired = pyqtSignal(np.ndarray)

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.stopped = False
        self.paused = False

    def run(self):
        try:
            # record start humidity
            start_humidity = self.main_window.get_current_humidity()
            self.main_window.scan_data['start_humidity'] = start_humidity
            self.status_updated.emit(f"Scan start humidity: {start_humidity:.2f}%")

            center_x = float(self.main_window.center_x_edit.text())
            center_y = float(self.main_window.center_y_edit.text())
            width = float(self.main_window.width_edit.text())
            height = float(self.main_window.height_edit.text())
            step_x = float(self.main_window.step_x_edit.text())
            step_y = float(self.main_window.step_y_edit.text())
            t_min = float(self.main_window.t_min_edit.text())
            t_max = float(self.main_window.t_max_edit.text())

            start_x = center_x - width / 2
            end_x = center_x + width / 2
            start_y = center_y - height / 2
            end_y = center_y + height / 2

            x_steps = int(width / step_x) + 1
            y_steps = int(height / step_y) + 1
            total_points = x_steps * y_steps

            self.main_window.scan_data = {
                'positions': [],
                'spectra': [],
                'max_values': [],
                'min_values': [],
                'params': {
                    'center_x': center_x,
                    'center_y': center_y,
                    'width': width,
                    'height': height,
                    'step_x': step_x,
                    'step_y': step_y,
                    't_min': t_min,
                    't_max': t_max
                },
                'start_humidity': start_humidity,
                'end_humidity': None # will be set at the end
            }

            current_point = 0
            collected_points = 0

            wait_time = float(self.main_window.wait_time_edit.text())

            for y_idx in range(y_steps):
                y_pos = start_y + y_idx * step_y

                if y_idx % 2 == 0:
                    x_range = range(x_steps)
                else:
                    x_range = range(x_steps - 1, -1, -1)

                for x_idx in x_range:
                    if self.stopped:
                        self.scan_completed.emit(False, "scan stopped")
                        return

                    x_pos = start_x + x_idx * step_x
                    self.position_updated.emit(x_pos, y_pos)

                    self.status_updated.emit(f"Moving to ({x_pos:.2f}, {y_pos:.2f})")#

                    if not self.main_window.move_to_position(x_pos, y_pos):
                        self.status_updated.emit(f"move failed: ({x_pos:.2f}, {y_pos:.2f})")
                        continue

                    time.sleep(wait_time)

                    self.status_updated.emit(f"Acquiring spectrum at ({x_pos:.2f}, {y_pos:.2f})")
                    spectrum = self.main_window.acquire_spectrum()

                    if spectrum is None:
                        self.status_updated.emit(f"data acquire failed: ({x_pos:.2f}, {y_pos:.2f})")
                        continue

                    self.spectrum_acquired.emit(spectrum)

                    max_val, min_val = self.add_point(x_pos, y_pos, spectrum, t_min, t_max)
                    collected_points += 1
                    self.status_updated.emit(
                        f"point ({x_pos:.2f}, {y_pos:.2f}): max={max_val:.4f}, min={min_val:.4f}"
                    )

                    current_point += 1
                    progress = int(current_point / total_points * 100)
                    self.progress_updated.emit(progress)

            end_humidity = self.main_window.get_current_humidity()
            self.main_window.scan_data['end_humidity'] = end_humidity
            self.status_updated.emit(f"Scan end humidity: {end_humidity:.2f}%")
            
            self.scan_completed.emit(True, f"Scan completed. Collected {collected_points}/{total_points} points")
        except Exception as e:
            self.scan_completed.emit(False, f"scan error: {str(e)}")

    def add_point(self, x, y, spectrum, t_min, t_max):
        self.main_window.scan_data['positions'].append((x, y))
        self.main_window.scan_data['spectra'].append(spectrum)

        if self.main_window.time_axis is not None and spectrum is not None:
            indices = np.where((self.main_window.time_axis >= t_min) &
                               (self.main_window.time_axis <= t_max))[0]
            if len(indices) > 0:
                cut_spectrum = spectrum[indices]
                max_val = np.max(cut_spectrum)
                min_val = np.min(cut_spectrum)
                self.main_window.scan_data['max_values'].append(max_val)
                self.main_window.scan_data['min_values'].append(min_val)
                return max_val, min_val

        self.main_window.scan_data['max_values'].append(0)
        self.main_window.scan_data['min_values'].append(0)
        return 0, 0

    def stop(self):
        self.stopped = True

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.scan_data = {}
        self.time_axis = None
        self.scan_thread = None
        self.scanning = False
        self.port = 8001
        self.menlo_connected = False
        self.humidity_reader = None
        self.humidity_value = 0.0

        self.scan_lock = threading.Lock()

        self.setWindowTitle("THz Point Scanning Data Acquire")
        self.setGeometry(100, 100, 1200, 700)

        self.status_bar = QStatusBar( )
        self.setStatusBar( self.status_bar )
        self.status_label = QLabel("OK")
        self.status_label.setStyleSheet("font-weight: bold; color: blue;")
        self.status_bar.addWidget(self.status_label)

        self.humidity_label = QLabel("Humidity: --%")
        self.humidity_label.setStyleSheet("font-weight: bold; color: blue;")
        self.status_bar.addPermanentWidget(self.humidity_label)

        self.motorX_controller = MotorController(axis='X', stage_id=2)
        self.motorY_controller = MotorController(axis='Y', stage_id=1)
        self.setup_ui()
        self.populate_serial_ports()

        self.realtime_timer = QTimer()
        self.realtime_timer.timeout.connect(self.update_realtime_spectrum)

        self.humidity_timer = QTimer()
        self.humidity_timer.timeout.connect(self.update_humidity_display)
        self.humidity_timer.start(1000)  # Update every second

    def populate_serial_ports(self):
        ports = serial.tools.list_ports.comports()
        port__names = [port.device for port in ports]
        if not port__names:
            port__names = ["No Serial Port"]
        self.motorX_combo.addItems(port__names)
        self.motorY_combo.addItems(port__names)
        self.humidity_combo.addItems(port__names)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        # left
        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)

        device_group = QGroupBox("Device Connect")
        device_layout = QVBoxLayout(device_group)
        device_layout.setSpacing(15)

        motorX_layout = QHBoxLayout()
        self.motorX_combo = QComboBox()
        self.motorX_combo.setMinimumWidth(100)
        self.connect_motorX_btn = StyledButton("Connect", preset="primary")
        self.connect_motorX_btn.setMinimumWidth(150)
        self.motorX_status = QLabel()
        self.motorX_status.setFixedSize(20, 20)
        self.motorX_status.setStyleSheet("background-color: gray; border-radius: 10px;")
        motorX_layout.addWidget(QLabel("Port Motor X:"))
        motorX_layout.addWidget(self.motorX_combo)
        motorX_layout.addWidget(self.connect_motorX_btn)
        motorX_layout.addWidget(self.motorX_status)
        device_layout.addLayout(motorX_layout)

        motorY_layout = QHBoxLayout()
        self.motorY_combo = QComboBox()
        self.motorY_combo.setMinimumWidth(100)
        self.connect_motorY_btn = StyledButton("Connect", preset="primary")
        self.connect_motorY_btn.setMinimumWidth(150)
        self.motorY_status = QLabel()
        self.motorY_status.setFixedSize(20, 20)
        self.motorY_status.setStyleSheet("background-color: gray; border-radius: 10px;")
        motorY_layout.addWidget(QLabel("Port Motor Y:"))
        motorY_layout.addWidget(self.motorY_combo)
        motorY_layout.addWidget(self.connect_motorY_btn)
        motorY_layout.addWidget(self.motorY_status)
        device_layout.addLayout(motorY_layout)

        humidity_layout = QHBoxLayout()
        self.humidity_combo = QComboBox()
        self.humidity_combo.setMinimumWidth(100)
        self.connect_humidity_btn = StyledButton("Connect", preset="primary")
        self.connect_humidity_btn.setMinimumWidth(150)
        self.humidity_status = QLabel()
        self.humidity_status.setFixedSize(20, 20)
        self.humidity_status.setStyleSheet("background-color: gray; border-radius: 10px;")
        humidity_layout.addWidget(QLabel("Port Humidity:"))
        humidity_layout.addWidget(self.humidity_combo)
        humidity_layout.addWidget(self.connect_humidity_btn)
        humidity_layout.addWidget(self.humidity_status)
        device_layout.addLayout(humidity_layout)

        spectrometer_layout = QHBoxLayout()
        self.spectrometer_ip_edit = QLineEdit()
        self.spectrometer_ip_edit.setPlaceholderText("127.0.0.1")
        self.spectrometer_ip_edit.setMaximumWidth(100)
        self.spectrometer_ip_edit.setReadOnly(True)
        self.spectrometer_ip_edit.setStyleSheet("background-color: #d0d0d0;")
        self.connect_spectrometer_btn = StyledButton("Connect", preset="primary")
        self.connect_spectrometer_btn.setMinimumWidth(150)
        self.spectrometer_status = QLabel()
        self.spectrometer_status.setFixedSize(20, 20)
        self.spectrometer_status.setStyleSheet("background-color: gray; border-radius: 10px;")
        spectrometer_layout.addWidget(QLabel("IP Menlo:"))
        spectrometer_layout.addWidget(self.spectrometer_ip_edit)
        spectrometer_layout.addWidget(self.connect_spectrometer_btn)
        spectrometer_layout.addWidget(self.spectrometer_status)
        device_layout.addLayout(spectrometer_layout)

        # locate
        position_group = QGroupBox("Position Control")
        position_layout = QVBoxLayout(position_group)

        pos_now_layout = QHBoxLayout()
        self.x_pos_now = QLineEdit()
        self.x_pos_now.setReadOnly(True)
        self.x_pos_now.setStyleSheet("background-color: #d0d0d0;")
        self.x_pos_now.setMaximumWidth(80)
        self.y_pos_now = QLineEdit()
        self.y_pos_now.setReadOnly(True)
        self.y_pos_now.setStyleSheet("background-color: #d0d0d0;")
        self.y_pos_now.setMaximumWidth(80)
        pos_now_layout.addWidget(QLabel("Now X (mm)"))
        pos_now_layout.addWidget(self.x_pos_now)
        pos_now_layout.addWidget(QLabel("Now Y (mm)"))
        pos_now_layout.addWidget(self.y_pos_now)
        position_layout.addLayout(pos_now_layout)

        pos_home_layout = QHBoxLayout()
        self.home_x_btn = StyledButton("Home X", preset="primary")
        self.home_y_btn = StyledButton("Home Y", preset="primary")
        pos_home_layout.addWidget(self.home_x_btn)
        pos_home_layout.addWidget(self.home_y_btn)
        position_layout.addLayout(pos_home_layout)

        pos_loc_layout = QHBoxLayout()
        self.x_pos_loc = QLineEdit()
        self.x_pos_loc.setMaximumWidth(80)
        self.y_pos_loc = QLineEdit()
        self.y_pos_loc.setMaximumWidth(80)
        pos_loc_layout.addWidget(QLabel("Loc X (mm)"))
        pos_loc_layout.addWidget(self.x_pos_loc)
        pos_loc_layout.addWidget(QLabel("Loc Y (mm)"))
        pos_loc_layout.addWidget(self.y_pos_loc)
        position_layout.addLayout(pos_loc_layout)

        move_btn_layout = QHBoxLayout()
        self.move_x_btn = StyledButton("Move To X", preset="primary")
        self.move_y_btn = StyledButton("Move To Y", preset="primary")
        move_btn_layout.addWidget(self.move_x_btn)
        move_btn_layout.addWidget(self.move_y_btn)
        position_layout.addLayout(move_btn_layout)

        # scan setting
        scan_group = QGroupBox("Scan Setting")
        scan_layout = QVBoxLayout(scan_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        scan_layout.addWidget(self.progress_bar)

        save_layout = QHBoxLayout()
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("Select save directory")
        self.save_path_edit.setReadOnly(True)
        self.save_path_edit.setStyleSheet("background-color: #d0d0d0;")
        self.browse_btn = StyledButton("Browse...", preset="primary")
        save_layout.addWidget(QLabel("Save Path:"))
        save_layout.addWidget(self.save_path_edit)
        save_layout.addWidget(self.browse_btn)
        scan_layout.addLayout(save_layout)

        center_layout = QHBoxLayout()
        self.center_x_edit = QLineEdit('85')
        self.center_x_edit.setMaximumWidth(80)
        self.center_y_edit = QLineEdit('140')
        self.center_y_edit.setMaximumWidth(80)
        center_layout.addWidget(QLabel("Center X (mm)"))
        center_layout.addWidget(self.center_x_edit)
        center_layout.addWidget(QLabel("Center Y (mm)"))
        center_layout.addWidget(self.center_y_edit)
        scan_layout.addLayout(center_layout)

        size_layout = QHBoxLayout()
        self.width_edit = QLineEdit('10')
        self.width_edit.setMaximumWidth(80)
        self.height_edit = QLineEdit('10')
        self.height_edit.setMaximumWidth(80)
        size_layout.addWidget(QLabel("Width (mm)"))
        size_layout.addWidget(self.width_edit)
        size_layout.addWidget(QLabel("Height (mm)"))
        size_layout.addWidget(self.height_edit)
        scan_layout.addLayout(size_layout)

        step_layout = QHBoxLayout()
        self.step_x_edit = QLineEdit('1')
        self.step_x_edit.setMaximumWidth(80)
        self.step_y_edit = QLineEdit('1')
        self.step_y_edit.setMaximumWidth(80)
        step_layout.addWidget(QLabel("Step X (mm)"))
        step_layout.addWidget(self.step_x_edit)
        step_layout.addWidget(QLabel("Step Y (mm)"))
        step_layout.addWidget(self.step_y_edit)
        scan_layout.addLayout(step_layout)

        wait_time_layout = QHBoxLayout()
        self.wait_time_edit = QLineEdit('0.5')  # 0.5s
        self.wait_time_edit.setMaximumWidth(80)
        wait_time_layout.addWidget(QLabel("Wait time (s):"))
        wait_time_layout.addWidget(self.wait_time_edit)
        scan_layout.addLayout(wait_time_layout)

        scan_btn_layout = QHBoxLayout()
        self.start_scan_btn = StyledButton("Start Scan", preset="primary")
        self.stop_scan_btn = StyledButton("Stop Scan", preset="primary")
        scan_btn_layout.addWidget(self.start_scan_btn)
        scan_btn_layout.addWidget(self.stop_scan_btn)
        scan_layout.addLayout(scan_btn_layout)

        # image rec
        rec_group = QGroupBox("Image Reconstruction")
        rec_layout = QVBoxLayout(rec_group)

        self.rebulid_method_combo = QComboBox()
        self.rebulid_method_combo.addItems(['P-P Value','Max Value'])

        cut_time_layout = QHBoxLayout()
        self.t_min_edit = QLineEdit('0')
        self.t_min_edit.setMaximumWidth(80)
        self.t_max_edit = QLineEdit('100')
        self.t_max_edit.setMaximumWidth(80)
        cut_time_layout.addWidget(QLabel("Cut Start (ps)"))
        cut_time_layout.addWidget(self.t_min_edit)
        cut_time_layout.addWidget(QLabel("Cut End (ps)"))
        cut_time_layout.addWidget(self.t_max_edit)
        rec_layout.addLayout(cut_time_layout)

        control_layout.addWidget(device_group)
        control_layout.addWidget(position_group)
        control_layout.addWidget(scan_group)
        control_layout.addWidget(rec_group)

        # right display
        display_panel = QWidget()
        display_layout = QVBoxLayout(display_panel)
        # spectrum display

        pulse_group = QGroupBox("Time Domain Pulse")
        pulse_layout = QVBoxLayout(pulse_group)

        self.spectrum_plot = pg.PlotWidget()
        self.spectrum_plot.setLabel("left", "Voltage (mV)")
        self.spectrum_plot.setLabel("bottom", "Time (ps)")
        self.spectrum_curve = self.spectrum_plot.plot(pen = 'b')
        self.peak_value_label = QLabel("Peak-to-peak value: --")
        self.peak_value_label.setStyleSheet("font-weight: bold; color: blue;")#
        pulse_layout.addWidget(self.spectrum_plot)
        pulse_layout.addWidget(self.peak_value_label)

        # image display
        image_container = QWidget()
        image_layout = QHBoxLayout(image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        # left image: peak image
        peak_group = QGroupBox("Peak Value Reconstruction")
        peak_layout = QVBoxLayout(peak_group)
        self.peak_image_view = ImageView(show_crosshair=False)
        peak_layout.addWidget(self.peak_image_view)
        # right image: peak-to-peak image
        pp_group = QGroupBox("Peak-to-Peak Value Reconstruction")
        pp_layout = QVBoxLayout(pp_group)
        self.pp_image_view = ImageView(show_crosshair=True)
        pp_layout.addWidget(self.pp_image_view)

        image_layout.addWidget(peak_group)
        image_layout.addWidget(pp_group)

        self.set_light_theme()
        display_layout.addWidget(pulse_group)
        display_layout.addWidget(self.peak_value_label)
        display_layout.addWidget(image_container)

        main_layout.addWidget(control_panel, 1)
        main_layout.addWidget(display_panel, 2)

        self.stop_scan_btn.setEnabled(False)

        self.connect_motorX_btn.clicked.connect(self.toggle_motorX_connection)
        self.connect_motorY_btn.clicked.connect(self.toggle_motorY_connection)
        self.home_x_btn.clicked.connect(self.home_x_motor)
        self.home_y_btn.clicked.connect(self.home_y_motor)
        self.move_x_btn.clicked.connect(self.moveX_to_position)
        self.move_y_btn.clicked.connect(self.moveY_to_position)
        self.browse_btn.clicked.connect(self.select_save_directory)
        self.start_scan_btn.clicked.connect(self.start_scan)
        self.stop_scan_btn.clicked.connect(self.stop_scan)
        self.connect_spectrometer_btn.clicked.connect(self.toggle_spectrometer_connection)
        self.pp_image_view.cursor_moved.connect(self.handle_cursor_moved)
        self.connect_humidity_btn.clicked.connect(self.toggle_humidity_connection)

    def toggle_humidity_connection(self):
        if self.humidity_reader and self.humidity_reader.isRunning():
            # Disconnect
            self.humidity_reader.stop()
            self.humidity_reader = None
            self.connect_humidity_btn.setText("Connect")
            self.humidity_status.setStyleSheet("background-color: gray; border-radius: 10px;")
            self.status_label.setText("Humidity sensor disconnected")
        else:
            # Connect
            port = self.humidity_combo.currentText()
            try:
                self.humidity_reader = HumidityReader(port)
                self.humidity_reader.humidity_updated.connect(self.update_humidity_value)
                self.humidity_reader.connection_status.connect(self.status_label.setText)
                self.humidity_reader.start()
                self.connect_humidity_btn.setText("Disconnect")
                self.humidity_status.setStyleSheet("background-color: green; border-radius: 10px;")
                self.status_label.setText(f"Humidity sensor connected to {port}")
            except Exception as e:
                self.status_label.setText(f"Failed to connect humidity sensor: {str(e)}")
                self.humidity_status.setStyleSheet("background-color: red; border-radius: 10px;")
                
    def update_humidity_value(self, value):
        self.humidity_value = value
        self.humidity_label.setText(f"Humidity: {value:.2f}%")
        
    def update_humidity_display(self):
        if self.humidity_reader and self.humidity_reader.isRunning():
            self.humidity_label.setText(f"Humidity: {self.humidity_value:.2f}%")
            
    def get_current_humidity(self):
        return self.humidity_value

    def get_scan_params(self):
        return {
            'center_x': self.center_x_edit.text(),
            'center_y': self.center_y_edit.text(),
            'width': self.width_edit.text(),
            'height': self.height_edit.text(),
            'step_x': self.step_x_edit.text(),
            'step_y': self.step_y_edit.text(),
            't_min': self.t_min_edit.text(),
            't_max': self.t_max_edit.text()
        }

    def toggle_motorX_connection(self):
        if self.motorX_controller.is_connected():
            self.motorX_controller.disconnect()
            self.connect_motorX_btn.setText("Connect")
            self.motorX_status.setStyleSheet("background-color: gray; border-radius: 10px;")
            self.status_label.setText("Motor X disconnected")
        else:
            port = self.motorX_combo.currentText()
            if self.motorX_controller.connect(port):
                self.connect_motorX_btn.setText("Disconnect")
                self.motorX_status.setStyleSheet("background-color: green; border-radius: 10px;")
                self.status_label.setText(f"Motor X connected to {port}")
            else:
                self.status_label.setText("Failed to connect Motor X")

    def toggle_motorY_connection(self):
        if self.motorY_controller.is_connected():
            self.motorY_controller.disconnect()
            self.connect_motorY_btn.setText("Connect")
            self.motorY_status.setStyleSheet("background-color: gray; border-radius: 10px;")
            self.status_label.setText("Motor Y disconnected")
        else:
            port = self.motorY_combo.currentText()
            if self.motorY_controller.connect(port):
                self.connect_motorY_btn.setText("Disconnect")
                self.motorY_status.setStyleSheet("background-color: green; border-radius: 10px;")
                self.status_label.setText(f"Motor Y connected to {port}")
            else:
                self.status_label.setText("Failed to connect Motor Y")

    def toggle_spectrometer_connection(self):
        current_color = self.spectrometer_status.styleSheet()
        is_connected = "green" in current_color

        if is_connected:
            #self.spectrometer.disconnect()
            self.connect_spectrometer_btn.setText("Connect")
            self.spectrometer_status.setStyleSheet("background-color: gray; border-radius: 10px;")
            self.status_label.setText("Menlo disconnected")
            #self.spectrometer.stop_monitoring()
            self.realtime_timer.stop()
            self.menlo_connected = False
            self.spectrum_curve.setData([], [])
            self.peak_value_label.setText("Peak-to-peak value: --")
        else:
            ip = self.spectrometer_ip_edit.text()
            if 1 == 1: ###
                self.connect_spectrometer_btn.setText("Disconnect")
                self.spectrometer_status.setStyleSheet("background-color: green; border-radius: 10px;")
                self.status_label.setText(f"Menlo connected to {ip}")
                self.menlo_connected = True
                self.realtime_timer.start(1000)
                self.update_realtime_spectrum()
                #self.spectrometer.start_monitoring()
            else:
                self.spectrometer_status.setStyleSheet("background-color: gray; border-radius: 10px;")
                self.status_label.setText(f"Failed to connect to Menlo at {ip}")

    def home_x_motor(self):
        if self.motorX_controller.is_connected():
            self.status_label.setText(f"Motor X homing started...")
            threading.Thread(target=self._home_x_motor_worker).start()
        else:
            self.status_label.setText("Motor X is not connected")

    def home_y_motor(self):
        if self.motorY_controller.is_connected():
            self.status_label.setText(f"Motor Y homing started...")
            threading.Thread(target=self._home_y_motor_worker).start()
        else:
            self.status_label.setText("Motor Y is not connected")

    def moveX_to_position(self):
        if not self.motorX_controller.is_connected():
            self.status_label.setText("Motor X is not connected")
            return
        try:
            target_x = float(self.x_pos_loc.text())
            current_x = self.motorX_controller.current_position
            distance = abs(target_x - current_x)
            direction = 0 if target_x > current_x else 1
            pulse_count = int(distance * self.motorX_controller.pulses_per_mm)
            if pulse_count == 0:
                self.status_label.setText("Already at target position")
                return
            self.status_label.setText(f"Moving X to {target_x:.2f}mm...")
            threading.Thread(
                target=self._move_x_motor_worker,
                args=(direction, pulse_count, target_x)
            ).start()
        except ValueError:
            self.status_label.setText("Invalid position value")

    def moveY_to_position(self):
        if not self.motorY_controller.is_connected():
            self.status_label.setText("Motor Y is not connected")
            return
        try:
            target_y = float(self.y_pos_loc.text())
            current_y = self.motorY_controller.current_position
            distance = abs(target_y - current_y)
            direction = 0 if target_y > current_y else 1
            pulse_count = int(distance * self.motorY_controller.pulses_per_mm)
            if pulse_count == 0:
                self.status_label.setText("Already at target position")
                return
            self.status_label.setText(f"Moving Y to {target_y:.2f}mm...")
            threading.Thread(
                target=self._move_y_motor_worker,
                args=(direction, pulse_count, target_y)
            ).start()
        except ValueError:
            self.status_label.setText("Invalid position value")

    def _home_x_motor_worker(self):
        if self.motorX_controller.go_home_x():
            self.status_label.setText(f"Motor X homing completed")
            self.x_pos_now.setText("0.00")
        else:
            self.status_label.setText(f"Failed to home Motor X")

    def _home_y_motor_worker(self):
        if self.motorY_controller.go_home_y():
            self.status_label.setText(f"Motor Y homing completed")
            self.y_pos_now.setText("0.00")
        else:
            self.status_label.setText(f"Failed to home Motor Y")

    def _move_x_motor_worker(self, direction, pulse_count, target_x):
        success = self.motorX_controller.move_motor(direction, pulse_count)
        if success:
            self.x_pos_now.setText(f"{target_x:.2f}")
            self.status_label.setText(f"X axis moved to {target_x:.2f}mm")
        else:
            self.status_label.setText("Failed to move X axis")

    def _move_y_motor_worker(self, direction, pulse_count, target_y):
        success = self.motorY_controller.move_motor(direction, pulse_count)
        if success:
            self.y_pos_now.setText(f"{target_y:.2f}")
            self.status_label.setText(f"Y axis moved to {target_y:.2f}mm")
        else:
            self.status_label.setText("Failed to move Y axis")

    def set_light_theme(self):
        self.spectrum_plot.setBackground('w')
        self.spectrum_plot.getAxis('bottom').setPen('k')
        self.spectrum_plot.getAxis('bottom').setTextPen('k')
        self.spectrum_plot.getAxis('left').setPen('k')
        self.spectrum_plot.getAxis('left').setTextPen('k')
        self.spectrum_plot.setTitle("Time domain pulse", color='k')
        self.spectrum_plot.showGrid(x=True, y=True, alpha=0.3)

    def select_save_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select save directory",
            "",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )
        if directory:
            self.save_path_edit.setText(directory)

    def start_scan(self):
        if self.scanning:
            return

        if not self.motorX_controller.is_connected() or not self.motorY_controller.is_connected():
            self.status_label.setText("need to connect to motors")
            return

        save_path = self.save_path_edit.text()
        if not save_path:
            QMessageBox.warning(self, "Warning", "Please select save directory")
            return

        if self.time_axis is None:
            if not self.get_time_axis():
                QMessageBox.warning(self, "Warning", "Can't get time axis")
                return

        if self.realtime_timer.isActive():
            self.realtime_timer.stop()

        self.scanning = True
        self.stop_scan_btn.setEnabled(True)
        self.start_scan_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        self.scan_thread = ScanThread(self)
        self.scan_thread.progress_updated.connect(self.update_progress)
        self.scan_thread.position_updated.connect(self.update_scan_position)
        self.scan_thread.status_updated.connect(self.status_label.setText)
        self.scan_thread.scan_completed.connect(self.scan_complete)
        self.scan_thread.start()

        self.status_label.setText("Scanning start...")

    def stop_scan(self):
        if self.scan_thread:
            self.scan_thread.stop()
        self.scanning = False
        self.status_label.setText("scan stopped")

    def scan_complete(self, success, message):
        self.scanning = False
        self.stop_scan_btn.setEnabled(False)
        self.start_scan_btn.setEnabled(True)
        self.status_label.setText("scan completed")

        if self.menlo_connected:
            self.realtime_timer.start(1000)

        if success:
            save_path = self.save_path_edit.text()
            success, save_message = self.save_scan_data(save_path)
            if success:
                self.status_label.setText(f"Data is saved: {save_message}")
            else:
                self.status_label.setText(f"Scan finished but saved failed: {save_message}")

            self.reconstruct_images()
        else:
            self.status_label.setText(f"Scan failed: {message}")

    def save_scan_data(self, directory):

        if not self.scan_data.get('positions') or not self.scan_data.get('spectra'):
            return False, "no data can be saved"

        positions = self.scan_data.get('positions', [])
        spectra = self.scan_data.get('spectra', [])

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"scan_data_{timestamp}.hdf5"
        filepath = os.path.join(directory, filename)

        try:
            with h5py.File(filepath, 'w') as f:
                params_group = f.create_group("scan_parameters")
                for key, value in self.scan_data['params'].items():
                    params_group.attrs[key] = value

                # Save humidity values
                if 'start_humidity' in self.scan_data:
                    params_group.attrs['start_humidity'] = self.scan_data['start_humidity']
                if 'end_humidity' in self.scan_data:
                    params_group.attrs['end_humidity'] = self.scan_data['end_humidity']

                if positions:
                    f.create_dataset("positions", data=np.array(positions))

                if spectra:
                    f.create_dataset("spectra", data=np.array(spectra))

                if self.scan_data.get('max_values'):
                    f.create_dataset("max_values", data=np.array(self.scan_data['max_values']))

                if self.scan_data.get('min_values'):
                    f.create_dataset("min_values", data=np.array(self.scan_data['min_values']))

                if self.time_axis is not None:
                    f.create_dataset("time_axis", data=self.time_axis)

            return True, filepath
        except Exception as e:
            return False, str(e)

    def reconstruct_images(self):
        if not self.scan_data.get('positions') or not self.scan_data.get('max_values'):
            return

        params = self.scan_data['params']
        center_x = params['center_x']
        center_y = params['center_y']
        width = params['width']
        height = params['height']
        step_x = params['step_x']
        step_y = params['step_y']

        start_x = center_x - width / 2
        end_x = center_x + width / 2
        start_y = center_y - height / 2
        end_y = center_y + height / 2

        x_steps = int(width / step_x) + 1
        y_steps = int(height / step_y) + 1

        peak_image = np.zeros((y_steps, x_steps)) * np.nan
        pp_image = np.zeros((y_steps, x_steps)) * np.nan

        for i, (x, y) in enumerate(self.scan_data['positions']):
            col = int(round((x - start_x) / step_x))
            row = int(round((y - start_y) / step_y))

            if 0 <= row < y_steps and 0 <= col < x_steps:
                peak_image[row, col] = self.scan_data['max_values'][i]
                pp_image[row, col] = self.scan_data['max_values'][i] - self.scan_data['min_values'][i]

        physical_rect = (start_x, start_y, width, height)

        self.peak_image_view.set_image(peak_image, physical_rect)
        self.pp_image_view.set_image(pp_image, physical_rect)

        self.status_label.setText("Rec Image Finished")

    def update_scan_position(self, x, y):
        self.x_pos_now.setText(f"{x:.2f}")
        self.y_pos_now.setText(f"{y:.2f}")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def move_to_position(self, x, y):
        current_x = self.motorX_controller.current_position
        distance_x = abs(x - current_x)
        direction_x = 0 if x > current_x else 1
        pulse_count_x = int(distance_x * self.motorX_controller.pulses_per_mm)

        current_y = self.motorY_controller.current_position
        distance_y = abs(y - current_y)
        direction_y = 0 if y > current_y else 1
        pulse_count_y = int(distance_y * self.motorY_controller.pulses_per_mm)

        with self.scan_lock:
            x_success = True
            y_success = True

            if pulse_count_x > 0:
                x_success = self.motorX_controller.move_motor(direction_x, pulse_count_x)
                if x_success:
                    self.motorX_controller.current_position = x
                else:
                    self.status_label.setText(f"X move failed: {current_x} -> {x}")

            if pulse_count_y > 0:
                y_success = self.motorY_controller.move_motor(direction_y, pulse_count_y)
                if y_success:
                    self.motorY_controller.current_position = y
                else:
                    self.status_label.setText(f"Y move failed: {current_y} -> {y}")

            if x_success and pulse_count_x > 0:
                self.x_pos_now.setText(f"{x:.2f}")
            if y_success and pulse_count_y > 0:
                self.y_pos_now.setText(f"{y:.2f}")

            return x_success and y_success

    def handle_cursor_moved(self, x, y, value):
            self.status_label.setText(f"position: X={x:.2f}mm, Y={y:.2f}mm, value={value:.4f}")

    def get_time_axis(self):
        try:
            temp_socket = QTcpSocket()
            temp_socket.connectToHost('127.0.0.1', self.port)###
            if not temp_socket.waitForConnected(2000):
                print(f"can not connect to the TCP server: {self.ip}:8001", 3000)###
                return False

            temp_socket.write(b"GETTIMEAXIS\n")

            if temp_socket.waitForReadyRead(2000):
                data = temp_socket.readAll()
                byte_data = bytes(data)
                if len(byte_data) % 8 != 0:
                    print(f"data length error ({len(byte_data)}byte)")
                    return False
                self.time_axis = np.frombuffer(byte_data, dtype=np.float64)
                print(f"time axis point num: {len(self.time_axis)}")
                temp_socket.disconnectFromHost()
                return True
            else:
                print("get time axis timeout")
                return False
        except Exception as e:
            print(f"acquire time axis error: {e}")
            return False

    def acquire_spectrum(self):
        try:
            temp_socket = QTcpSocket()
            temp_socket.connectToHost('127.0.0.1', self.port)###
            if not temp_socket.waitForConnected(2000):
                print(f"can not connect to the TCP server: {self.ip}:8001", 3000)###
                return False
            temp_socket.write(b"GETLATESTPULSE\n")
            if temp_socket.waitForReadyRead(2000):
                data = temp_socket.readAll()
                byte_data = bytes(data)
                if len(byte_data) % 8 != 0:
                    print(f"data length error ({len(byte_data)}byte)")
                    return False

                spectrum = np.frombuffer(byte_data, dtype=np.float64)
                return spectrum

            else:
                print("get pulse timeout")
                return False
        except Exception as e:
            print(f"acquire pulse error: {e}")
            return False

    def update_realtime_spectrum(self):
        if not self.menlo_connected or self.scanning:
            return

        if self.time_axis is None:
            if not self.get_time_axis():
                self.status_label.setText("get time axis error")
                self.time_axis = np.linspace(0, 100, 1000)

        spectrum = self.acquire_spectrum()
        if spectrum is not None and self.time_axis is not None:
            if len(self.time_axis) != len(spectrum):
                min_len = min(len(self.time_axis), len(spectrum))
                self.spectrum_curve.setData(
                    self.time_axis[:min_len],
                    spectrum[:min_len]
                )
            else:
                self.spectrum_curve.setData(self.time_axis, spectrum)
            self.calculate_peak_to_peak(spectrum)

    def update_scan_spectrum(self, spectrum):
        if spectrum is not None:
            self.spectrum_curve.setData(self.time_axis, spectrum)
            self.calculate_peak_to_peak(spectrum)

    def calculate_peak_to_peak(self, spectrum):
        try:
            t_min = float(self.t_min_edit.text())
            t_max = float(self.t_max_edit.text())

            if self.time_axis is not None and spectrum is not None:
                indices = np.where((self.time_axis >= t_min) &
                                   (self.time_axis <= t_max))[0]
                if len(indices) > 0:
                    cut_spectrum = spectrum[indices]
                    max_val = np.max(cut_spectrum)
                    min_val = np.min(cut_spectrum)
                    pp_value = max_val - min_val
                    self.peak_value_label.setText(f"Peak-to-peak value: {pp_value:.4f}")
                    return
        except Exception as e:
            print(f"cal pp value error: {e}")

        self.peak_value_label.setText("Peak-to-peak value: --")