# widget.py
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import Qt
BUTTON_STYLE = """
    QPushButton {{
        background-color: {bg_color};
        border: 1px solid {border_color};
        border-radius: {radius}px;
        padding: 5px;
        color: {text_color};
    }}
    QPushButton:hover {{
        background-color: {hover_color};
    }}
    QPushButton:pressed {{
        background-color: {pressed_color};
    }}
    QPushButton:disabled {{
        background-color: {disabled_color};
        color: {disabled_text};
    }}
"""

STYLE_PRESETS = {
    "default": {
        "bg_color": "#f0f0f0",
        "border_color": "#c0c0c0",
        "text_color": "#000000",
        "hover_color": "#e0e0e0",
        "pressed_color": "#d0d0d0",
        "disabled_color": "#a0a0a0",
        "disabled_text": "#606060",
        "radius": 8
    },
    "primary": {
        "bg_color": "#4a86e8",
        "border_color": "#3a76d8",
        "text_color": "#ffffff",
        "hover_color": "#5a96f8",
        "pressed_color": "#3a76d8",
        "disabled_color": "#a0c0f0",
        "disabled_text": "#d0d0d0",
        "radius": 8
    },
    "success": {
        "bg_color": "#6aa84f",
        "border_color": "#5a983f",
        "text_color": "#ffffff",
        "hover_color": "#7ab85f",
        "pressed_color": "#5a983f",
        "disabled_color": "#b0d0a0",
        "disabled_text": "#d0d0d0",
        "radius": 8
    },
    "warning": {
        "bg_color": "#f1c232",
        "border_color": "#e1b222",
        "text_color": "#000000",
        "hover_color": "#ffd242",
        "pressed_color": "#e1b222",
        "disabled_color": "#f9e0a0",
        "disabled_text": "#606060",
        "radius": 8
    },
    "danger": {
        "bg_color": "#cc0000",
        "border_color": "#bc0000",
        "text_color": "#ffffff",
        "hover_color": "#dc1010",
        "pressed_color": "#bc0000",
        "disabled_color": "#f0a0a0",
        "disabled_text": "#d0d0d0",
        "radius": 8
    }
}

class StyledButton(QPushButton):
    def __init__(self, text="", preset="default", parent=None):
        super().__init__(text, parent)
        self._apply_preset(preset)

    def _apply_preset(self, preset_name="default"):
        if preset_name not in STYLE_PRESETS:
            preset_name = "default"

        style_data = STYLE_PRESETS[preset_name]
        self.setStyleSheet(BUTTON_STYLE.format(**style_data))

    def set_radius(self, radius):
        style_data = STYLE_PRESETS.get(self.style_name, STYLE_PRESETS["default"]).copy()
        style_data["radius"] = radius
        self.setStyleSheet(BUTTON_STYLE.format(**style_data))


def apply_button_style(button, preset="default"):
    if preset not in STYLE_PRESETS:
        preset = "default"

    style_data = STYLE_PRESETS[preset]
    button.setStyleSheet(BUTTON_STYLE.format(**style_data))
