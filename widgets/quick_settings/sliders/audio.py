# widgets/quick_settings/sliders/audio.py

from typing import Optional, Any
from fabric.widgets.box import Box
from gi.repository import Gtk, GLib
from loguru import logger

from services import audio_service
from shared import SettingSlider
from shared.widget_container import HoverButton
from utils.icons import icons
from utils.widget_utils import text_icon


class AudioSlider(SettingSlider):
    """A widget to display a scale for audio settings."""

    def __init__(self, audio_stream: Optional[Any] = None, show_chevron: bool = True):
        stream_name_for_log = (
            getattr(audio_stream, "name", "Default Device Speaker (pending init)")
            if audio_stream
            else "Default Device Speaker (pending init)"
        )
        logger.info(f"INIT: {self.__class__.__name__} for stream: {stream_name_for_log}")

        self.client = audio_service
        self.audio_stream = audio_stream
        self._stream_changed_handler_id: Optional[int] = None
        self._client_speaker_changed_handler_id: Optional[int] = None
        self._client_changed_for_init_handler_id: Optional[int] = None
        self._realize_handler_id: Optional[int] = None

        self.pixel_size = 16
        initial_icon_name = str(icons.get("audio", {}).get("volume", {}).get("high", "audio-volume-high-symbolic"))
        initial_volume = 0
        if self.audio_stream and hasattr(self.audio_stream, "muted") and hasattr(self.audio_stream, "volume"):
            initial_icon_name = str(
                icons.get("audio", {}).get("volume", {}).get("muted" if self.audio_stream.muted else "high", initial_icon_name)
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
            current_children = list(getattr(self, "children", []))
            current_children.append(self.chevron_btn)
            self.children = tuple(current_children)

        if not self.audio_stream:
            logger.debug(f"{self.__class__.__name__}: No specific audio_stream, setting up for default device speaker.")
            self._setup_default_device_speaker_logic()
        else:
            logger.debug(f"{self.__class__.__name__}: Initializing for specific stream: {getattr(self.audio_stream, 'name', 'N/A')}")
            if hasattr(self.audio_stream, "connect"):
                self._stream_changed_handler_id = self.audio_stream.connect("changed", self.update_state)

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

    def _setup_default_device_speaker_logic(self):
        def init_or_reset_default_speaker_cb(*args):
            logger.debug(f"{self.__class__.__name__}: init_or_reset_default_speaker_cb called.")
            if (
                self.audio_stream
                and self._stream_changed_handler_id
                and hasattr(self.audio_stream, "handler_is_connected")
                and self.audio_stream.handler_is_connected(self._stream_changed_handler_id)
            ):
                self.audio_stream.disconnect(self._stream_changed_handler_id)
            self._stream_changed_handler_id = None
            if (
                self._client_changed_for_init_handler_id
                and self.client
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_changed_for_init_handler_id)
            ):
                self.client.disconnect(self._client_changed_for_init_handler_id)
            self._client_changed_for_init_handler_id = None

            if self.client and self.client.speaker:
                self.audio_stream = self.client.speaker
                logger.info(f"{self.__class__.__name__}: Now controlling default speaker: {getattr(self.audio_stream, 'name', 'N/A')}")
                if self.get_realized():
                    GLib.idle_add(self.update_state, priority=GLib.PRIORITY_DEFAULT_IDLE)
                if hasattr(self.audio_stream, "connect"):
                    self._stream_changed_handler_id = self.audio_stream.connect("changed", self.update_state)
                if (
                    self._client_speaker_changed_handler_id
                    and self.client
                    and hasattr(self.client, "handler_is_connected")
                    and self.client.handler_is_connected(self._client_speaker_changed_handler_id)
                ):
                    self.client.disconnect(self._client_speaker_changed_handler_id)
                self._client_speaker_changed_handler_id = self.client.connect("speaker-changed", init_or_reset_default_speaker_cb)
            else:
                logger.warning(f"{self.__class__.__name__}: Client or client.speaker is None during default speaker setup.")
                self.audio_stream = None
                if self.get_realized():
                    GLib.idle_add(self.update_state, priority=GLib.PRIORITY_DEFAULT_IDLE)
            return GLib.SOURCE_REMOVE

        if self.client:
            if self.client.speaker:
                GLib.idle_add(init_or_reset_default_speaker_cb)
            else:
                self._client_changed_for_init_handler_id = self.client.connect("changed", init_or_reset_default_speaker_cb)
        else:
            logger.error(f"{self.__class__.__name__}: audio_service (self.client) is None.")

    def update_state(self, *args):
        if not self.get_realized():
            logger.debug(
                f"{self.__class__.__name__} for '{getattr(self.audio_stream, 'name', 'N/A')}': update_state NOT realized. Skipping."
            )
            return False
        if not self.get_visible():
            logger.debug(
                f"{self.__class__.__name__} for '{getattr(self.audio_stream, 'name', 'N/A')}': update_state NOT visible. Skipping scale part."
            )

        target_stream = self.audio_stream
        if not target_stream and self.client and self.client.speaker:
            target_stream = self.client.speaker
        if not target_stream:
            if hasattr(self, "scale") and self.scale:
                self.scale.set_sensitive(False)
            if hasattr(self, "icon") and self.icon:
                self.icon.set_from_icon_name(
                    str(icons.get("audio", {}).get("volume", {}).get("disabled", "audio-volume-muted-blocking-symbolic")), self.pixel_size
                )
            return False

        if hasattr(self, "scale") and self.scale and self.get_visible():
            adj = self.scale.get_adjustment()
            if not adj or not isinstance(adj, Gtk.Adjustment):
                logger.error(f"{self.__class__.__name__}: Invalid adjustment.")
                return False
            muted = getattr(target_stream, "muted", True)
            volume = getattr(target_stream, "volume", 0)
            self.scale.set_sensitive(not muted)
            # logger.debug(f"{self.__class__.__name__} '{getattr(target_stream,'name','N/A')}': Adj valid. L:{adj.get_lower()} U:{adj.get_upper()} V:{adj.get_value()}. Set to {float(volume)}") # Verbose
            try:
                if abs(adj.get_value() - float(volume)) > 1e-6:
                    adj.set_value(float(volume))
            except Exception as e:
                logger.error(f"Slider: Error setting scale value: {e}", exc_info=True)
            if hasattr(self.scale, "set_tooltip_text"):
                self.scale.set_tooltip_text(f"{round(volume)}%")
        if hasattr(self, "icon") and self.icon:
            self.icon.set_from_icon_name(str(self._get_icon_name(target_stream)), self.pixel_size)
        return False

    def _get_icon_name(self, stream_to_check=None) -> str:
        curr_stream = stream_to_check if stream_to_check else self.audio_stream
        if not curr_stream and self.client and self.client.speaker:
            curr_stream = self.client.speaker
        if not curr_stream:
            return str(icons.get("audio", {}).get("volume", {}).get("high", "audio-volume-high-symbolic"))
        muted = getattr(curr_stream, "muted", True)
        volume = round(getattr(curr_stream, "volume", 0))
        if muted:
            key = "muted"
        elif volume == 0:
            key = "off"
        elif volume < 34:
            key = "low"
        elif volume < 67:
            key = "medium"
        else:
            key = "high"
        return str(
            icons.get("audio", {})
            .get("volume", {})
            .get(key, icons.get("audio", {}).get("volume", {}).get("medium", "audio-volume-medium-symbolic"))
        )

    def on_scale_move(self, w, s, val):
        target_stream = self.audio_stream
        if not target_stream and self.client and self.client.speaker:
            target_stream = self.client.speaker
        if target_stream and hasattr(target_stream, "volume"):
            try:
                target_stream.volume = float(val)
            except Exception as e:
                logger.error(f"Error setting volume on stream: {e}")

    def on_button_click(self, *_):
        parent = self.get_parent()
        while parent and not hasattr(parent, "audio_submenu"):
            parent = parent.get_parent()
        if parent and hasattr(parent, "audio_submenu") and parent.audio_submenu:
            is_vis = parent.audio_submenu.toggle_reveal()
            if hasattr(self, "chevron_icon") and self.chevron_icon:
                self.chevron_icon.set_label("" if is_vis else "")

    def on_mute_click(self, *_):
        target_stream = self.audio_stream
        if not target_stream and self.client and self.client.speaker:
            target_stream = self.client.speaker
        if target_stream and hasattr(target_stream, "muted"):
            try:
                target_stream.muted = not target_stream.muted
            except Exception as e:
                logger.error(f"Error toggling mute: {e}")

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
                self._client_speaker_changed_handler_id
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_speaker_changed_handler_id)
            ):
                self.client.disconnect(self._client_speaker_changed_handler_id)
            if (
                self._client_changed_for_init_handler_id
                and hasattr(self.client, "handler_is_connected")
                and self.client.handler_is_connected(self._client_changed_for_init_handler_id)
            ):
                self.client.disconnect(self._client_changed_for_init_handler_id)
        self._realize_handler_id = self._stream_changed_handler_id = self._client_speaker_changed_handler_id = (
            self._client_changed_for_init_handler_id
        ) = None
        self.audio_stream = self.client = None
        super().destroy()
