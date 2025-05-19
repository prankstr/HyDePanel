import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
from loguru import logger
import contextlib

from fabric.widgets.box import Box
from shared import SettingSlider
from shared.widget_container import HoverButton

from services import audio_service
from utils.icons import icons
from utils.widget_utils import text_icon


class MicrophoneSlider(SettingSlider):
    def __init__(self, audio_stream=None, show_chevron=True):
        self.client = audio_service
        self.audio_stream = audio_stream
        self.pixel_size = 16

        self._client_mic_changed_sid = None
        self._stream_changed_sid = None
        self._client_changed_init_sid = None
        self._is_default_device_controller = audio_stream is None

        super().__init__(
            icon_name=icons.get("audio", {}).get("mic", {}).get("medium", "audio-input-microphone-symbolic"),
            start_value=0,
            min_value=0,
            max_value=100,
            pixel_size=self.pixel_size,
        )

        self.chevron_btn = None
        self.chevron_icon = None
        if show_chevron:
            self.chevron_icon = text_icon(icon="", props={"style": "font-size:12px;"})
            self.chevron_btn = HoverButton(child=Box(children=(self.chevron_icon,)))
            self.chevron_btn.connect("clicked", self.on_chevron_click)
            self.pack_end(self.chevron_btn, False, False, 0)

        if self._is_default_device_controller:
            if self.client:
                if self.client.microphone:
                    self._initialize_with_device_stream(self.client.microphone)
                self._client_mic_changed_sid = self.client.connect("microphone-changed", self._on_device_mic_changed)
                self._client_changed_init_sid = self.client.connect("changed", self._init_default_mic_cb)
            else:
                logger.warning("MicrophoneSlider: Audio service client not available for default mic.")
        else:
            if self.audio_stream and hasattr(self.audio_stream, "connect"):
                self._stream_changed_sid = self.audio_stream.connect("changed", self.update_state_idle)
            else:
                logger.warning(f"MicrophoneSlider: Provided app audio_stream is invalid or non-connectable: {self.audio_stream}")
            self.update_state_idle()

        if self.scale:
            self.scale.connect("change-value", self.on_scale_move)
        else:
            logger.error("MicrophoneSlider: self.scale is None after super init.")

        if self.icon_button:
            self.icon_button.connect("clicked", self.on_mute_click)
        else:
            logger.error("MicrophoneSlider: self.icon_button is None after super init.")

        self.connect("destroy", self._on_destroy)

    def _init_default_mic_cb(self, _client=None, _pspec_or_stream=None):
        if not self._is_default_device_controller or self.audio_stream:
            self._disconnect_signal(self.client, self._client_changed_init_sid)
            self._client_changed_init_sid = None
            return GLib.SOURCE_REMOVE

        if self.client and self.client.microphone:
            self._initialize_with_device_stream(self.client.microphone)
            self._disconnect_signal(self.client, self._client_changed_init_sid)
            self._client_changed_init_sid = None
            if not self._client_mic_changed_sid and self.client:
                self._client_mic_changed_sid = self.client.connect("microphone-changed", self._on_device_mic_changed)
        return GLib.SOURCE_REMOVE

    def _initialize_with_device_stream(self, stream_obj):
        if self.audio_stream == stream_obj and self._stream_changed_sid is not None:
            self.update_state_idle()
            return

        self._disconnect_signal(self.audio_stream, self._stream_changed_sid)
        self.audio_stream = stream_obj

        if self.audio_stream and hasattr(self.audio_stream, "connect"):
            self._stream_changed_sid = self.audio_stream.connect("changed", self.update_state_idle)
        elif self.audio_stream:
            logger.warning(f"MicrophoneSlider: New device mic stream {self.audio_stream} is not connectable.")

        self.update_state_idle()

    def _on_device_mic_changed(self, _client=None, _new_stream_ref_or_pspec=None):
        if self._is_default_device_controller:
            if self.client and self.client.microphone:
                new_mic = self.client.microphone
                self._initialize_with_device_stream(new_mic)
            else:
                logger.warning("MicrophoneSlider: Default microphone became None.")
                self._initialize_with_device_stream(None)

    def _get_icon_name(self):
        stream_to_check = self.audio_stream
        if self._is_default_device_controller:
            stream_to_check = self.client.microphone if self.client and self.client.microphone else None

        if not stream_to_check or not hasattr(stream_to_check, "muted") or not hasattr(stream_to_check, "volume"):
            return str(icons.get("audio", {}).get("mic", {}).get("disabled", "audio-input-microphone-muted-symbolic"))

        if stream_to_check.muted:
            return str(icons.get("audio", {}).get("mic", {}).get("muted", "audio-input-microphone-muted-symbolic"))

        return str(icons.get("audio", {}).get("mic", {}).get("medium", "audio-input-microphone-symbolic"))

    def update_state_idle(self, *args):
        GLib.idle_add(self.update_state, priority=GLib.PRIORITY_DEFAULT_IDLE)
        return GLib.SOURCE_REMOVE

    def update_state(self, *args):
        if not self.scale or not isinstance(self.scale, Gtk.Widget) or not self.scale.get_realized():
            logger.debug(f"MicrophoneSlider ({self.get_name()}): Scale not valid/realized. Skipping update.")
            return GLib.SOURCE_REMOVE

        adjustment = self.scale.get_adjustment()
        if not adjustment or not isinstance(adjustment, Gtk.Adjustment):
            logger.debug(f"MicrophoneSlider ({self.get_name()}): Adjustment not valid. Skipping update.")
            return GLib.SOURCE_REMOVE

        stream_to_update_from = self.audio_stream
        if self._is_default_device_controller:
            stream_to_update_from = self.client.microphone if self.client and self.client.microphone else None

        if not stream_to_update_from or not hasattr(stream_to_update_from, "volume") or not hasattr(stream_to_update_from, "muted"):
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
            volume_raw = stream_to_update_from.volume
            muted = stream_to_update_from.muted
            volume = 0.0
            with contextlib.suppress(ValueError, TypeError):
                volume = float(volume_raw)

            self.scale.set_sensitive(not muted)
            current_scale_val = self.scale.get_value()
            clamped_volume = max(adjustment.get_lower(), min(volume, adjustment.get_upper()))

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
                target_stream.volume = float(value)
            except Exception as e:
                logger.error(f"MicrophoneSlider: Error setting volume: {e}", exc_info=True)
        return False

    def on_chevron_click(self, button_widget):
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

    def on_mute_click(self, button_widget):
        target_stream = self.audio_stream
        if self._is_default_device_controller:
            target_stream = self.client.microphone if self.client and self.client.microphone else None

        if target_stream and hasattr(target_stream, "muted"):
            try:
                new_mute_state = not target_stream.muted
                target_stream.muted = new_mute_state
            except Exception as e:
                logger.error(f"MicrophoneSlider: Error toggling mute: {e}", exc_info=True)

    def _disconnect_signal(self, obj, sid):
        if obj and sid is not None and hasattr(obj, "handler_is_connected") and obj.handler_is_connected(sid):
            with contextlib.suppress(Exception):
                obj.disconnect(sid)
                return True
        return False

    def _on_destroy(self, *args):
        if self.client:
            self._disconnect_signal(self.client, self._client_mic_changed_sid)
            self._disconnect_signal(self.client, self._client_changed_init_sid)

        self._disconnect_signal(self.audio_stream, self._stream_changed_sid)

        self._client_mic_changed_sid = None
        self._client_changed_init_sid = None
        self._stream_changed_sid = None
        self.audio_stream = None
