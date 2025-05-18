import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
from loguru import logger  # Optional: for logging. Ensure loguru is installed or remove.

from fabric.widgets.box import Box

# Assuming SettingSlider is in 'shared' and HoverButton in 'shared.widget_container'
# Adjust paths if they are different in your project structure.
from shared import SettingSlider  # Base class for sliders
from shared.widget_container import HoverButton  # For the icon button functionality

from services import audio_service  # Your audio service
from utils.icons import icons  # Your icon dictionary
from utils.widget_utils import text_icon  # For the chevron icon


class AudioSlider(SettingSlider):
    """
    A widget to display a scale for audio settings for speakers.
    Can control the default system speaker or a specific application audio stream.
    """

    def __init__(self, audio_stream=None, show_chevron=True):
        logger.debug(f"AudioSlider: Initializing. audio_stream type: {type(audio_stream)}, show_chevron: {show_chevron}")
        self.client = audio_service
        self.audio_stream = audio_stream  # For app-specific streams, None for default speaker
        self.pixel_size = 16

        # Signal handler IDs for cleanup
        self._client_speaker_changed_sid = None
        self._stream_changed_sid = None
        self._client_changed_init_sid = None  # For initial 'changed' signal from client

        # Initialize SettingSlider (base class)
        # This creates self.scale, self.icon, self.icon_button
        super().__init__(
            icon_name=icons.get("audio", {}).get("volume", {}).get("high", "audio-volume-high-symbolic"),
            start_value=0,  # Initial value, will be updated by update_state
            min_value=0,  # Default for Gtk.Scale
            max_value=100,  # Default for Gtk.Scale (0-100 range for volume)
            pixel_size=self.pixel_size,
        )
        logger.debug(f"AudioSlider: super().__init__() done. self.scale: {self.scale}")

        self.chevron_btn = None
        self.chevron_icon = None
        if show_chevron:
            self.chevron_icon = text_icon(icon="", props={"style": "font-size:12px;"})
            self.chevron_btn = HoverButton(child=Box(children=(self.chevron_icon,)))  # Ensure Box is imported
            self.chevron_btn.connect("clicked", self.on_chevron_click)
            self.pack_end(self.chevron_btn, False, False, 0)  # Add chevron to this Box (AudioSlider is a Box)
            logger.debug("AudioSlider: Chevron button created and added.")

        if not self.audio_stream:  # Controlling default system speaker
            logger.debug("AudioSlider: No specific audio_stream provided, controlling default speaker.")
            if self.client:
                if self.client.speaker:
                    logger.debug("AudioSlider: Default speaker available on init, initializing with it.")
                    self._initialize_with_device_stream(self.client.speaker)
                # Connect to speaker-changed for future changes to the default speaker
                self._client_speaker_changed_sid = self.client.connect("speaker-changed", self._on_device_stream_changed)
                # Connect to general 'changed' signal if speaker not immediately available or to catch other updates
                self._client_changed_init_sid = self.client.connect("changed", self._init_default_speaker_cb)
            else:
                logger.warning("AudioSlider: Audio service client not available on init for default speaker.")
        else:  # audio_stream is provided (app-specific)
            logger.debug(f"AudioSlider: Specific audio_stream provided: {self.audio_stream}")
            if self.audio_stream and hasattr(self.audio_stream, "connect"):
                self._stream_changed_sid = self.audio_stream.connect("changed", self.update_state_idle)
            else:
                logger.warning(f"AudioSlider: Provided audio_stream is invalid or non-connectable: {self.audio_stream}")
            self.update_state_idle()  # Initial update for the provided stream

        if self.scale:
            self.scale.connect("change-value", self.on_scale_move)
            logger.debug("AudioSlider: Connected 'change-value' to self.scale.")
        else:
            logger.error("AudioSlider: self.scale is None after super init. This should not happen.")

        if self.icon_button:  # From SettingSlider
            self.icon_button.connect("clicked", self.on_mute_click)
            logger.debug("AudioSlider: Connected 'clicked' to self.icon_button.")
        else:
            logger.error("AudioSlider: self.icon_button is None after super init.")

        self.connect("destroy", self._on_destroy)
        logger.debug("AudioSlider: Initialization complete.")

    def _init_default_speaker_cb(self, _client=None, _pspec_or_stream=None):
        # Callback for audio_service 'changed' signal, primarily for initial setup if speaker wasn't ready.
        logger.debug("AudioSlider: _init_default_speaker_cb triggered.")
        if self.audio_stream:  # Already initialized (e.g. by specific stream or earlier direct init)
            logger.debug("AudioSlider: Default speaker already initialized or stream provided, disconnecting init callback.")
            self._disconnect_signal(self.client, self._client_changed_init_sid)
            self._client_changed_init_sid = None
            return GLib.SOURCE_REMOVE

        if self.client and self.client.speaker:
            logger.debug("AudioSlider: Default speaker now available via 'changed' signal, initializing.")
            self._initialize_with_device_stream(self.client.speaker)
            self._disconnect_signal(self.client, self._client_changed_init_sid)  # No longer need this generic 'changed'
            self._client_changed_init_sid = None
            # Ensure speaker-changed is connected if it wasn't (e.g. if client was None initially)
            if not self._client_speaker_changed_sid and self.client:
                self._client_speaker_changed_sid = self.client.connect("speaker-changed", self._on_device_stream_changed)
        else:
            logger.debug("AudioSlider: Default speaker still not available after 'changed' signal.")
        return GLib.SOURCE_REMOVE  # Try once

    def _initialize_with_device_stream(self, stream_obj):
        logger.debug(f"AudioSlider: Initializing with device stream: {stream_obj}")
        if self.audio_stream == stream_obj and self._stream_changed_sid is not None:
            logger.debug("AudioSlider: Stream is the same and already connected, forcing update.")
            self.update_state_idle()  # Update state even if stream object is same, properties might have changed
            return

        self._disconnect_signal(self.audio_stream, self._stream_changed_sid)  # Disconnect from old stream if any
        self.audio_stream = stream_obj  # This is now the stream we are controlling (the default speaker)

        if self.audio_stream and hasattr(self.audio_stream, "connect"):
            self._stream_changed_sid = self.audio_stream.connect("changed", self.update_state_idle)
            logger.debug(f"AudioSlider: Connected to 'changed' signal of new stream: {self.audio_stream}")
        elif self.audio_stream:
            logger.warning(f"AudioSlider: New stream {self.audio_stream} is not connectable.")

        self.update_state_idle()  # Update UI with the new stream's state

    def _on_device_stream_changed(self, _client=None, _new_stream_ref_or_pspec=None):
        # Called when audio_service.speaker (the default system speaker instance) itself changes
        logger.debug("AudioSlider: _on_device_stream_changed (default speaker instance changed).")
        if self.client and self.client.speaker:
            new_speaker = self.client.speaker
            logger.debug(f"AudioSlider: New default speaker instance: {new_speaker}")
            self._initialize_with_device_stream(new_speaker)
        else:
            logger.warning("AudioSlider: Default speaker became None.")
            self._initialize_with_device_stream(None)  # Handle case where speaker is removed

    def _get_icon_name(self):
        # Determine icon based on the current audio_stream's state
        stream_to_check = self.audio_stream

        if not stream_to_check or not hasattr(stream_to_check, "muted") or not hasattr(stream_to_check, "volume"):
            return icons.get("audio", {}).get("volume", {}).get("disabled", "audio-volume-muted-symbolic")

        if stream_to_check.muted:
            return icons.get("audio", {}).get("volume", {}).get("muted", "audio-volume-muted-symbolic")

        volume = stream_to_check.volume
        if volume == 0:
            return icons.get("audio", {}).get("volume", {}).get("none", "audio-volume-muted-symbolic")  # Or specific zero icon
        elif volume < 34:
            return icons.get("audio", {}).get("volume", {}).get("low", "audio-volume-low-symbolic")
        elif volume < 67:
            return icons.get("audio", {}).get("volume", {}).get("medium", "audio-volume-medium-symbolic")
        else:
            return icons.get("audio", {}).get("volume", {}).get("high", "audio-volume-high-symbolic")

    def update_state_idle(self, *args):
        GLib.idle_add(self.update_state, priority=GLib.PRIORITY_DEFAULT_IDLE)
        return GLib.SOURCE_REMOVE  # If called from signal that expects it

    def update_state(self, *args):
        # logger.debug(f"AudioSlider: update_state called for stream: {self.audio_stream}")
        # MODIFIED LINE HERE
        if not self.scale or not isinstance(self.scale, Gtk.Widget) or not self.scale.get_realized():
            logger.warning(f"AudioSlider ({self.get_name()}): Scale not a valid Gtk.Widget or not realized. Skipping update.")
            return GLib.SOURCE_REMOVE

        adjustment = self.scale.get_adjustment()
        if not adjustment or not isinstance(adjustment, Gtk.Adjustment):  # Also check adjustment type
            logger.warning(f"AudioSlider ({self.get_name()}): Gtk.Adjustment not valid. Skipping update.")
            return GLib.SOURCE_REMOVE

        stream_to_update_from = self.audio_stream

        if not stream_to_update_from or not hasattr(stream_to_update_from, "volume") or not hasattr(stream_to_update_from, "muted"):
            logger.debug(f"AudioSlider: Stream {stream_to_update_from} is invalid or lacks properties.")
            self.scale.set_sensitive(False)
            try:
                val_to_set = adjustment.get_lower()
                if not (adjustment.get_lower() <= val_to_set <= adjustment.get_upper()):
                    val_to_set = 0
                self.scale.set_value(val_to_set)
            except Exception as e:
                logger.error(f"AudioSlider: Error setting scale to lower on invalid stream: {e}")
            self.scale.set_tooltip_text("Audio device not available")
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
            logger.error(f"AudioSlider ({self.get_name()}): Error during update_state: {e}", exc_info=True)
        return GLib.SOURCE_REMOVE

    def on_scale_move(self, scale_widget, scroll_type, value):
        # scroll_type and value are Gtk.Scale specific arguments for "change-value"
        target_stream = self.audio_stream

        if target_stream and hasattr(target_stream, "volume"):
            try:
                # audio_stream.volume expects value in same range as scale (e.g. 0-100)
                # logger.debug(f"AudioSlider: Scale moved to {value}, setting volume on stream {target_stream.name if hasattr(target_stream,'name') else 'N/A'}")
                target_stream.volume = float(value)  # Ensure it's a float if service expects it
            except Exception as e:
                logger.error(f"AudioSlider: Error setting volume on stream: {e}", exc_info=True)
        return False  # Let Gtk.Scale handle its event propagation unless True is returned

    def on_chevron_click(self, button_widget):  # Chevron click
        parent = self.get_parent()
        # Traverse up to QuickSettingsMenu which should have 'audio_submenu'
        while parent and not hasattr(parent, "audio_submenu"):
            parent = parent.get_parent()

        if (
            parent
            and hasattr(parent, "audio_submenu")
            and hasattr(parent.audio_submenu, "toggle_reveal")
            and self.chevron_icon
            and hasattr(self.chevron_icon, "set_label")
        ):
            try:
                is_visible = parent.audio_submenu.toggle_reveal()
                self.chevron_icon.set_label("" if is_visible else "")
            except Exception as e:
                logger.error(f"AudioSlider: Error toggling audio_submenu: {e}", exc_info=True)
        elif not (self.chevron_icon and hasattr(self.chevron_icon, "set_label")):
            logger.warning("AudioSlider: Chevron icon not available for label update.")
        else:
            logger.warning("AudioSlider: Could not find audio_submenu or toggle_reveal method on parent.")

    def on_mute_click(self, button_widget):  # Icon click
        target_stream = self.audio_stream
        if target_stream and hasattr(target_stream, "muted"):
            try:
                new_mute_state = not target_stream.muted
                logger.debug(
                    f"AudioSlider: Toggling mute for stream {target_stream.name if hasattr(target_stream, 'name') else 'N/A'} to {new_mute_state}"
                )
                target_stream.muted = new_mute_state
                # self.update_state_idle() # Refresh UI based on new mute state
            except Exception as e:
                logger.error(f"AudioSlider: Error toggling mute on stream: {e}", exc_info=True)

    def _disconnect_signal(self, obj, sid):
        if obj and sid is not None and hasattr(obj, "handler_is_connected") and obj.handler_is_connected(sid):
            try:
                obj.disconnect(sid)
                # logger.debug(f"AudioSlider: Disconnected signal ID {sid} from {obj}")
                return True
            except Exception as e:
                logger.warning(f"AudioSlider: Error disconnecting signal ID {sid} from {obj}: {e}")
        return False

    def _on_destroy(self, *args):
        logger.debug(f"AudioSlider ({self.get_name()}): Destroying, disconnecting signals.")
        if self.client:
            self._disconnect_signal(self.client, self._client_speaker_changed_sid)
            self._disconnect_signal(self.client, self._client_changed_init_sid)

        self._disconnect_signal(self.audio_stream, self._stream_changed_sid)  # Disconnects from current stream

        self._client_speaker_changed_sid = None
        self._client_changed_init_sid = None
        self._stream_changed_sid = None
        self.audio_stream = None  # Clear reference
        logger.debug(f"AudioSlider ({self.get_name()}): Destruction complete.")
