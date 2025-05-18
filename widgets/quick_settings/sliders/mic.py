# widgets/quick_settings/sliders/mic.py

from typing import Optional, Any  # Added Optional, Any
from fabric.widgets.box import Box
from gi.repository import Gtk, GLib
from loguru import logger

from services import audio_service
from shared import SettingSlider  # Assuming SettingSlider is Gtk.Widget based and has self.scale
from shared.widget_container import HoverButton
from utils.icons import icons
from utils.widget_utils import text_icon


class MicrophoneSlider(SettingSlider):
    """A widget to display a scale for audio settings."""

    def __init__(self, audio_stream: Optional[Any] = None, show_chevron: bool = True):
        # Use a more descriptive name if audio_stream is None initially
        stream_name_for_log = (
            getattr(audio_stream, "name", "Default Device Mic (pending init)") if audio_stream else "Default Device Mic (pending init)"
        )
        logger.info(f"INIT: {self.__class__.__name__} for stream: {stream_name_for_log}")

        self.client = audio_service
        self.audio_stream = audio_stream
        self._stream_changed_handler_id: Optional[int] = None
        self._client_mic_changed_handler_id: Optional[int] = None
        self._client_changed_for_init_handler_id: Optional[int] = None
        self._realize_handler_id: Optional[int] = None  # For initial update_state call

        self.pixel_size = 16

        initial_icon_name = str(icons.get("audio", {}).get("mic", {}).get("medium", "audio-input-microphone-symbolic"))
        initial_volume = 0
        if self.audio_stream and hasattr(self.audio_stream, "muted") and hasattr(self.audio_stream, "volume"):
            initial_icon_name = str(
                icons.get("audio", {}).get("mic", {}).get("muted" if self.audio_stream.muted else "high", initial_icon_name)
            )
            initial_volume = getattr(self.audio_stream, "volume", 0)

        super().__init__(
            icon_name=initial_icon_name,
            start_value=initial_volume,
            pixel_size=self.pixel_size,
        )

        if show_chevron:
            self.chevron_icon = text_icon(icon="", props={"style": "font-size:12px;"})
            self.chevron_btn = HoverButton(child=Box(children=(self.chevron_icon,)))
            self.chevron_btn.connect("clicked", self.on_button_click)
            current_children = list(getattr(self, "children", []))  # Ensure self.children exists from superclass
            current_children.append(self.chevron_btn)
            self.children = tuple(current_children)

        if not self.audio_stream:
            logger.debug(f"{self.__class__.__name__}: No specific audio_stream, setting up for default device microphone.")
            self._setup_default_device_mic_logic()
        else:
            logger.debug(f"{self.__class__.__name__}: Initializing for specific stream: {getattr(self.audio_stream, 'name', 'N/A')}")
            if hasattr(self.audio_stream, "connect"):
                self._stream_changed_handler_id = self.audio_stream.connect("changed", self.update_state)

        # Schedule first update after the widget is realized, or on idle if already realized
        if not self.get_realized():
            self._realize_handler_id = self.connect_after("realize", self._on_slider_realized)
        else:
            GLib.idle_add(self.update_state, priority=GLib.PRIORITY_DEFAULT_IDLE)

        if hasattr(self, "scale") and self.scale:
            self.scale.connect("change-value", self.on_scale_move)
        if hasattr(self, "icon_button") and self.icon_button:
            self.icon_button.connect("clicked", self.on_mute_click)

    def _on_slider_realized(self, widget: Gtk.Widget) -> None:
        logger.debug(f"{self.__class__.__name__} for '{getattr(self.audio_stream, 'name', 'N/A')}': Realized. Scheduling update_state.")
        GLib.idle_add(self.update_state, priority=GLib.PRIORITY_DEFAULT_IDLE)
        if self._realize_handler_id:  # Disconnect after first call
            self.disconnect(self._realize_handler_id)
            self._realize_handler_id = None

    def _setup_default_device_mic_logic(self):
        # This internal function will be called to set up or re-set up the default mic
        def init_or_reset_default_mic_cb(*args):
            logger.debug(f"{self.__class__.__name__}: init_or_reset_default_mic_cb called.")

            # Disconnect previous specific stream handler if any (e.g., if default mic changed)
            if (
                self.audio_stream
                and self._stream_changed_handler_id
                and hasattr(self.audio_stream, "handler_is_connected")
                and self.audio_stream.handler_is_connected(self._stream_changed_handler_id)
            ):
                self.audio_stream.disconnect(self._stream_changed_handler_id)
            self._stream_changed_handler_id = None

            # Disconnect the initial "changed" handler if it was this one
            if (
                self._client_changed_for_init_handler_id
                and self.client
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_changed_for_init_handler_id)
            ):
                self.client.disconnect(self._client_changed_for_init_handler_id)
            self._client_changed_for_init_handler_id = None

            if self.client and self.client.microphone:
                self.audio_stream = self.client.microphone
                logger.info(f"{self.__class__.__name__}: Now controlling default mic: {getattr(self.audio_stream, 'name', 'N/A')}")
                if self.get_realized():
                    GLib.idle_add(self.update_state, priority=GLib.PRIORITY_DEFAULT_IDLE)  # Update if realized

                if hasattr(self.audio_stream, "connect"):
                    self._stream_changed_handler_id = self.audio_stream.connect("changed", self.update_state)

                # Ensure "microphone-changed" is connected (or reconnected)
                if (
                    self._client_mic_changed_handler_id
                    and self.client
                    and hasattr(self.client, "handler_is_connected")
                    and self.client.handler_is_connected(self._client_mic_changed_handler_id)
                ):
                    pass  # Already connected
                elif self.client and hasattr(self.client, "connect"):
                    if self._client_mic_changed_handler_id:  # Disconnect old if it existed
                        try:
                            self.client.disconnect(self._client_mic_changed_handler_id)
                        except:
                            pass
                    self._client_mic_changed_handler_id = self.client.connect("microphone-changed", init_or_reset_default_mic_cb)
            else:
                logger.warning(f"{self.__class__.__name__}: Client or client.microphone is None during default mic setup.")
                self.audio_stream = None  # Ensure it's None
                if self.get_realized():
                    GLib.idle_add(self.update_state, priority=GLib.PRIORITY_DEFAULT_IDLE)  # Update to show disabled state
            return GLib.SOURCE_REMOVE

        if self.client:
            if self.client.microphone:
                GLib.idle_add(init_or_reset_default_mic_cb)
            else:
                self._client_changed_for_init_handler_id = self.client.connect("changed", init_or_reset_default_mic_cb)
        else:
            logger.error(f"{self.__class__.__name__}: audio_service (self.client) is None.")

    def update_state(self, *args):
        # Visible/Realized check is primary
        if not self.get_realized():  # Check realized first - if not realized, it's definitely not properly visible for updates
            logger.debug(
                f"{self.__class__.__name__} for '{getattr(self.audio_stream, 'name', 'N/A')}': update_state when NOT realized. Skipping."
            )
            return False
        if not self.get_visible():
            logger.debug(
                f"{self.__class__.__name__} for '{getattr(self.audio_stream, 'name', 'N/A')}': update_state when NOT visible. Skipping scale update."
            )
            # Still update icon if it's based on non-visual state like mute
            target_stream_for_icon = self.audio_stream
            if not target_stream_for_icon and self.client and self.client.microphone:
                target_stream_for_icon = self.client.microphone
            if target_stream_for_icon and hasattr(self, "icon") and self.icon:
                self.icon.set_from_icon_name(str(self._get_icon_name(target_stream_for_icon)), self.pixel_size)
            return False

        target_stream = self.audio_stream
        if not target_stream and self.client and self.client.microphone:
            target_stream = self.client.microphone

        if not target_stream:
            logger.warning(f"{self.__class__.__name__}: audio_stream is None in update_state.")
            if hasattr(self, "scale") and self.scale:
                self.scale.set_sensitive(False)
            if hasattr(self, "icon") and self.icon:
                self.icon.set_from_icon_name(
                    str(icons.get("audio", {}).get("mic", {}).get("disabled", "audio-input-microphone-disabled-symbolic")), self.pixel_size
                )
            return False

        if not hasattr(self, "scale") or not self.scale or not isinstance(self.scale, Gtk.Scale):
            logger.error(f"{self.__class__.__name__}: self.scale is not a valid Gtk.Scale widget.")
            return False
        adjustment = self.scale.get_adjustment()
        if not adjustment or not isinstance(adjustment, Gtk.Adjustment):
            logger.error(f"{self.__class__.__name__}: self.scale.get_adjustment() invalid. Adj: {adjustment}")
            return False

        stream_muted = getattr(target_stream, "muted", True)
        stream_volume = getattr(target_stream, "volume", 0)

        self.scale.set_sensitive(not stream_muted)
        try:
            current_adj_val = adjustment.get_value()
            if abs(current_adj_val - float(stream_volume)) > 1e-6:  # Using epsilon
                # logger.debug(f"Slider '{getattr(target_stream,'name','N/A')}': Setting adj value to {float(stream_volume)}") # Can be verbose
                adjustment.set_value(float(stream_volume))
        except Exception as e:
            logger.error(f"Slider: Error setting scale for {getattr(target_stream, 'name', 'N/A')}: {e}", exc_info=True)

        if hasattr(self.scale, "set_tooltip_text"):
            self.scale.set_tooltip_text(f"{round(stream_volume)}%")
        if hasattr(self, "icon") and self.icon:
            self.icon.set_from_icon_name(str(self._get_icon_name(target_stream)), self.pixel_size)
        return False

    def _get_icon_name(self, stream_to_check=None) -> str:
        current_stream = stream_to_check if stream_to_check else self.audio_stream
        if not current_stream and self.client and self.client.microphone:
            current_stream = self.client.microphone
        if not current_stream:
            return str(icons.get("audio", {}).get("mic", {}).get("high", "audio-input-microphone-symbolic"))
        muted = getattr(current_stream, "muted", True)
        # volume = round(getattr(current_stream, 'volume', 0)) # If you have low/medium icons
        key = "muted" if muted else "high"  # Default to high if not muted
        return str(
            icons.get("audio", {})
            .get("mic", {})
            .get(key, icons.get("audio", {}).get("mic", {}).get("medium", "audio-input-microphone-symbolic"))
        )

    def on_scale_move(self, w, s, val):
        target_stream = self.audio_stream
        if not target_stream and self.client and self.client.microphone:
            target_stream = self.client.microphone
        if target_stream and hasattr(target_stream, "volume"):
            try:
                target_stream.volume = float(val)
            except Exception as e:
                logger.error(f"Error setting volume on stream {getattr(target_stream, 'name', 'N/A')}: {e}")

    def on_mute_click(self, *_):
        target_stream = self.audio_stream
        if not target_stream and self.client and self.client.microphone:
            target_stream = self.client.microphone
        if target_stream and hasattr(target_stream, "muted"):
            try:
                target_stream.muted = not target_stream.muted
            except Exception as e:
                logger.error(f"Error toggling mute for {getattr(target_stream, 'name', 'N/A')}: {e}")

    def on_button_click(self, *_):
        parent = self.get_parent()
        while parent and not hasattr(parent, "mic_submenu"):
            parent = parent.get_parent()
        if parent and hasattr(parent, "mic_submenu") and parent.mic_submenu:
            is_vis = parent.mic_submenu.toggle_reveal()
            if hasattr(self, "chevron_icon") and self.chevron_icon:
                self.chevron_icon.set_label("" if is_vis else "")

    def destroy(self):
        logger.info(f"DESTROY: {self.__class__.__name__} for stream: {getattr(self.audio_stream, 'name', 'N/A')}")
        if self._realize_handler_id and self.handler_is_connected(self._realize_handler_id):
            self.disconnect(self._realize_handler_id)
        if (
            self.audio_stream
            and self._stream_changed_handler_id
            and hasattr(self.audio_stream, "handler_is_connected")
            and self.audio_stream.handler_is_connected(self._stream_changed_handler_id)
        ):
            self.audio_stream.disconnect(self._stream_changed_handler_id)
        if self.client:
            if (
                self._client_mic_changed_handler_id
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_mic_changed_handler_id)
            ):
                self.client.disconnect(self._client_mic_changed_handler_id)
            if (
                self._client_changed_for_init_handler_id
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_changed_for_init_handler_id)
            ):
                self.client.disconnect(self._client_changed_for_init_handler_id)
        self._realize_handler_id = self._stream_changed_handler_id = self._client_mic_changed_handler_id = (
            self._client_changed_for_init_handler_id
        ) = None
        self.audio_stream = self.client = None
        super().destroy()
