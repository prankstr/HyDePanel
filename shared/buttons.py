import contextlib

import gi
from fabric.core.service import Signal
from fabric.utils import get_relative_path
from fabric.widgets.box import Box
from fabric.widgets.image import Image as FabricImage
from fabric.widgets.label import Label as FabricLabel

from utils.icons import icons
from utils.widget_utils import setup_cursor_hover

from .animator import Animator
from .circle_image import CircleImage
from .separator import Separator
from .submenu import QuickSubMenu
from .widget_container import HoverButton

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


class ScanButton(HoverButton):
    def __init__(self, **kwargs):
        super().__init__(name="scan-button", style_classes="submenu-button", **kwargs)
        image_path = "../assets/icons/png/refresh.png"
        try:
            resolved_image_path = get_relative_path(image_path)
        except Exception:
            resolved_image_path = image_path

        self.scan_image = CircleImage(image_file=resolved_image_path, size=20)
        self.scan_animator = Animator(
            bezier_curve=(0, 0, 1, 1),
            duration=4,
            min_value=0,
            max_value=360,
            tick_widget=self,
            repeat=False,
            notify_value=self.set_notify_value,
        )
        if hasattr(self, "set_image") and callable(self.set_image):
            self.set_image(self.scan_image)
        elif hasattr(self, "add"):
            self.add(self.scan_image)

    def set_notify_value(self, p, _):
        if hasattr(self.scan_image, "set_angle"):
            self.scan_image.set_angle(p.value)

    def play_animation(self):
        if hasattr(self.scan_animator, "play"):
            self.scan_animator.play()

    def stop_animation(self):
        if hasattr(self.scan_animator, "stop"):
            self.scan_animator.stop()


def is_font_icon_character(text: str) -> bool:
    return bool(text and len(text) == 1 and ord(text[0]) > 127)


class QSToggleButton(Box):
    @Signal
    def action_clicked(self) -> None: ...

    def __init__(
        self,
        action_label: str = "My Label",
        action_icon: str = icons["fallback"]["package"],
        pixel_size: int = 20,
        **kwargs,
    ):
        super().__init__(
            name="quicksettings-togglebutton",
            h_align="start",
            v_align="start",
            **kwargs,
        )

        self.pixel_size = pixel_size
        self.action_label_str = action_label

        if is_font_icon_character(action_icon):
            self.action_icon = FabricLabel(
                label=action_icon,
                style_classes=["icon", "panel-icon-font"],
                v_align=Gtk.Align.CENTER,
            )
        else:
            self.action_icon = FabricImage(
                style_classes=["panel-icon"],
                icon_name=action_icon,
                icon_size=pixel_size,
            )

        self.action_label = FabricLabel(
            style_classes=["panel-text"],
            label=action_label,
            ellipsization="end",
            h_align="start",
            h_expand=True,
        )

        self._action_button_content_box = Box(
            h_align="start",
            v_align="center",
            style_classes="quicksettings-toggle-action-box",
            children=[self.action_icon, self.action_label],
        )

        self.action_button = HoverButton(
            style_classes="quicksettings-toggle-action",
            child=self._action_button_content_box,
        )
        self.action_button.set_size_request(170, 20)

        self.box = Box()
        self.box.add(self.action_button)
        self.add(self.box)

        setup_cursor_hover(self)
        self.action_button.connect("clicked", self.do_action)

    def do_action(self, *_):
        self.emit("action-clicked")

    def set_active_style(self, active: bool) -> None:
        if active:
            self.set_style_classes("active")
        else:
            self.set_style_classes("")

    def set_action_label(self, label: str):
        stripped_label = label.strip()
        if hasattr(self, "action_label") and isinstance(self.action_label, FabricLabel):
            self.action_label.set_label(stripped_label)
        self.action_label_str = stripped_label

    def set_action_icon(self, icon_content: str):
        if not hasattr(self, "action_icon"):
            return

        new_is_text = is_font_icon_character(icon_content)
        current_is_label = isinstance(self.action_icon, FabricLabel)
        current_is_image = isinstance(self.action_icon, FabricImage)

        if new_is_text:
            if current_is_label:
                self.action_icon.set_label(icon_content)
            else:
                new_label = FabricLabel(
                    label=icon_content,
                    style_classes=["icon", "panel-icon-font"],
                    v_align=Gtk.Align.CENTER,
                )
                self._replace_current_icon_widget(new_label)
        else:
            if current_is_image:
                self.action_icon.set_from_icon_name(icon_content, self.pixel_size)
            else:
                new_image = FabricImage(
                    style_classes=["panel-icon"],
                    icon_name=icon_content,
                    icon_size=self.pixel_size,
                )
                self._replace_current_icon_widget(new_image)

    def _replace_current_icon_widget(self, new_widget: Gtk.Widget):
        if not (
            hasattr(self, "action_icon")
            and hasattr(self, "_action_button_content_box")
            and self._action_button_content_box
            and isinstance(self._action_button_content_box, Box)
        ):
            return

        old_widget = self.action_icon

        if old_widget.get_parent() == self._action_button_content_box:
            children = list(self._action_button_content_box.get_children())
            idx = -1
            idx = children.index(old_widget)
            contextlib.suppress(ValueError)

            self._action_button_content_box.remove(old_widget)
            self._action_button_content_box.add(new_widget)

            if idx != -1:
                current_children_count = len(
                    self._action_button_content_box.get_children()
                )
                if idx < current_children_count:
                    self._action_button_content_box.reorder_child(new_widget, idx)
            elif len(self._action_button_content_box.get_children()) > 1:
                self._action_button_content_box.reorder_child(new_widget, 0)

            self.action_icon = new_widget


class QSChevronButton(QSToggleButton):
    @Signal
    def reveal_clicked(self) -> None: ...

    def __init__(
        self,
        action_label: str = "My Label",
        action_icon: str = icons["fallback"]["package"],
        pixel_size: int = 20,
        submenu: QuickSubMenu | None = None,
        **kwargs,
    ):
        self.submenu = submenu
        super().__init__(
            action_label=action_label,
            action_icon=action_icon,
            pixel_size=pixel_size,
            **kwargs,
        )
        self.button_image = FabricImage(
            icon_name=icons["ui"]["arrow"]["right"], icon_size=20
        )
        self.reveal_button = HoverButton(
            style_classes="toggle-revealer", image=self.button_image, h_expand=True
        )
        self.box.add(Separator())
        self.box.add(self.reveal_button)
        self.reveal_button.connect("clicked", self.do_reveal_toggle)

    def do_reveal_toggle(self, *_):
        self.emit("reveal-clicked")
