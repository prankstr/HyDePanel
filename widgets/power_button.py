import gi
gi.require_version("Gdk", "3.0")

from fabric.utils import exec_shell_command_async
from fabric.widgets.box import Box
from fabric.widgets.label import Label

from shared import ButtonWidget
from utils import BarConfig, ExecutableNotFoundError
from utils.widget_utils import text_icon
import utils.functions as helpers


class PowerWidget(ButtonWidget):
    """
    A widget to trigger a power-related command (e.g., wlogout) directly.
    """
    def __init__(self, widget_config: BarConfig, **kwargs):
        self.config = widget_config.get("power", {})
        if not self.config:
            self.config = {}
            print("Warning: 'power' configuration not found in widget_config. Using empty config.")

        super().__init__(self.config, name="power", **kwargs)

        self.action_command = self.config.get("command", "wlogout")
        executable_name = self.action_command.split()[0]

        if not helpers.executable_exists(executable_name):
            print(
                f"Error: Executable '{executable_name}' (from command: '{self.action_command}') not found. "
                f"PowerWidget will be disabled."
            )
            self.action_command = None
            self.set_sensitive(False)
            self.set_tooltip_text(f"Command '{executable_name}' not found")


        if self.config.get("show_icon", True):
            icon_name = self.config.get("icon", "system-shutdown-symbolic")
            icon_props = {"style_classes": ["panel-icon"]}

            widget_icon_font_size = self.config.get("widget_icon_font_size")
            if widget_icon_font_size:
                font_size_str = f"{widget_icon_font_size}px" if isinstance(widget_icon_font_size, (int, float)) else str(widget_icon_font_size)
                current_style = icon_props.get("style", "")
                additional_style = f"font-size: {font_size_str};"
                icon_props["style"] = f"{current_style} {additional_style}".strip()

            self.icon = text_icon(icon=icon_name, props=icon_props)
            if hasattr(self, 'box') and isinstance(self.box, Box):
                self.box.add(self.icon)
            else:
                self.add(self.icon)

        if self.config.get("label", False):
            label_text = self.config.get("label_text", "Power")
            self.power_label = Label(label=label_text, style_classes=["panel-text"])
            if hasattr(self, 'box') and isinstance(self.box, Box):
                self.box.add(self.power_label)
            else:
                self.add(self.power_label)

        if self.config.get("tooltip", True):
            tooltip_text = self.config.get("tooltip_text", "Power Menu")
            self.set_tooltip_text(tooltip_text)

        if self.action_command:
            self.connect("clicked", self._on_clicked_handler)

    def _on_clicked_handler(self, _emitter):
        """Handles the 'clicked' signal from ButtonWidget."""
        if not self.action_command:
            print("PowerWidget: Clicked, but no action command is configured or executable.")
            return True

        print(f"PowerWidget: Executing '{self.action_command}'")
        try:
            exec_shell_command_async(
                self.action_command,
                lambda success, stdout, stderr: self._handle_command_result(success, stdout, stderr)
            )
        except Exception as e:
            print(f"Error trying to execute command '{self.action_command}': {e}")
        return True

    def _handle_command_result(self, success: bool, stdout: str, stderr: str):
        if success:
            print(f"Command '{self.action_command}' executed successfully.")
            if stdout:
                print(f"Stdout: {stdout}")
        else:
            print(f"Command '{self.action_command}' failed.")
            if stderr:
                print(f"Stderr: {stderr}")
