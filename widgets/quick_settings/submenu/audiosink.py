# widgets/quick_settings/submenu/audiosink.py

from typing import Optional, List
from fabric.utils import exec_shell_command_async
from fabric.widgets.box import Box
from fabric.widgets.image import Image
from fabric.widgets.label import Label  # fabric.widgets.label.Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import Gtk, GObject, GLib, Pango
from loguru import logger

from services import audio_service
from shared.buttons import ScanButton
from shared.submenu import QuickSubMenu
from utils.icons import icons

AudioStream = GObject.Object


class AudioSinkSubMenu(QuickSubMenu):
    def __init__(self, **kwargs):
        logger.info(f"INIT: {self.__class__.__name__}")
        self.client = audio_service
        self._client_changed_handler_id: Optional[int] = None
        self._client_speaker_changed_handler_id: Optional[int] = None
        self._update_sinks_timeout_id: Optional[int] = None

        self.scan_button = ScanButton()
        self.scan_button.connect("clicked", lambda _: self.update_sinks(force_rescan=True))

        self.sink_list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, name="sink-list", visible=True)
        self.sink_list_box.get_style_context().add_class("menu")
        self.sink_list_box.connect("row-activated", self._on_sink_activated)

        self.scrolled_window_child = ScrolledWindow(
            min_content_height=80,
            max_content_height=240,
            propagate_natural_width=True,
            propagate_natural_height=True,
            h_scrollbar_policy=Gtk.PolicyType.NEVER,
            v_scrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            child=self.sink_list_box,
        )

        super().__init__(
            title="Playback Devices",
            title_icon=str(icons.get("audio", {}).get("settings", "audio-card-symbolic")),
            scan_button=self.scan_button,
            child=self.scrolled_window_child,
            **kwargs,
        )
        self.set_hexpand(False)

        if self.client:
            self._client_changed_handler_id = self.client.connect("changed", self.update_sinks)
            self._client_speaker_changed_handler_id = self.client.connect("speaker-changed", self.update_sinks)
        else:
            logger.error(f"INIT: {self.__class__.__name__} - audio_service (self.client) is None!")
        GLib.idle_add(self._do_update_sinks, False)

    def _handle_command_completion(self, stdout: str, stderr: str, exit_code: int, command_desc: str):
        if exit_code == 0:
            logger.info(f"Success: {command_desc}.")
        else:
            logger.error(f"Error: {command_desc} (Code: {exit_code}). Stderr: {stderr.strip()}.")

    def _set_default_sink_external(self, sink_stream: AudioStream):
        pactl_name = getattr(sink_stream, "name", None)
        wp_id = str(getattr(sink_stream, "id", "NO_ID"))
        if pactl_name:
            exec_shell_command_async(
                ["pactl", "set-default-sink", pactl_name],
                lambda o, e, c: self._handle_command_completion(o, e, c, f"pactl set {pactl_name}"),
            )
        if wp_id != "NO_ID":
            exec_shell_command_async(
                ["wpctl", "set-default", wp_id], lambda o, e, c: self._handle_command_completion(o, e, c, f"wpctl set {wp_id}")
            )

    def _on_sink_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow):
        selected = getattr(row, "_sink_object", None)
        if selected and not (self.client.speaker and getattr(selected, "id", -1) == getattr(self.client.speaker, "id", -2)):
            self._set_default_sink_external(selected)

    def update_sinks(self, *args, force_rescan: bool = False):
        if self._update_sinks_timeout_id is not None:
            GLib.source_remove(self._update_sinks_timeout_id)
        delay = 10 if force_rescan else 250
        self._update_sinks_timeout_id = GLib.timeout_add(delay, self._execute_do_update_sinks_once, force_rescan)
        return False

    def _execute_do_update_sinks_once(self, force_rescan: bool = False) -> bool:
        if self._update_sinks_timeout_id is not None:
            self._update_sinks_timeout_id = None
        self._do_update_sinks(force_rescan)
        return GLib.SOURCE_REMOVE

    def _get_custom_sink_icon_name(self, sink: AudioStream) -> str:
        nl = (getattr(sink, "name", None) or "").lower()
        dl = (getattr(sink, "description", None) or "").lower()
        pi = getattr(sink, "icon_name", None)
        df = str(icons.get("devices", {}).get("default_audio_output", "audio-card-symbolic"))
        ih = str(icons.get("devices", {}).get("headset", "audio-headphones-symbolic"))
        isp = str(icons.get("devices", {}).get("speakers", "multimedia-speakers-symbolic"))
        if "steelseries" in nl or "steelseries" in dl:
            return ih
        hpw = ["headphone", "headset", "earphone", "arctis", "hs80", "bluetooth"]
        spkw = ["speaker", "hdmi", "dp", "line out", "analog", "speakers"]
        if any(k in nl or k in dl for k in hpw):
            return ih
        if any(k in nl or k in dl for k in spkw) and not any(h in nl or h in dl for h in hpw):
            return isp
        return str(pi) if pi else df

    def _do_update_sinks(self, force_rescan: bool = False):
        if not self.get_visible() or not self.get_realized():
            if not force_rescan:
                logger.debug(f"{self.__class__.__name__}: Update called while NOT visible/realized. Skipping.")
                return GLib.SOURCE_REMOVE  # Changed to DEBUG
        if hasattr(self.scan_button, "set_sensitive"):
            self.scan_button.set_sensitive(False)
        if hasattr(self.scan_button, "play_animation") and callable(self.scan_button.play_animation):
            self.scan_button.play_animation()
        for child in list(self.sink_list_box.get_children()):
            self.sink_list_box.remove(child)
            child.destroy()
        sinks = getattr(self.client, "speakers", [])
        def_sink = getattr(self.client, "speaker", None)
        if not sinks:
            self.sink_list_box.add(
                Label(
                    label="No playback devices",
                    style_classes=["menu-item", "placeholder-label"],
                    halign=Gtk.Align.CENTER,
                    valign=Gtk.Align.CENTER,
                    hexpand=True,
                    vexpand=True,
                )
            )
        else:
            def_id = getattr(def_sink, "id", None)
            for s in sinks:
                r = Gtk.ListBoxRow(activatable=True, selectable=True)
                r.get_style_context().add_class("menu-item")
                r._sink_object = s
                act = def_id is not None and getattr(s, "id", -1) == def_id
                b = Box(orientation="h", spacing=10, h_expand=False)
                b.set_margin_start(6)
                b.set_margin_end(6)
                b.set_margin_top(6)
                b.set_margin_bottom(6)
                i = Image(icon_name=self._get_custom_sink_icon_name(s), icon_size=16)
                b.pack_start(i, False, False, 0)
                t = getattr(s, "description", "").strip() or getattr(s, "name", "") or "Unknown"
                l = Label(
                    label=t,
                    style_classes=["submenu-item-label", "sink-name-label"],
                    h_align="start",
                    ellipsization="end",
                    max_chars_width=30,
                    tooltip_text=t,
                    hexpand=True,
                    vexpand=False,
                )
                b.pack_start(l, True, True, 0)
                if act:
                    ind = Image(icon_name=str(icons.get("status", {}).get("checkmark", "object-select-symbolic")), icon_size=16)
                    b.pack_end(ind, False, False, 0)
                    r.get_style_context().add_class("active-sink")
                r.add(b)
                self.sink_list_box.add(r)
        self.sink_list_box.show_all()
        if hasattr(self.scan_button, "set_sensitive"):
            self.scan_button.set_sensitive(True)
        if hasattr(self.scan_button, "stop_animation") and callable(self.scan_button.stop_animation):
            self.scan_button.stop_animation()
        return GLib.SOURCE_REMOVE

    def destroy(self):
        logger.info(f"DESTROY: {self.__class__.__name__}")
        if self._update_sinks_timeout_id is not None:
            GLib.source_remove(self._update_sinks_timeout_id)
            self._update_sinks_timeout_id = None
        if self.client:
            if (
                self._client_changed_handler_id
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_changed_handler_id)
            ):
                self.client.disconnect(self._client_changed_handler_id)
            if (
                self._client_speaker_changed_handler_id
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_speaker_changed_handler_id)
            ):
                self.client.disconnect(self._client_speaker_changed_handler_id)
        self._client_changed_handler_id = self._client_speaker_changed_handler_id = None
        self.scan_button = self.sink_list_box = self.scrolled_window_child = self.client = None
        super().destroy()
