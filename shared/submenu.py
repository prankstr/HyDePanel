from typing import Union

import gi
from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.revealer import Revealer
from fabric.widgets.widget import Widget as FabricWidget

gi.require_version("Gtk", "3.0")

from gi.repository import GObject, Gtk


class QuickSubMenu(Box):
    """A widget to display a submenu for quick settings."""

    def __init__(
        self,
        scan_button: Union[Button, None] = None,
        child: Union[FabricWidget, Gtk.Widget, None] = None,
        title: Union[str, None] = None,
        title_icon: Union[str, None] = None,
        **kwargs,
    ):
        self.title = title
        self.title_icon = title_icon
        self.child = child
        self.scan_button = scan_button

        self._title_label_widget: Union[Label, None] = None

        super().__init__(
            visible=False,
            orientation=Gtk.Orientation.VERTICAL,
            no_show_all=True,
            **kwargs,
        )

        self.revealer_child = Box(orientation="v", name="submenu")

        self.submenu_title_box = self.make_submenu_title_box()

        if self.submenu_title_box:
            self.revealer_child.add(self.submenu_title_box)
        if self.child:
            self.revealer_child.add(self.child)

        self.revealer = Revealer(
            child=self.revealer_child,
            transition_type="slide-down",
            transition_duration=600,
            h_expand=True,
        )
        self.revealer.set_reveal_child(False)
        self.revealer.connect(
            "notify::child-revealed",
            self.on_child_revealed,
        )
        self.add(self.revealer)

    def on_child_revealed(self, revealer: Revealer, _: GObject.ParamSpec):
        self.set_visible(revealer.get_reveal_child())

    def make_submenu_title_box(self) -> Union[Box, None]:
        if not self.title_icon and not self.title and not self.scan_button:
            self._title_label_widget = None
            return None

        submenu_box = Box(
            spacing=4,
            style_classes=["submenu-title-box"],
            orientation="h",
            hexpand=True,
        )

        has_actual_content = False
        if self.title_icon:
            submenu_box.add(Image(icon_name=self.title_icon, icon_size=18))
            has_actual_content = True

        if self.title:
            self._title_label_widget = Label(
                style_classes=["submenu-title-label"],
                label=self.title,
            )
            submenu_box.add(self._title_label_widget)
            has_actual_content = True
        else:
            self._title_label_widget = None

        if self.scan_button:
            if hasattr(self.scan_button, "set_halign"):
                self.scan_button.set_halign(Gtk.Align.END)
            submenu_box.pack_end(self.scan_button, False, False, 0)
            has_actual_content = True

        if not has_actual_content:
            return None

        return submenu_box

    def do_reveal(self, visible: bool):
        self.set_visible(True)
        self.revealer.set_reveal_child(visible)

    def toggle_reveal(self) -> bool:
        self.set_visible(True)
        current_state = self.revealer.get_reveal_child()
        self.revealer.set_reveal_child(not current_state)
        return not current_state

    def is_revealed(self) -> bool:
        return self.revealer.get_reveal_child()

    def set_title_text(self, new_text: str):
        """
        Updates the text of the title Label widget, if it was created.
        Also updates the internal 'title' attribute for consistency.
        """
        self.title = new_text
        if self._title_label_widget is not None:
            self._title_label_widget.set_label(new_text)
