import struct
import threading
from enum import Enum
from threading import Thread, Event
import serial
import time
import queue

class CommandType(Enum):
    SET_DIRECTION = 0x44
    SET_PULSES = 0x50
    EXECUTE_MOVE = 0x47

class MotorController:
    def __init__(self, axis='X', stage_id=2, pulses_per_mm=2000):
        self.port = None
        self.baudrate = 9600
        self.timeout = 10
        self.connected = False
        self.ser = None
        self.axis = axis
        self.current_position = 0.0
        self.stage_id = stage_id
        self.pulses_per_mm = pulses_per_mm
        self.max_travel = 200
        self.running = False
        self.response_thread = None
        self.response_queue = queue.Queue()
        self.command_events = {}
        self.last_command = None

    def connect(self, port):
        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            self.connected = True
            self.start_response_monitor()
            return True
        except serial.SerialException as e:
            print(f"Motor {self.axis} failed to connect to {port}: {e}")
            self.connected = False
            return False

    def disconnect(self):
        self.stop_response_monitor()
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.connected = False
        self.ser = None

    def is_connected(self):
        return self.connected

    def start_response_monitor(self):
        if self.connected and not self.running:
            self.running = True
            self.response_thread = Thread(target=self.monitor_responses)
            self.response_thread.daemon = True
            self.response_thread.start()

    def stop_response_monitor(self):
        self.running = False
        if self.response_thread and self.response_thread.is_alive():
            self.response_thread.join(timeout=1.0)
        self.response_thread = None

    def monitor_responses(self):
        while self.running and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting >= 10:
                    response = self.ser.read(10)
                    self.response_queue.put(response)
                    print(f"Motor {self.axis} received raw response: {response.hex()}")
                else:
                    time.sleep(0.01)
            except serial.SerialException as e:
                print(f"Error reading response from motor {self.axis}: {e}")
                break

    def wait_for_response(self, cmd_type, timeout=1.0):
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                while not self.response_queue.empty():
                    response = self.response_queue.get_nowait()

                    if cmd_type == CommandType.EXECUTE_MOVE and len(response) == 10:
                        print(f"Motor {self.axis} received EXECUTE_MOVE response")
                        return True

                    if len(response) >= 5:
                        command_code = response[4]
                        try:
                            response_type = CommandType(command_code)
                            if response_type == cmd_type:
                                print(f"Motor {self.axis} received {cmd_type.name} response")
                                return True
                        except ValueError:
                            pass

                time.sleep(0.01)
            except queue.Empty:
                time.sleep(0.01)

        print(f"Timeout waiting for {cmd_type.name} response from motor {self.axis}")
        return False

    def send_command_and_wait(self, command, cmd_type, timeout=1.0):
        if not self.connected:
            print(f"Motor {self.axis} is not connected")
            return False

        self.ser.reset_input_buffer()

        while not self.response_queue.empty():
            try:
                self.response_queue.get_nowait()
            except queue.Empty:
                break

        print(f"Motor {self.axis} sending command: {cmd_type.name}")
        try:
            self.ser.write(command)
        except serial.SerialException as e:
            print(f"Error sending command to motor {self.axis}: {e}")
            return False

        return self.wait_for_response(cmd_type, timeout)

    def set_direction(self, direction):
        direction_cmd = bytes([0x00, 0x00, 0x40, self.stage_id,
                               CommandType.SET_DIRECTION.value, 0x00,
                               direction, 0x00, 0x00, 0x00])
        return self.send_command_and_wait(direction_cmd, CommandType.SET_DIRECTION)

    def set_pulse_count(self, pulse_count):
        pulse_bytes = struct.pack('<I', pulse_count)
        pulse_cmd = bytes([0x00, 0x00, 0x40, self.stage_id,
                           CommandType.SET_PULSES.value, 0x00]) + pulse_bytes
        return self.send_command_and_wait(pulse_cmd, CommandType.SET_PULSES)

    def execute_move(self, timeout=30.0):
        execute_cmd = bytes([0x00, 0x00, 0x40, self.stage_id,
                             CommandType.EXECUTE_MOVE.value, 0x00,
                             0x00, 0x00, 0x00, 0x00])
        return self.send_command_and_wait(execute_cmd, CommandType.EXECUTE_MOVE, timeout)

    def move_motor(self, direction, pulse_count, timeout=180):
        if not self.connected:
            print(f"Motor {self.axis} is not connected")
            return False

        if not self.set_direction(direction):
            print(f"Failed to set direction for motor {self.axis}")
            return False

        if not self.set_pulse_count(pulse_count):
            print(f"Failed to set pulse count for motor {self.axis}")
            return False

        if not self.execute_move(timeout):
            print(f"Failed to execute movement for motor {self.axis}")
            return False

        if direction == 1:
            self.current_position -= pulse_count / self.pulses_per_mm
        else:
            self.current_position += pulse_count / self.pulses_per_mm

        print(f"Movement completed. New position: {self.current_position:.2f}mm")
        return True

    def go_home_x(self, timeout=180):
        if not self.connected:
            print(f"Motor {self.axis} is not connected")
            return False

        home_direction = 1
        home_pulses = int(self.max_travel * self.pulses_per_mm)
        print(f"Motor {self.axis} homing: direction={home_direction}, pulses={home_pulses}")

        if self.move_motor(home_direction, home_pulses, timeout):
            self.current_position = 0.0
            print(f"Motor {self.axis} reached home position")
            return True
        return False

    def go_home_y(self, timeout=180):
        if not self.connected:
            print(f"Motor {self.axis} is not connected")
            return False

        home_direction = 0
        home_pulses = int(self.max_travel * self.pulses_per_mm)
        print(f"Motor {self.axis} homing: direction={home_direction}, pulses={home_pulses}")

        if self.move_motor(home_direction, home_pulses, timeout):
            self.move_motor(1, home_pulses, timeout)
            self.current_position = 0.0
            print(f"Motor {self.axis} reached home position")
            return True
        return False