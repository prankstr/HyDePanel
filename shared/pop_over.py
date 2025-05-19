from typing import ClassVar

import gi
from fabric.hyprland.service import HyprlandEvent
from fabric.hyprland.widgets import get_hyprland_connection
from fabric.widgets.box import Box
from fabric.widgets.wayland import WaylandWindow
from fabric.widgets.widget import Widget
from gi.repository import Gdk, GLib, GObject, GtkLayerShell
from loguru import logger

gi.require_versions({"Gtk": "3.0", "Gdk": "3.0", "GtkLayerShell": "0.1", "GObject": "2.0"})


class PopoverManager:
    """Singleton manager to handle shared resources for popovers."""

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.overlay = WaylandWindow(
            name="popover-overlay",
            style_classes="popover-overlay",
            title="fabric-shell-popover-overlay",
            anchor="left top right bottom",
            margin="-50px 0px 0px 0px",
            exclusivity="auto",
            layer="overlay",
            type="top-level",
            visible=False,
            all_visible=False,
            style="background-color: rgba(0,0,0,0.0);",
        )

        self.overlay.add(Box())

        self.active_popover = None
        self.available_windows = []

        self.overlay.connect("button-press-event", self._on_overlay_clicked)
        self._hyprland_connection = get_hyprland_connection()
        self._hyprland_connection.connect("event::focusedmonv2", self._on_monitor_change)

    def _on_monitor_change(self, _, event: HyprlandEvent):
        if self.active_popover:
            self.active_popover.hide_popover()
        return True

    def _on_overlay_clicked(self, widget, event):
        if self.active_popover:
            self.active_popover.hide_popover()
        return True

    def get_popover_window(self):
        """Get an available popover window or create a new one."""
        if self.available_windows:
            return self.available_windows.pop()

        window = WaylandWindow(
            type="popup",
            layer="overlay",
            name="popover-window",
            anchor="left top",
            visible=False,
            all_visible=False,
        )
        GtkLayerShell.set_keyboard_interactivity(window, True)
        window.set_keep_above(True)
        return window

    def return_popover_window(self, window):
        """Return a popover window to the pool."""
        for child in window.get_children():
            window.remove(child)

        window.hide()
        if len(self.available_windows) < 5:
            self.available_windows.append(window)
        else:
            window.destroy()

    def activate_popover(self, popover):
        """Set the active popover and show overlay."""
        if self.active_popover and self.active_popover != popover:
            self.active_popover.hide_popover()

        self.active_popover = popover
        self.overlay.show()


@GObject.Signal(flags=GObject.SignalFlags.RUN_LAST, return_type=GObject.TYPE_NONE, arg_types=())
def popover_opened(widget: Widget): ...


@GObject.Signal(flags=GObject.SignalFlags.RUN_LAST, return_type=GObject.TYPE_NONE, arg_types=())
def popover_closed(widget: Widget): ...


@GObject.type_register
class Popover(Widget):
    """Memory-efficient popover implementation."""

    __gsignals__: ClassVar = {
        "popover-opened": (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, ()),
        "popover-closed": (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, ()),
    }

    def __init__(
        self,
        point_to,
        content_factory=None,
        content=None,
    ):
        super().__init__()
        """
        Initialize a popover.

        Args:
            content_factory: Function that returns content widget when called
            point_to: Widget to position the popover next to
        """
        self._content_factory = content_factory
        self._point_to = point_to
        self._content_window = None
        self._content = content
        self._visible = False
        self._destroy_timeout = None
        self._manager = PopoverManager.get_instance()

    def set_content_factory(self, content_factory):
        """Set the content factory for the popover."""
        self._content_factory = content_factory

    def set_content(self, content):
        """Set the content for the popover."""
        self._content = content

    def _on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape and self._manager.active_popover:
            self._manager.active_popover.hide_popover()

    def get_visible(self) -> bool:
        return self._visible

    def open(self, *_):
        logger.debug(f"Popover ({self}): open() called. Current _visible: {self._visible}, _content_window: {self._content_window}")
        if self._destroy_timeout is not None:
            GLib.source_remove(self._destroy_timeout)
            self._destroy_timeout = None

        if self._visible and self._content_window is not None:
            logger.debug(f"Popover ({self}): open() called, but already visible and has content window. Doing nothing.")
            self._manager.activate_popover(self)
            self._content_window.show()
            if hasattr(self._content_window, "steal_input"):
                self._content_window.steal_input()
            return

        if not self._content_window:
            try:
                logger.debug(f"Popover ({self}): No content window, calling _create_popover()")
                self._create_popover()
            except Exception as e:
                logger.error(f"Popover ({self}): Could not create popover! Error: {e}", exc_info=True)
                self._visible = False
                if self._content_window:
                    self._manager.return_popover_window(self._content_window)
                self._content_window = None
                self._content = None
                return
        else:
            logger.debug(f"Popover ({self}): Content window exists, _visible was False. Showing window.")
            self._manager.activate_popover(self)
            self._content_window.show()
            if hasattr(self._content_window, "steal_input"):
                self._content_window.steal_input()
            self._visible = True

        if self._visible:
            self.emit("popover-opened")
        logger.debug(f"Popover ({self}): open() finished. _visible is {self._visible}")

    def _calculate_margins(self):
        widget_allocation = self._point_to.get_allocation()
        popover_size = self._content_window.get_size()

        display = Gdk.Display.get_default()
        screen = display.get_default()
        monitor_at_window = screen.get_monitor_at_window(self._point_to.get_window())
        monitor_geometry = monitor_at_window.get_geometry()

        x = widget_allocation.x + (widget_allocation.width / 2) - (popover_size.width / 2)
        y = widget_allocation.y - 5

        if x <= 0:
            x = widget_allocation.x
        elif x + popover_size.width >= monitor_geometry.width:
            x = widget_allocation.x - popover_size.width + widget_allocation.width

        return [y, 0, 0, x]

    def set_position(self, position: tuple[int, int, int, int] | None = None):
        if position is None:
            self._content_window.set_margin(self._calculate_margins())
            return False

        self._content_window.set_margin(position)
        return False

    def _on_content_ready(self, widget, event):
        self.set_position()

    def _create_popover(self):
        if self._content is None and self._content_factory is not None:
            self._content = self._content_factory()

        self._content_window = self._manager.get_popover_window()

        self._content.connect("draw", self._on_content_ready)

        self._content_window.add(Box(style_classes="popover-content", children=self._content))

        self._content_window.connect("focus-out-event", self._on_popover_focus_out)

        self._content_window.connect("key-press-event", self._on_key_press)
        self._manager.activate_popover(self)
        self._content_window.show()
        self._content_window.steal_input()
        self._visible = True

    def _on_popover_focus_out(self, widget, event):
        GLib.timeout_add(100, self.hide_popover)
        return False

    def hide_popover(self):
        logger.debug(f"Popover ({self}): hide_popover() called. Current _visible: {self._visible}, _content_window: {self._content_window}")
        if not self._visible:
            logger.debug(f"Popover ({self}): hide_popover() called, but already _visible = False. Ensuring actual hide.")
            if self._content_window:
                self._content_window.hide()
            if self._manager.active_popover is self:
                self._manager.overlay.hide()
                self._manager.active_popover = None
            return False

        if not self._content_window:
            logger.warning(f"Popover ({self}): hide_popover() called with _visible=True but no _content_window.")
            self._visible = False
            if self._manager.active_popover is self:
                self._manager.overlay.hide()
                self._manager.active_popover = None
            self.emit("popover-closed")
            return False

        self._content_window.hide()
        self._manager.overlay.hide()
        if self._manager.active_popover is self:
            self._manager.active_popover = None

        prev_visible_state = self._visible
        self._visible = False

        if not self._destroy_timeout:
            self._destroy_timeout = GLib.timeout_add(1000 * 5, self._destroy_popover)

        if prev_visible_state:
            logger.debug(f"Popover ({self}): Emitting popover-closed. _visible is now {self._visible}")
            self.emit("popover-closed")
        return False

    def _destroy_popover(self):
        """Return resources to the pool and clear references."""
        self._destroy_timeout = None
        self._visible = False

        if self._content_window:
            self._manager.return_popover_window(self._content_window)
            self._content_window = None

        self._content = None

        return False
