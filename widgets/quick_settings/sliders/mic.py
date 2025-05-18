import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
from loguru import logger  # Optional: for logging

from fabric.widgets.box import Box
from shared import SettingSlider
from shared.widget_container import HoverButton

from services import audio_service
from utils.icons import icons
from utils.widget_utils import text_icon


class MicrophoneSlider(SettingSlider):
    """
    A widget to display a scale for microphone settings.
    Can control the default system microphone or a specific application audio stream.
    """

    def __init__(self, audio_stream=None, show_chevron=True):
        logger.debug(f"MicrophoneSlider: Initializing. audio_stream type: {type(audio_stream)}, show_chevron: {show_chevron}")
        self.client = audio_service
        self.audio_stream = audio_stream  # For app-specific mic input streams
        self.pixel_size = 16

        # Signal handler IDs
        self._client_mic_changed_sid = None  # For default system microphone changes
        self._stream_changed_sid = None  # For changes on a specific app_stream
        self._client_changed_init_sid = None  # For initial 'changed' from client for default mic

        # Flag to indicate if this instance controls the default device mic
        self._is_default_device_controller = audio_stream is None

        super().__init__(
            icon_name=icons.get("audio", {}).get("mic", {}).get("medium", "audio-input-microphone-symbolic"),
            start_value=0,
            min_value=0,
            max_value=100,
            pixel_size=self.pixel_size,
        )
        logger.debug(f"MicrophoneSlider: super().__init__() done. self.scale: {self.scale}")

        self.chevron_btn = None
        self.chevron_icon = None
        if show_chevron:  # Typically only for the main QS mic slider
            self.chevron_icon = text_icon(icon="", props={"style": "font-size:12px;"})
            self.chevron_btn = HoverButton(child=Box(children=(self.chevron_icon,)))
            self.chevron_btn.connect("clicked", self.on_chevron_click)
            self.pack_end(self.chevron_btn, False, False, 0)
            logger.debug("MicrophoneSlider: Chevron button created and added.")

        if self._is_default_device_controller:
            logger.debug("MicrophoneSlider: Controlling default system microphone.")
            if self.client:
                if self.client.microphone:  # Default mic instance
                    logger.debug("MicrophoneSlider: Default microphone available on init, initializing.")
                    self._initialize_with_device_stream(self.client.microphone)
                self._client_mic_changed_sid = self.client.connect("microphone-changed", self._on_device_mic_changed)
                self._client_changed_init_sid = self.client.connect("changed", self._init_default_mic_cb)
            else:
                logger.warning("MicrophoneSlider: Audio service client not available for default mic.")
        else:  # Controls a specific app stream (audio_stream is provided)
            logger.debug(f"MicrophoneSlider: Specific audio_stream provided: {self.audio_stream}")
            if self.audio_stream and hasattr(self.audio_stream, "connect"):
                self._stream_changed_sid = self.audio_stream.connect("changed", self.update_state_idle)
            else:
                logger.warning(f"MicrophoneSlider: Provided app audio_stream is invalid or non-connectable: {self.audio_stream}")
            self.update_state_idle()  # Initial update for the app stream

        if self.scale:
            self.scale.connect("change-value", self.on_scale_move)
            logger.debug("MicrophoneSlider: Connected 'change-value' to self.scale.")
        else:
            logger.error("MicrophoneSlider: self.scale is None after super init.")

        if self.icon_button:
            self.icon_button.connect("clicked", self.on_mute_click)
            logger.debug("MicrophoneSlider: Connected 'clicked' to self.icon_button.")
        else:
            logger.error("MicrophoneSlider: self.icon_button is None after super init.")

        self.connect("destroy", self._on_destroy)
        logger.debug("MicrophoneSlider: Initialization complete.")

    def _init_default_mic_cb(self, _client=None, _pspec_or_stream=None):
        logger.debug("MicrophoneSlider: _init_default_mic_cb triggered.")
        if not self._is_default_device_controller or self.audio_stream:  # If it's now handling an app stream or already init
            logger.debug("MicrophoneSlider: Not default controller or already init, disconnecting init cb.")
            self._disconnect_signal(self.client, self._client_changed_init_sid)
            self._client_changed_init_sid = None
            return GLib.SOURCE_REMOVE

        if self.client and self.client.microphone:
            logger.debug("MicrophoneSlider: Default microphone now available via 'changed' signal, initializing.")
            self._initialize_with_device_stream(self.client.microphone)
            self._disconnect_signal(self.client, self._client_changed_init_sid)
            self._client_changed_init_sid = None
            if not self._client_mic_changed_sid and self.client:
                self._client_mic_changed_sid = self.client.connect("microphone-changed", self._on_device_mic_changed)
        else:
            logger.debug("MicrophoneSlider: Default microphone still not available after 'changed' signal.")
        return GLib.SOURCE_REMOVE

    def _initialize_with_device_stream(self, stream_obj):
        # Only called when _is_default_device_controller is True
        logger.debug(f"MicrophoneSlider: Initializing with device microphone stream: {stream_obj}")
        if self.audio_stream == stream_obj and self._stream_changed_sid is not None:
            logger.debug("MicrophoneSlider: Device mic stream is the same and already connected, forcing update.")
            self.update_state_idle()
            return

        self._disconnect_signal(self.audio_stream, self._stream_changed_sid)  # Disconnect from old device stream
        self.audio_stream = stream_obj  # Now self.audio_stream points to the default device mic

        if self.audio_stream and hasattr(self.audio_stream, "connect"):
            self._stream_changed_sid = self.audio_stream.connect("changed", self.update_state_idle)
            logger.debug(f"MicrophoneSlider: Connected to 'changed' signal of new device mic stream: {self.audio_stream}")
        elif self.audio_stream:
            logger.warning(f"MicrophoneSlider: New device mic stream {self.audio_stream} is not connectable.")

        self.update_state_idle()

    def _on_device_mic_changed(self, _client=None, _new_stream_ref_or_pspec=None):
        # Called when audio_service.microphone (the default system mic instance) itself changes
        logger.debug("MicrophoneSlider: _on_device_mic_changed (default mic instance changed).")
        if self._is_default_device_controller:
            if self.client and self.client.microphone:
                new_mic = self.client.microphone
                logger.debug(f"MicrophoneSlider: New default mic instance: {new_mic}")
                self._initialize_with_device_stream(new_mic)
            else:
                logger.warning("MicrophoneSlider: Default microphone became None.")
                self._initialize_with_device_stream(None)

    def _get_icon_name(self):
        # stream_to_check is either the app-specific stream or the current default system microphone
        stream_to_check = self.audio_stream
        if self._is_default_device_controller:  # Always use the current default system mic if this slider is for it
            stream_to_check = self.client.microphone if self.client and self.client.microphone else None

        if not stream_to_check or not hasattr(stream_to_check, "muted") or not hasattr(stream_to_check, "volume"):
            return icons.get("audio", {}).get("mic", {}).get("disabled", "audio-input-microphone-muted-symbolic")

        if stream_to_check.muted:
            return icons.get("audio", {}).get("mic", {}).get("muted", "audio-input-microphone-muted-symbolic")

        # Could add logic for volume levels if mic icons for different levels exist
        return icons.get("audio", {}).get("mic", {}).get("medium", "audio-input-microphone-symbolic")

    def update_state_idle(self, *args):
        GLib.idle_add(self.update_state, priority=GLib.PRIORITY_DEFAULT_IDLE)
        return GLib.SOURCE_REMOVE

    def update_state(self, *args):
        # logger.debug(f"MicrophoneSlider: update_state called. Is default controller: {self._is_default_device_controller}, stream: {self.audio_stream}")
        # MODIFIED LINE HERE
        if not self.scale or not isinstance(self.scale, Gtk.Widget) or not self.scale.get_realized():
            logger.warning(f"MicrophoneSlider ({self.get_name()}): Scale not a valid Gtk.Widget or not realized. Skipping update.")
            return GLib.SOURCE_REMOVE

        adjustment = self.scale.get_adjustment()
        if not adjustment or not isinstance(adjustment, Gtk.Adjustment):  # Also check adjustment type
            logger.warning(f"MicrophoneSlider ({self.get_name()}): Adjustment not valid. Skipping update.")
            return GLib.SOURCE_REMOVE

        stream_to_update_from = self.audio_stream
        if self._is_default_device_controller:
            stream_to_update_from = self.client.microphone if self.client and self.client.microphone else None

        if not stream_to_update_from or not hasattr(stream_to_update_from, "volume") or not hasattr(stream_to_update_from, "muted"):
            logger.debug(f"MicrophoneSlider: Stream {stream_to_update_from} is invalid or lacks properties for update.")
            self.scale.set_sensitive(False)
            try:
                val_to_set = adjustment.get_lower()
                if not (adjustment.get_lower() <= val_to_set <= adjustment.get_upper()):
                    val_to_set = 0
                self.scale.set_value(val_to_set)
            except Exception as e:
                logger.error(f"MicrophoneSlider: Error setting scale to lower on invalid stream: {e}")
            self.scale.set_tooltip_text("Microphone not available")
            if self.icon and hasattr(self.icon, "set_from_icon_name"):
                self.icon.set_from_icon_name(self._get_icon_name(), self.pixel_size)
            return GLib.SOURCE_REMOVE

        try:
            volume = stream_to_update_from.volume
            muted = stream_to_update_from.muted

            self.scale.set_sensitive(not muted)
            current_scale_val = self.scale.get_value()
            clamped_volume = max(adjustment.get_lower(), min(float(volume), adjustment.get_upper()))

            if abs(current_scale_val - clamped_volume) > 0.001:
                self.scale.set_value(clamped_volume)

            self.scale.set_tooltip_text(f"{round(clamped_volume)}%")
            if self.icon and hasattr(self.icon, "set_from_icon_name"):
                self.icon.set_from_icon_name(self._get_icon_name(), self.pixel_size)
        except Exception as e:
            logger.error(f"MicrophoneSlider ({self.get_name()}): Error during update_state: {e}", exc_info=True)
        return GLib.SOURCE_REMOVE

    def on_scale_move(self, scale_widget, scroll_type, value):
        target_stream = self.audio_stream
        if self._is_default_device_controller:
            target_stream = self.client.microphone if self.client and self.client.microphone else None

        if target_stream and hasattr(target_stream, "volume"):
            try:
                # logger.debug(f"MicrophoneSlider: Scale moved to {value}, setting volume on stream {target_stream.name if hasattr(target_stream,'name') else 'N/A'}")
                target_stream.volume = float(value)
            except Exception as e:
                logger.error(f"MicrophoneSlider: Error setting volume: {e}", exc_info=True)
        return False

    def on_chevron_click(self, button_widget):  # Chevron click
        parent = self.get_parent()
        while parent and not hasattr(parent, "mic_submenu"):
            parent = parent.get_parent()

        if (
            parent
            and hasattr(parent, "mic_submenu")
            and hasattr(parent.mic_submenu, "toggle_reveal")
            and self.chevron_icon
            and hasattr(self.chevron_icon, "set_label")
        ):
            try:
                is_visible = parent.mic_submenu.toggle_reveal()
                self.chevron_icon.set_label("" if is_visible else "")
            except Exception as e:
                logger.error(f"MicrophoneSlider: Error toggling mic_submenu: {e}", exc_info=True)
        elif not (self.chevron_icon and hasattr(self.chevron_icon, "set_label")):
            logger.warning("MicrophoneSlider: Chevron icon not available for label update.")
        else:
            logger.warning("MicrophoneSlider: Could not find mic_submenu or toggle_reveal method on parent.")

    def on_mute_click(self, button_widget):  # Icon click
        target_stream = self.audio_stream
        if self._is_default_device_controller:
            target_stream = self.client.microphone if self.client and self.client.microphone else None

        if target_stream and hasattr(target_stream, "muted"):
            try:
                new_mute_state = not target_stream.muted
                logger.debug(
                    f"MicrophoneSlider: Toggling mute for stream {target_stream.name if hasattr(target_stream, 'name') else 'N/A'} to {new_mute_state}"
                )
                target_stream.muted = new_mute_state
                # self.update_state_idle() # Refresh UI
            except Exception as e:
                logger.error(f"MicrophoneSlider: Error toggling mute: {e}", exc_info=True)

    def _disconnect_signal(self, obj, sid):
        if obj and sid is not None and hasattr(obj, "handler_is_connected") and obj.handler_is_connected(sid):
            try:
                obj.disconnect(sid)
                # logger.debug(f"MicrophoneSlider: Disconnected signal ID {sid} from {obj}")
                return True
            except Exception as e:
                logger.warning(f"MicrophoneSlider: Error disconnecting signal ID {sid} from {obj}: {e}")
        return False

    def _on_destroy(self, *args):
        logger.debug(f"MicrophoneSlider ({self.get_name()}): Destroying. Is default: {self._is_default_device_controller}")
        if self.client:
            self._disconnect_signal(self.client, self._client_mic_changed_sid)
            self._disconnect_signal(self.client, self._client_changed_init_sid)

        self._disconnect_signal(self.audio_stream, self._stream_changed_sid)

        self._client_mic_changed_sid = None
        self._client_changed_init_sid = None
        self._stream_changed_sid = None
        self.audio_stream = None
        logger.debug(f"MicrophoneSlider ({self.get_name()}): Destruction complete.")
