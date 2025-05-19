import gi

gi.require_version("Gtk", "3.0")
import contextlib

from fabric.widgets.box import Box
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import GLib, Gtk, Pango
from loguru import logger

from services import audio_service
from shared.buttons import ScanButton
from shared.submenu import QuickSubMenu
from utils.icons import icons

from ..sliders.mic import MicrophoneSlider


class MicroPhoneSubMenu(QuickSubMenu):
    def __init__(self, **kwargs):
        self.client = audio_service
        self._client_streams_changed_sid = None

        self.scan_button = ScanButton()

        self.app_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            name="app-list",
            visible=True,
        )
        self.app_list.get_style_context().add_class("menu")

        self.child_scrolled_window = ScrolledWindow(
            min_content_height=80,
            max_content_height=200,
            propagate_natural_width=True,
            propagate_natural_height=True,
            h_scrollbar_policy=Gtk.PolicyType.NEVER,
            v_scrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            child=self.app_list,
        )

        super().__init__(
            title="Application Microphones",
            title_icon=str(icons.get("audio", {}).get("mic", {}).get("high", "audio-input-microphone-symbolic")),
            scan_button=self.scan_button,
            child=self.child_scrolled_window,
            **kwargs,
        )
        self.scan_button.connect("clicked", self.update_apps_idle)

        if self.client:
            self._client_streams_changed_sid = self.client.connect("changed", self.update_apps_idle)

        self.update_apps_idle()

        self.connect("destroy", self._on_destroy)

    def update_apps_idle(self, *args):
        GLib.idle_add(self.update_apps, priority=GLib.PRIORITY_DEFAULT_IDLE)
        return GLib.SOURCE_REMOVE

    def update_apps(self, *_):
        if not isinstance(self.app_list, Gtk.Widget) or not self.app_list.get_realized():
            if hasattr(self.scan_button, "set_sensitive"):
                self.scan_button.set_sensitive(True)
            if hasattr(self.scan_button, "stop_animation"):
                self.scan_button.stop_animation()
            return GLib.SOURCE_REMOVE

        if hasattr(self.scan_button, "set_sensitive"):
            self.scan_button.set_sensitive(False)
        if hasattr(self.scan_button, "play_animation"):
            self.scan_button.play_animation()

        for child in self.app_list.get_children():
            self.app_list.remove(child)

        app_mic_streams = []
        if self.client:
            if hasattr(self.client, "recorders") and isinstance(self.client.recorders, list):
                app_mic_streams = self.client.recorders
            elif hasattr(self.client, "microphones") and isinstance(self.client.microphones, list):
                app_mic_streams = [s for s in self.client.microphones if getattr(s, "is_application", False)]
                if not app_mic_streams and self.client.microphones:
                    logger.info("MicroPhoneSubMenu: Used client.microphones, but filter 'is_application' found none. Listing all if any.")

        if not app_mic_streams:
            self.app_list.add(
                Label(
                    label="No applications using microphone",
                    style_classes=["menu-item", "placeholder-label"],
                    halign=Gtk.Align.CENTER,
                    valign=Gtk.Align.CENTER,
                    hexpand=True,
                    vexpand=True,
                )
            )
        else:
            for app_stream in app_mic_streams:
                if not app_stream:
                    logger.warning("MicroPhoneSubMenu: Encountered a None stream in app_mic_streams list.")
                    continue

                row = Gtk.ListBoxRow(activatable=False, selectable=False)
                row.get_style_context().add_class("menu-item")

                item_box = Box(name="list-box-row", orientation="v", spacing=8, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)

                name_box = Box(orientation="h", spacing=10, hexpand=True)

                stream_icon_name_raw = getattr(app_stream, "icon_name", None) or icons.get("audio", {}).get("mic", {}).get(
                    "medium", "audio-input-microphone-symbolic"
                )
                stream_icon_name = str(stream_icon_name_raw) if stream_icon_name_raw is not None else "audio-input-microphone-symbolic"
                app_icon_img = Image(icon_name=stream_icon_name, icon_size=16)
                name_box.pack_start(app_icon_img, False, False, 0)

                stream_name = getattr(app_stream, "name", "Unknown App")
                stream_desc = getattr(app_stream, "description", stream_name)
                app_name_label = Label(
                    label=stream_name,
                    style_classes=["submenu-item-label"],
                    h_align=Gtk.Align.START,
                    tooltip_text=stream_desc,
                    ellipsization=Pango.EllipsizeMode.END,
                )
                name_box.pack_start(app_name_label, True, True, 0)
                item_box.add(name_box)

                app_slider = MicrophoneSlider(audio_stream=app_stream, show_chevron=False)

                slider_container = Box(margin_start=20)
                slider_container.add(app_slider)
                item_box.add(slider_container)

                row.add(item_box)
                self.app_list.add(row)

        self.app_list.show_all()
        if hasattr(self.scan_button, "set_sensitive"):
            self.scan_button.set_sensitive(True)
        if hasattr(self.scan_button, "stop_animation"):
            self.scan_button.stop_animation()
        return GLib.SOURCE_REMOVE

    def _disconnect_signal(self, obj, sid):
        if obj and sid is not None and hasattr(obj, "handler_is_connected") and obj.handler_is_connected(sid):
            with contextlib.suppress(Exception):
                obj.disconnect(sid)
                return True
        return False

    def _on_destroy(self, *args):
        if self.client:
            self._disconnect_signal(self.client, self._client_streams_changed_sid)
        self._client_streams_changed_sid = None
