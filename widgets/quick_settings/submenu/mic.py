# widgets/quick_settings/submenu/mic.py

from typing import Optional, List
from fabric.widgets.box import Box
from fabric.widgets.image import Image
from fabric.widgets.label import Label  # fabric.widgets.label.Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import Gtk, GLib, Pango
from loguru import logger

from services import audio_service
from shared.buttons import ScanButton
from shared.submenu import QuickSubMenu
from utils.icons import icons
from widgets.quick_settings.sliders.mic import MicrophoneSlider


class MicroPhoneSubMenu(QuickSubMenu):
    def __init__(self, **kwargs):
        logger.info(f"INIT: {self.__class__.__name__}")
        self.client = audio_service
        self._client_changed_handler_id: Optional[int] = None
        self._client_mic_specific_handler_id: Optional[int] = None
        self._update_apps_timeout_id: Optional[int] = None

        self.scan_button = ScanButton()
        self.scan_button.connect("clicked", lambda _: self.update_apps(force_update=True))

        self.app_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, name="app-list", visible=True)
        self.app_list.get_style_context().add_class("menu")

        self.scrolled_window_child = ScrolledWindow(
            min_content_height=100,
            max_content_height=200,
            propagate_natural_width=True,
            propagate_natural_height=True,
            h_scrollbar_policy=Gtk.PolicyType.NEVER,
            v_scrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            child=self.app_list,
        )

        super().__init__(
            title="Microphones",
            title_icon=str(icons.get("audio", {}).get("mic", {}).get("high", "audio-input-microphone-symbolic")),
            scan_button=self.scan_button,
            child=self.scrolled_window_child,
            **kwargs,
        )
        self.set_hexpand(False)

        if self.client:
            self._client_changed_handler_id = self.client.connect("changed", self.update_apps)
            if hasattr(self.client, "connect") and callable(self.client.connect):
                try:
                    self._client_mic_specific_handler_id = self.client.connect("microphones-changed", self.update_apps)
                except TypeError:
                    logger.warning(f"INIT: {self.__class__.__name__} - Signal 'microphones-changed' not found on audio_service.")
        else:
            logger.error(f"INIT: {self.__class__.__name__} - audio_service (self.client) is None!")
        GLib.idle_add(self._do_update_apps, False)

    def update_apps(self, *args, force_update: bool = False):
        if self._update_apps_timeout_id is not None:
            GLib.source_remove(self._update_apps_timeout_id)
        delay_ms = 10 if force_update else 250
        self._update_apps_timeout_id = GLib.timeout_add(delay_ms, self._execute_do_update_apps_once, force_update)
        return False

    def _execute_do_update_apps_once(self, force_update: bool = False) -> bool:
        if self._update_apps_timeout_id is not None:
            self._update_apps_timeout_id = None
        self._do_update_apps(force_update)
        return GLib.SOURCE_REMOVE

    def _do_update_apps(self, force_update: bool = False):
        if not self.get_visible() or not self.get_realized():
            if not force_update:
                logger.debug(f"{self.__class__.__name__}: Update called while NOT visible/realized. Skipping.")  # Changed to DEBUG
                if hasattr(self.scan_button, "stop_animation") and callable(self.scan_button.stop_animation):
                    self.scan_button.stop_animation()
                if hasattr(self.scan_button, "set_sensitive"):
                    self.scan_button.set_sensitive(True)
                return GLib.SOURCE_REMOVE

        if hasattr(self.scan_button, "set_sensitive"):
            self.scan_button.set_sensitive(False)
        if hasattr(self.scan_button, "play_animation") and callable(self.scan_button.play_animation):
            self.scan_button.play_animation()

        for child in list(self.app_list.get_children()):
            self.app_list.remove(child)
            if hasattr(child, "destroy"):
                child.destroy()

        microphones_list = getattr(self.client, "microphones", [])
        if not microphones_list:
            self.app_list.add(
                Label(
                    label="No microphones found",
                    style_classes=["menu-item", "placeholder-label"],
                    halign=Gtk.Align.CENTER,
                    valign=Gtk.Align.CENTER,
                    hexpand=True,
                    vexpand=True,
                )
            )
        else:
            for app_stream in microphones_list:
                row = Gtk.ListBoxRow(activatable=False)
                row.get_style_context().add_class("menu-item")
                box = Box(name="list-box-row", orientation="v", spacing=10, margin_start=6, margin_end=6, margin_top=3, margin_bottom=3)
                name_box = Box(orientation="h", spacing=12, h_expand=True)
                app_icon_name = getattr(app_stream, "icon_name", None) or icons.get("audio", {}).get("mic", {}).get(
                    "high", "audio-input-microphone-symbolic"
                )
                icon = Image(icon_name=str(app_icon_name), icon_size=16)
                name_box.pack_start(icon, False, False, 0)
                app_name = str(getattr(app_stream, "name", "Unknown Microphone"))
                app_desc = str(getattr(app_stream, "description", app_name))
                name_label = Label(
                    label=app_name, style_classes=["submenu-item-label"], h_align="start", tooltip_text=app_desc, ellipsization="end"
                )
                name_box.pack_start(name_label, True, True, 0)
                box.add(name_box)
                audio_box = Box(orientation="h", spacing=6, margin_start=24)
                try:
                    mic_slider = MicrophoneSlider(app_stream, show_chevron=False)
                    audio_box.pack_start(mic_slider, True, True, 0)
                except Exception as e:
                    logger.error(f"Error creating MicrophoneSlider for {app_name}: {e}", exc_info=True)
                box.add(audio_box)
                row.add(box)
                self.app_list.add(row)
        self.app_list.show_all()
        if hasattr(self.scan_button, "set_sensitive"):
            self.scan_button.set_sensitive(True)
        if hasattr(self.scan_button, "stop_animation") and callable(self.scan_button.stop_animation):
            self.scan_button.stop_animation()
        return GLib.SOURCE_REMOVE

    def destroy(self):
        logger.info(f"DESTROY: {self.__class__.__name__}")
        if self._update_apps_timeout_id is not None:
            GLib.source_remove(self._update_apps_timeout_id)
            self._update_apps_timeout_id = None
        if self.client:
            if (
                self._client_changed_handler_id
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_changed_handler_id)
            ):
                self.client.disconnect(self._client_changed_handler_id)
            if (
                self._client_mic_specific_handler_id
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_mic_specific_handler_id)
            ):
                self.client.disconnect(self._client_mic_specific_handler_id)
        self._client_changed_handler_id = self._client_mic_specific_handler_id = None
        self.scan_button = self.app_list = self.scrolled_window_child = self.client = None
        super().destroy()
