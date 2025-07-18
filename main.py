# main.py
import sys
import os

from PyQt6.QtWidgets import QApplication
from core.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__=='__main__':
    main()