import gi

gi.require_version("Gtk", "3.0")
import contextlib

from fabric.utils import exec_shell_command_async
from fabric.widgets.box import Box
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import GLib, GObject, Gtk, Pango
from loguru import logger

from services import audio_service
from shared.buttons import ScanButton
from shared.submenu import QuickSubMenu
from utils.icons import icons

AudioStream = GObject.Object


class AudioSinkSubMenu(QuickSubMenu):
    def __init__(self, **kwargs):
        self.client = audio_service
        self._client_changed_sid = None
        self._client_speaker_changed_sid = None

        self.scan_button = ScanButton()

        self.sink_list_box = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            name="sink-list",
            visible=True,
        )
        self.sink_list_box.get_style_context().add_class("menu")

        if not hasattr(self, "_on_sink_activated"):
            logger.error("AudioSinkSubMenu FATAL: _on_sink_activated method is not defined before connecting signal!")
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
        self.scan_button.connect("clicked", lambda _: self.update_sinks(force_rescan=True))

        self.set_hexpand(False)
        if self.client:
            self._client_changed_sid = self.client.connect("changed", self.update_sinks)
            self._client_speaker_changed_sid = self.client.connect("speaker-changed", self.update_sinks)

        GLib.idle_add(self._do_update_sinks)

        self.connect("destroy", self._on_destroy)

    def _handle_command_completion(self, stdout: str, stderr: str, exit_code: int, command_desc: str):
        if exit_code == 0:
            logger.info(f"Success: {command_desc}.")
        else:
            logger.error(f"Error: {command_desc} failed (Code: {exit_code}). Stderr: {stderr.strip()}. Stdout: {stdout.strip()}")

    def _set_default_sink_external(self, sink_stream: AudioStream):
        if not sink_stream:
            logger.warning("AudioSinkSubMenu: _set_default_sink_external called with no sink_stream.")
            return

        pactl_sink_name = getattr(sink_stream, "name", None)
        wpctl_sink_id_str = str(getattr(sink_stream, "id", None))

        if pactl_sink_name:
            command_pactl = ["pactl", "set-default-sink", pactl_sink_name]
            exec_shell_command_async(
                command_pactl,
                lambda out, err, code: self._handle_command_completion(out, err, code, f"pactl set-default-sink {pactl_sink_name}"),
            )

        if wpctl_sink_id_str and wpctl_sink_id_str != "None":
            command_wpctl = ["wpctl", "set-default", wpctl_sink_id_str]
            exec_shell_command_async(
                command_wpctl,
                lambda out, err, code: self._handle_command_completion(out, err, code, f"wpctl set-default {wpctl_sink_id_str}"),
            )

    def _on_sink_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow):
        selected_sink: AudioStream = getattr(row, "_sink_object", None)
        if selected_sink:
            is_already_default = False
            if self.client and self.client.speaker:
                current_speaker_id = getattr(self.client.speaker, "id", None)
                selected_sink_id = getattr(selected_sink, "id", None)
                if current_speaker_id is not None and selected_sink_id is not None and current_speaker_id == selected_sink_id:
                    is_already_default = True

            if is_already_default:
                return

            logger.info(f"AudioSinkSubMenu: Activating sink '{getattr(selected_sink, 'name', 'Unknown')}'.")
            self._set_default_sink_external(selected_sink)
        else:
            logger.warning("AudioSinkSubMenu: _on_sink_activated called but no _sink_object found on the row.")

    def update_sinks(self, *args, force_rescan=False):
        GLib.idle_add(self._do_update_sinks, force_rescan, priority=GLib.PRIORITY_DEFAULT_IDLE)
        return GLib.SOURCE_REMOVE

    def _get_custom_sink_icon_name(self, sink: AudioStream) -> str:
        name_lower = (getattr(sink, "name", "") or "").lower()
        description_lower = (getattr(sink, "description", "") or "").lower()
        sink_icon_name_prop = getattr(sink, "icon_name", None)

        if "steelseries" in name_lower or "steelseries" in description_lower:
            return str(icons.get("devices", {}).get("headset", "audio-headphones-symbolic"))

        headphone_keywords = ["headphone", "headset", "earphone", "arctis", "hs80", "headphones"]
        for keyword in headphone_keywords:
            if keyword in name_lower or keyword in description_lower:
                return str(icons.get("devices", {}).get("headset", "audio-headphones-symbolic"))

        speaker_keywords = ["speaker", "hdmi", "displayport", "line out", "analog output", "speakers"]
        for keyword in speaker_keywords:
            if keyword in name_lower or keyword in description_lower:
                is_also_headphone = any(hk_word in name_lower or hk_word in description_lower for hk_word in headphone_keywords)
                if not is_also_headphone:
                    return str(icons.get("devices", {}).get("speakers", "multimedia-speakers-symbolic"))

        if sink_icon_name_prop and isinstance(sink_icon_name_prop, str):
            return sink_icon_name_prop

        return str(icons.get("devices", {}).get("default_audio_output", "audio-card-symbolic"))

    def _do_update_sinks(self, force_rescan=False):
        if not isinstance(self.sink_list_box, Gtk.Widget) or not self.sink_list_box.get_realized():
            if hasattr(self.scan_button, "set_sensitive"):
                self.scan_button.set_sensitive(True)
            if hasattr(self.scan_button, "stop_animation"):
                self.scan_button.stop_animation()
            return GLib.SOURCE_REMOVE

        if hasattr(self.scan_button, "set_sensitive"):
            self.scan_button.set_sensitive(False)
        if hasattr(self.scan_button, "play_animation"):
            self.scan_button.play_animation()

        for child in self.sink_list_box.get_children():
            self.sink_list_box.remove(child)

        available_sinks: list[AudioStream] = self.client.speakers if self.client and hasattr(self.client, "speakers") else []
        current_default_sink: AudioStream = self.client.speaker if self.client and hasattr(self.client, "speaker") else None

        if not available_sinks:
            self.sink_list_box.add(
                Label(
                    label="No playback devices found",
                    style_classes=["menu-item", "placeholder-label"],
                    halign=Gtk.Align.CENTER,
                    valign=Gtk.Align.CENTER,
                    hexpand=True,
                    vexpand=True,
                )
            )
        else:
            current_default_sink_id_val = getattr(current_default_sink, "id", None) if current_default_sink else None

            for sink in available_sinks:
                row = Gtk.ListBoxRow(activatable=True, selectable=True)
                row.get_style_context().add_class("menu-item")
                row._sink_object = sink

                is_active = current_default_sink_id_val is not None and hasattr(sink, "id") and sink.id == current_default_sink_id_val

                item_box = Box(orientation="h", spacing=10, hexpand=False)
                item_box.set_margin_start(6)
                item_box.set_margin_end(6)
                item_box.set_margin_top(6)
                item_box.set_margin_bottom(6)

                chosen_icon_name = self._get_custom_sink_icon_name(sink)
                icon = Image(icon_name=chosen_icon_name, icon_size=16)
                item_box.pack_start(icon, False, False, 0)

                full_display_text = (getattr(sink, "description", "").strip() or getattr(sink, "name", "")).strip() or "Unknown Sink"

                name_label = Label(
                    label=full_display_text,
                    style_classes=["submenu-item-label", "sink-name-label"],
                    h_align=Gtk.Align.START,
                    ellipsization=Pango.EllipsizeMode.END,
                    tooltip_text=full_display_text,
                    hexpand=True,
                )
                item_box.pack_start(name_label, True, True, 0)

                if is_active:
                    active_icon_name_raw = icons.get("status", {}).get("checkmark", "object-select-symbolic")
                    active_icon_name = str(active_icon_name_raw) if active_icon_name_raw is not None else "object-select-symbolic"
                    active_indicator = Image(icon_name=active_icon_name, icon_size=16, name="active-sink-indicator")
                    item_box.pack_end(active_indicator, False, False, 0)
                    row.get_style_context().add_class("active-sink")

                row.add(item_box)
                self.sink_list_box.add(row)

        self.sink_list_box.show_all()
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
            self._disconnect_signal(self.client, self._client_changed_sid)
            self._disconnect_signal(self.client, self._client_speaker_changed_sid)
        self._client_changed_sid = None
        self._client_speaker_changed_sid = None
