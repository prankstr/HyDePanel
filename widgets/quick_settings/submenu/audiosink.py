from fabric.utils import exec_shell_command_async
from fabric.widgets.box import Box
from fabric.widgets.image import Image
from fabric.widgets.label import Label # Gtk.Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import Gtk, GObject, GLib, Pango # Import Pango for EllipsizeMode

from services import audio_service
from shared.buttons import ScanButton
from shared.submenu import QuickSubMenu
from utils.icons import icons

AudioStream = GObject.Object

class AudioSinkSubMenu(QuickSubMenu):
    # ... (constructor and other methods remain the same) ...
    def __init__(self, **kwargs):
        self.client = audio_service

        self.scan_button = ScanButton()
        self.scan_button.connect("clicked", lambda _: self.update_sinks(force_rescan=True))

        self.sink_list_box = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE, name="sink-list", visible=True,
        )
        self.sink_list_box.get_style_context().add_class("menu")
        self.sink_list_box.connect("row-activated", self._on_sink_activated)

        self.scrolled_window_child = ScrolledWindow(
            min_content_height=80, max_content_height=240,
            propagate_natural_width=True, propagate_natural_height=True, # Important for sizing
            h_scrollbar_policy=Gtk.PolicyType.NEVER, v_scrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            child=self.sink_list_box,
        )

        super().__init__(
            title="Playback Devices",
            title_icon=icons.get("audio", {}).get("settings", "audio-card-symbolic"),
            scan_button=self.scan_button,
            child=self.scrolled_window_child,
            **kwargs,
        )

        self.set_hexpand(False) # Call this AFTER super().__init__()
        self.client.connect("changed", self.update_sinks)
        self.client.connect("speaker-changed", self.update_sinks)
        GLib.idle_add(self._do_update_sinks)

    def _handle_command_completion(self, stdout: str, stderr: str, exit_code: int, command_desc: str):
        if exit_code == 0:
            print(f"Success: {command_desc}. Output: {stdout.strip()}")
        else:
            print(f"Error: {command_desc} failed (Code: {exit_code}). Stderr: {stderr.strip()}. Stdout: {stdout.strip()}")

    def _set_default_sink_external(self, sink_stream: AudioStream):
        pactl_sink_name = sink_stream.name
        wpctl_sink_id_str = str(sink_stream.id)

        if pactl_sink_name:
            command_pactl = ["pactl", "set-default-sink", pactl_sink_name]
            exec_shell_command_async(
                command_pactl,
                lambda out, err, code: self._handle_command_completion(
                    out, err, code, f"pactl set-default-sink {pactl_sink_name}"
                )
            )

        command_wpctl = ["wpctl", "set-default", wpctl_sink_id_str]
        exec_shell_command_async(
            command_wpctl,
            lambda out, err, code: self._handle_command_completion(
                out, err, code, f"wpctl set-default {wpctl_sink_id_str}"
            )
        )

    def _on_sink_activated(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow):
        selected_sink: AudioStream = getattr(row, "_sink_object", None)
        if selected_sink:
            if self.client.speaker and selected_sink.id == self.client.speaker.id:
                return
            self._set_default_sink_external(selected_sink)
        else:
            print("Warning: _on_sink_activated called but no _sink_object found on the row.")


    def update_sinks(self, *args, force_rescan=False):
        GLib.idle_add(self._do_update_sinks, force_rescan, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def _get_custom_sink_icon_name(self, sink: AudioStream) -> str:
        name_lower = (sink.name or "").lower()
        description_lower = (sink.description or "").lower()

        if "steelseries" in name_lower or "steelseries" in description_lower:
            return icons.get("devices", {}).get("headset", "audio-headphones-symbolic")

        headphone_keywords = ["headphone", "headset", "earphone", "arctis", "hs80"]
        for keyword in headphone_keywords:
            if keyword in name_lower or keyword in description_lower:
                return icons.get("devices", {}).get("headset", "audio-headphones-symbolic")

        speaker_keywords = ["speaker", "hdmi", "displayport", "line out", "analog"]
        for keyword in speaker_keywords:
            if keyword in name_lower or keyword in description_lower:
                is_also_headphone = any(hk in name_lower or hk in description_lower for hk in headphone_keywords)
                if not is_also_headphone:
                    return icons.get("devices", {}).get("speakers", "multimedia-speakers-symbolic")
        if sink.icon_name:
            return sink.icon_name
        return icons.get("devices", {}).get("default_audio_output", "audio-card-symbolic")

    def _do_update_sinks(self, force_rescan=False):
        self.scan_button.set_sensitive(False)
        if hasattr(self.scan_button, 'play_animation'):
            self.scan_button.play_animation()

        children = self.sink_list_box.get_children()
        for child in children:
            self.sink_list_box.remove(child)

        available_sinks: list[AudioStream] = self.client.speakers
        current_default_sink: AudioStream = self.client.speaker

        if not available_sinks:
            self.sink_list_box.add(
                Label(label="No playback devices found", style_classes=["menu-item", "placeholder-label"],
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, hexpand=True, vexpand=True)
            )
        else:
            current_default_sink_id_val = getattr(current_default_sink, 'id', None) if current_default_sink else None

            for sink in available_sinks:
                row = Gtk.ListBoxRow(activatable=True, selectable=False)
                row.get_style_context().add_class("menu-item")
                row._sink_object = sink

                is_active = (current_default_sink_id_val is not None and sink.id == current_default_sink_id_val)

                # The Gtk.Box that holds the icon, label, and active indicator for a single sink row.
                # Crucially, this Box itself should NOT expand horizontally if its contents (the label) are too wide.
                # The Label inside will be told to ellipsize.
                item_box = Box(
                    orientation="h",
                    spacing=10,
                    h_expand=False, # Make sure the item_box itself doesn't try to expand unnecessarily
                    # margin_start=6, margin_end=6, margin_top=6, margin_bottom=6 # Already have this
                )
                item_box.set_margin_start(6)
                item_box.set_margin_end(6)
                item_box.set_margin_top(6)
                item_box.set_margin_bottom(6)


                chosen_icon_name = self._get_custom_sink_icon_name(sink)
                icon = Image(icon_name=chosen_icon_name, icon_size=16)
                # Icon should not expand or fill
                item_box.pack_start(icon, False, False, 0)

                # Determine the full text for display and tooltip
                # Prefer description if available and not empty, otherwise use name
                full_display_text = sink.description.strip() if sink.description and sink.description.strip() else sink.name
                full_display_text = full_display_text or "Unknown Sink" # Fallback if both are empty

                name_label = Label(
                    label=full_display_text,
                    style_classes=["submenu-item-label", "sink-name-label"],
                    h_align="start",  # Gtk.Align.START might also work if fabric.Label maps it. "start" is safer.
                    # Use fabric.widgets.Label properties, consistent with PlayerBox:
                    ellipsization="end",
                    max_chars_width=30, # Adjust as needed, or use a config value. This matches your Gtk max_width_chars.
                    tooltip_text=full_display_text,
                    # Sizing behavior for the label:
                    # hexpand=True is okay, it means the label will try to fill the space given to it by item_box.
                    # If item_box gets constrained, the label will fill that smaller space and ellipsize.
                    hexpand=True,
                    vexpand=False,
                )
                # Label should expand and fill within its allocated space in the item_box
                item_box.pack_start(name_label, True, True, 0)

                if is_active:
                    active_icon_name = icons.get("status", {}).get("checkmark", "object-select-symbolic")
                    active_indicator = Image(icon_name=active_icon_name, icon_size=16, name="active-sink-indicator")
                    # Active indicator should not expand
                    item_box.pack_end(active_indicator, False, False, 0)
                    row.get_style_context().add_class("active-sink")

                row.add(item_box)
                self.sink_list_box.add(row)

        self.sink_list_box.show_all()
        self.scan_button.set_sensitive(True)
        return GLib.SOURCE_REMOVE
