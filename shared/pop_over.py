# shared/pop_over.py

from typing import ClassVar, Any, Callable, Union, List, Tuple, Optional
import weakref

import gi
import cairo
from fabric.hyprland.service import HyprlandEvent
from fabric.hyprland.widgets import get_hyprland_connection
from fabric.widgets.box import Box
from fabric.widgets.wayland import WaylandWindow
from fabric.widgets.widget import Widget
from gi.repository import Gdk, GLib, GObject, GtkLayerShell, Gtk
from loguru import logger

gi.require_versions({"Gtk": "3.0", "Gdk": "3.0", "GtkLayerShell": "0.1", "GObject": "2.0"})


class PopoverManager:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        logger.debug("INIT: PopoverManager")
        self.overlay = WaylandWindow(
            name="popover-overlay",
            style_classes=["popover-overlay"],
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
        self.active_popover: Union["Popover", None] = None
        self.available_windows: List[WaylandWindow] = []
        self.overlay.connect("button-press-event", self._on_overlay_clicked)
        try:
            self._hyprland_connection = get_hyprland_connection()
            if self._hyprland_connection:
                self._hyprland_connection.connect("event::focusedmonv2", self._on_monitor_change)
        except Exception as e:
            logger.error(f"PopoverManager: Error with Hyprland connection: {e}")
            self._hyprland_connection = None

    def _on_monitor_change(self, _, event: Optional[HyprlandEvent] = None):
        if self.active_popover and hasattr(self.active_popover, "hide_popover"):
            self.active_popover.hide_popover()
        return True

    def _on_overlay_clicked(self, widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if self.active_popover and hasattr(self.active_popover, "hide_popover"):
            self.active_popover.hide_popover()
        return True

    def get_popover_window(self) -> WaylandWindow:
        if self.available_windows:
            window = self.available_windows.pop()
            return window
        window = WaylandWindow(type="popup", layer="overlay", name="popover-window", anchor="left top", visible=False, all_visible=False)
        GtkLayerShell.set_keyboard_interactivity(window, True)
        window.set_keep_above(True)
        return window

    def return_popover_window(self, window: WaylandWindow):
        logger.debug(f"PopoverManager: Returning window {window} to pool.")

        # Robust check if the window is still a valid Gtk.Widget that can be manipulated
        # GObject.is_valid() is not a public API.
        # A common check is if it still has an associated Gdk.Window or if essential methods exist.
        # fabric.widgets.wayland.WaylandWindow should be a Gtk.Window.
        # Gtk.Window.is_active() or Gtk.Widget.get_mapped() can be indicators.
        # Gtk.Widget.get_window() returns its Gdk.Window.

        can_manipulate = False
        if window and isinstance(window, Gtk.Widget):
            # If it has a Gdk.Window, it's likely still somewhat valid on the GTK side.
            # If it's a Gtk.Container, we can try to remove children.
            if window.get_window() and isinstance(window, Gtk.Container):
                can_manipulate = True
            elif not window.get_window():
                logger.warning(
                    f"PopoverManager: Window {window} has no Gdk.Window (likely unmapped/destroyed). Cannot reliably remove children."
                )
            elif not isinstance(window, Gtk.Container):
                logger.warning(f"PopoverManager: Window {window} is not a Gtk.Container.")
        else:
            logger.warning(f"PopoverManager: Window {window} is None or not a Gtk.Widget.")

        if can_manipulate:
            # Ensure all children are removed before hiding or pooling
            children = list(window.get_children())
            for child in children:
                # logger.debug(f"PopoverManager: Removing child {child} from window {window} before pooling.")
                window.remove(child)  # This should unparent the child

            if window.get_visible():  # Hide if it was somehow still visible
                window.hide()

        # Now decide whether to pool or destroy the window shell
        # The most important thing is that Gtk.Widget.destroy() is safe to call multiple times.
        # If window.get_window() is None, it's already on its way out or gone.
        should_destroy = True  # Default to destroying if unsure
        if window and window.get_window():  # If it still has a Gdk.Window
            if len(self.available_windows) < 5:
                self.available_windows.append(window)
                logger.debug(f"PopoverManager: Window {window} added to pool. Pool size: {len(self.available_windows)}")
                should_destroy = False  # It's been pooled
            else:
                logger.debug(f"PopoverManager: Pool full. Marking for destruction: {window}.")
        elif window:
            logger.debug(f"PopoverManager: Window {window} has no Gdk.Window. Marking for destruction.")
        else:
            logger.warning("PopoverManager: Attempted to return a None window to pool.")
            should_destroy = False  # Nothing to destroy

        if should_destroy and window:
            window.destroy()
            logger.debug(f"PopoverManager: Window {window} destroyed.")

    def activate_popover(self, popover: "Popover"):
        if self.active_popover and self.active_popover != popover and hasattr(self.active_popover, "hide_popover"):
            self.active_popover.hide_popover()
        self.active_popover = popover
        if not self.overlay.get_visible():
            self.overlay.show()


@GObject.Signal(flags=GObject.SignalFlags.RUN_LAST, return_type=GObject.TYPE_NONE, arg_types=())
def popover_opened(widget: Widget): ...


@GObject.Signal(flags=GObject.SignalFlags.RUN_LAST, return_type=GObject.TYPE_NONE, arg_types=())
def popover_closed(widget: Widget): ...


@GObject.type_register
class Popover(Widget):
    __gsignals__: ClassVar = {
        "popover-opened": (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, ()),
        "popover-closed": (GObject.SignalFlags.RUN_LAST, GObject.TYPE_NONE, ()),
    }

    def __init__(self, point_to: Gtk.Widget, content_factory=None, content=None, **kwargs):
        super().__init__(**kwargs)
        logger.debug(f"INIT: Popover for point_to: {point_to}")
        self._content_factory = content_factory
        self._point_to = point_to
        self._content_window: Optional[WaylandWindow] = None
        self._content: Optional[Gtk.Widget] = content
        self._visible: bool = False
        self._destroy_timeout: Optional[int] = None
        self._manager: PopoverManager = PopoverManager.get_instance()
        self._key_press_handler_id: Optional[int] = None
        self._focus_out_handler_id: Optional[int] = None
        self._content_draw_handler_id: Optional[int] = None

    def _on_key_press(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_popover()
            return True
        return False

    def open(self, *_):
        logger.info(f"Popover.open called. _content_window: {self._content_window}, _visible: {self._visible}")
        if self._destroy_timeout is not None:
            GLib.source_remove(self._destroy_timeout)
            self._destroy_timeout = None
        if not self._content_window:
            try:
                self._create_popover()
            except Exception as e:
                logger.error(f"Popover.open: _create_popover FAILED: {e}", exc_info=True)
                return
        elif not self._visible and self._content_window:
            self._manager.activate_popover(self)
            self._content_window.show_all()
            if hasattr(self._content_window, "steal_input"):
                self._content_window.steal_input()
            self._visible = True
        else:
            self._manager.activate_popover(self)
            if self._content_window and hasattr(self._content_window, "steal_input"):
                self._content_window.steal_input()
        if self._visible:
            self.emit("popover-opened")

    def _calculate_margins(self) -> List[int]:
        if not (self._point_to and self._point_to.get_window() and self._content_window and self._content_window.get_realized()):
            return [0, 0, 0, 0]
        widget_alloc = self._point_to.get_allocation()
        popover_alloc = self._content_window.get_allocation()
        pw = popover_alloc.width
        if pw <= 1:
            req_w, _ = self._content_window.get_preferred_size()
            pw = req_w.width if req_w.width > 1 else pw
        display = self._point_to.get_display()
        monitor = display.get_monitor_at_window(self._point_to.get_window())
        if not monitor:
            return [widget_alloc.y - 5, 0, 0, widget_alloc.x]
        mon_geom = monitor.get_geometry()
        x = widget_alloc.x + (widget_alloc.width / 2) - (pw / 2)
        y = widget_alloc.y - 5
        x = max(mon_geom.x, min(x, mon_geom.x + mon_geom.width - pw))
        return [int(y), 0, 0, int(x)]

    def set_position(self, position: Optional[Tuple[int, int, int, int]] = None) -> bool:
        if not self._content_window:
            return False
        margins = position if position is not None else self._calculate_margins()
        if hasattr(self._content_window, "set_margin"):
            self._content_window.set_margin(margins)
        return False

    def _on_content_ready(self, widget: Gtk.Widget, cr: cairo.Context):
        self.set_position()
        return False

    def _create_popover(self):
        logger.debug("Popover._create_popover: Starting.")
        if self._content is None and self._content_factory:
            self._content = self._content_factory()
            if self._content and hasattr(self._content, "set_actual_popover_instance"):
                self._content.set_actual_popover_instance(self)
        if not self._content or not isinstance(self._content, Gtk.Widget):
            raise ValueError(f"Popover content invalid: {self._content}")

        self._content_window = self._manager.get_popover_window()

        if (
            self._content_draw_handler_id
            and self._content
            and hasattr(self._content, "handler_is_connected")
            and self._content.handler_is_connected(self._content_draw_handler_id)
        ):
            self._content.disconnect(self._content_draw_handler_id)
        if (
            self._key_press_handler_id
            and hasattr(self._content_window, "handler_is_connected")
            and self._content_window.handler_is_connected(self._key_press_handler_id)
        ):
            self._content_window.disconnect(self._key_press_handler_id)
        if (
            self._focus_out_handler_id
            and hasattr(self._content_window, "handler_is_connected")
            and self._content_window.handler_is_connected(self._focus_out_handler_id)
        ):
            self._content_window.disconnect(self._focus_out_handler_id)

        if hasattr(self._content, "connect"):
            self._content_draw_handler_id = self._content.connect("draw", self._on_content_ready)

        content_holder = Box(style_classes=["popover-content"])
        content_holder.add(self._content)
        self._content_window.add(content_holder)
        self._focus_out_handler_id = self._content_window.connect("focus-out-event", self._on_popover_focus_out)
        self._key_press_handler_id = self._content_window.connect("key-press-event", self._on_key_press)
        self._manager.activate_popover(self)
        self._content_window.show_all()
        if hasattr(self._content_window, "steal_input"):
            self._content_window.steal_input()
        self._visible = True
        logger.debug("Popover._create_popover: Finished.")

    def _on_popover_focus_out(self, widget: Gtk.Widget, event: Gdk.EventFocus) -> bool:
        GLib.timeout_add(150, self.hide_popover)
        return False

    def hide_popover(self) -> bool:
        if not self._visible or not self._content_window:
            return False
        logger.info(f"Popover.hide_popover: Hiding window {self._content_window}, overlay {self._manager.overlay}")
        self._content_window.hide()
        self._manager.overlay.hide()
        self._visible = False
        if self._manager.active_popover == self:
            self._manager.active_popover = None
        if not self._destroy_timeout:
            timeout_ms = 1000 * 5
            logger.debug(f"Popover.hide_popover: Scheduling _destroy_popover (resource cleanup) in {timeout_ms}ms.")
            self._destroy_timeout = GLib.timeout_add(timeout_ms, self._destroy_popover)
        self.emit("popover-closed")
        return False

    def _destroy_popover(self) -> bool:
        logger.info(f"Popover._destroy_popover: Current content: {self._content}, window: {self._content_window}")
        self._destroy_timeout = None
        self._visible = False

        # Disconnect handlers FROM self._content_window BEFORE returning it
        if self._content_window:
            if (
                self._key_press_handler_id is not None
                and hasattr(self._content_window, "handler_is_connected")
                and self._content_window.handler_is_connected(self._key_press_handler_id)
            ):
                self._content_window.disconnect(self._key_press_handler_id)
            self._key_press_handler_id = None

            if (
                self._focus_out_handler_id is not None
                and hasattr(self._content_window, "handler_is_connected")
                and self._content_window.handler_is_connected(self._focus_out_handler_id)
            ):
                self._content_window.disconnect(self._focus_out_handler_id)
            self._focus_out_handler_id = None

        # Disconnect draw handler from self._content (which might already be None or destroyed)
        # This check needs to be careful.
        temp_content_for_disconnect = self._content  # Use a temp var as self._content will be set to None
        if (
            self._content_draw_handler_id is not None
            and temp_content_for_disconnect
            and hasattr(temp_content_for_disconnect, "handler_is_connected")
            and temp_content_for_disconnect.handler_is_connected(self._content_draw_handler_id)
        ):
            try:
                temp_content_for_disconnect.disconnect(self._content_draw_handler_id)
            except Exception as e:
                logger.warning(f"Popover: Error disconnecting content_draw_handler from {temp_content_for_disconnect}: {e}")
        self._content_draw_handler_id = None

        # "Scenario A" style: Nullify content ref. Its destroy() should be called by its owner.
        self._content = None

        if self._content_window:
            self._manager.return_popover_window(self._content_window)  # Now this should be safer
            self._content_window = None
        logger.debug("Popover._destroy_popover: Finished.")
        return False

    def destroy(self):
        logger.info(f"DESTROY: Popover instance ({self})")
        if self._destroy_timeout is not None:
            GLib.source_remove(self._destroy_timeout)
            self._destroy_timeout = None
        if self._content and hasattr(self._content, "destroy"):
            self._content.destroy()
        self._content = None
        if self._content_window:
            self._content_window.destroy()
            self._content_window = None
        if self._manager.active_popover == self:
            self._manager.active_popover = None
            # Check if overlay is a valid Gtk.Widget before calling methods
            if (
                self._manager.overlay
                and isinstance(self._manager.overlay, Gtk.Widget)
                and hasattr(self._manager.overlay, "get_visible")
                and self._manager.overlay.get_visible()
            ):
                self._manager.overlay.hide()
        super().destroy()
