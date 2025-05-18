import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango, GLib
from loguru import logger  # Optional

from fabric.widgets.box import Box
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow

from services import audio_service
from shared.buttons import ScanButton
from shared.submenu import QuickSubMenu
from utils.icons import icons

# Import the MODIFIED MicrophoneSlider (ensure path is correct)
from ..sliders.mic import MicrophoneSlider  # Assuming sliders dir is one level up from submenu dir


class MicroPhoneSubMenu(QuickSubMenu):
    """A submenu to display mic controls for applications."""

    def __init__(self, **kwargs):
        logger.info("MicroPhoneSubMenu: Initializing...")
        self.client = audio_service
        self._client_recorders_changed_sid = None  # More specific signal if available
        self._client_changed_sid = None  # General fallback

        self.scan_button = ScanButton()

        self.app_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            name="app-list",
            visible=True,
        )
        self.app_list.get_style_context().add_class("menu")

        self.child_scrolled_window = ScrolledWindow(
            min_content_height=80,  # Adjusted from 100
            max_content_height=200,
            propagate_natural_width=True,
            propagate_natural_height=True,
            h_scrollbar_policy=Gtk.PolicyType.NEVER,
            v_scrollbar_policy=Gtk.PolicyType.AUTOMATIC,  # Changed to AUTOMATIC
            child=self.app_list,
        )

        super().__init__(
            title="Application Microphones",
            title_icon=icons.get("audio", {}).get("mic", {}).get("high", "audio-input-microphone-symbolic"),
            scan_button=self.scan_button,
            child=self.child_scrolled_window,
            **kwargs,
        )
        self.scan_button.connect("clicked", self.update_apps_idle)

        if self.client:
            # Prefer a more specific signal if your audio_service provides one for app mic streams
            # For example, 'recorders-changed' or 'microphone-applications-changed'
            if hasattr(self.client, "recorders") and hasattr(self.client, "connect_signal"):  # Example custom signal
                # self._client_recorders_changed_sid = self.client.connect_signal("recorders-changed", self.update_apps_idle)
                pass  # Placeholder for a more specific signal
            else:  # Fallback to general 'changed'
                self._client_changed_sid = self.client.connect("changed", self.update_apps_idle)

        self.update_apps_idle()  # Initial population

        self.connect("destroy", self._on_destroy)
        logger.info("MicroPhoneSubMenu: Initialization complete.")

    def update_apps_idle(self, *args):
        GLib.idle_add(self.update_apps, priority=GLib.PRIORITY_DEFAULT_IDLE)
        return GLib.SOURCE_REMOVE

    def update_apps(self, *_):
        logger.debug("MicroPhoneSubMenu: Updating application microphone list.")
        # MODIFIED LINE HERE
        if not isinstance(self.app_list, Gtk.Widget) or not self.app_list.get_realized():
            logger.warning("MicroPhoneSubMenu: app_list not a valid Gtk.Widget or not realized. Skipping update.")
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
            if hasattr(self.client, "recorders"):
                app_mic_streams = self.client.recorders
            elif hasattr(self.client, "microphones"):
                # This logic needs to be specific to how your audio_service differentiates
                # app streams from device streams if both are in client.microphones.
                # Example: assume an 'is_application_stream' property exists on the stream object.
                app_mic_streams = [m for m in self.client.microphones if hasattr(m, "is_application_stream") and m.is_application_stream]
            if not app_mic_streams and hasattr(self.client, "microphones") and not hasattr(self.client, "recorders"):
                # Fallback: if no 'recorders' and no clear app filter, maybe 'microphones' IS app streams
                # Or maybe it's just all mic inputs including the default device. This is ambiguous.
                # For safety, if you only want app streams, ensure they are identifiable.
                # If client.microphones is just app streams (excluding default device), then this is fine.
                # logger.warning("MicroPhoneSubMenu: 'recorders' not found, using 'microphones'. Ensure this lists app streams.")
                # app_mic_streams = self.client.microphones # Uncomment if client.microphones = app streams
                pass

        if not app_mic_streams:
            logger.info("MicroPhoneSubMenu: No applications found using microphone.")
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
            logger.info(f"MicroPhoneSubMenu: Found {len(app_mic_streams)} app mic streams.")
            for app_stream in app_mic_streams:
                if not app_stream:
                    logger.warning("MicroPhoneSubMenu: Encountered a None stream in app_mic_streams list.")
                    continue

                row = Gtk.ListBoxRow(activatable=False, selectable=False)
                row.get_style_context().add_class("menu-item")

                item_box = Box(name="list-box-row", orientation="v", spacing=8, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)

                name_box = Box(orientation="h", spacing=10, hexpand=True)

                stream_icon_name = getattr(app_stream, "icon_name", None) or icons.get("audio", {}).get("mic", {}).get(
                    "medium", "audio-input-microphone-symbolic"
                )
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

                # Pass the specific app_stream to this MicrophoneSlider instance
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
        logger.debug("MicroPhoneSubMenu: Application microphone list update complete.")
        return GLib.SOURCE_REMOVE

    def _disconnect_signal(self, obj, sid):
        if obj and sid is not None and hasattr(obj, "handler_is_connected") and obj.handler_is_connected(sid):
            try:
                obj.disconnect(sid)
            except Exception as e:
                logger.warning(f"MicroPhoneSubMenu: Error disconnecting signal (ID: {sid}): {e}")

            return True
        return False

    def _on_destroy(self, *args):
        logger.info("MicroPhoneSubMenu: Destroying and disconnecting signals.")
        if self.client:
            self._disconnect_signal(self.client, self._client_recorders_changed_sid)
            self._disconnect_signal(self.client, self._client_changed_sid)
        self._client_recorders_changed_sid = None
        self._client_changed_sid = None
        # Child widgets (like MicrophoneSlider instances in the list) will be destroyed by GTK
        # and their own _on_destroy methods will handle their specific signal disconnections.
        logger.info("MicroPhoneSubMenu: Destruction complete.")
