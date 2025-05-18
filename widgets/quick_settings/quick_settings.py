import os
import weakref
from typing import Any, Callable, Dict, List, Tuple, Type, Union

import gi
from fabric.utils import get_relative_path
from fabric.widgets.box import Box
from fabric.widgets.centerbox import CenterBox
from fabric.widgets.image import Image as FabricImage
from fabric.widgets.label import Label as FabricLabel
from gi.repository import GLib, Gtk
from loguru import logger

import utils.functions as helpers
from services import MprisPlayerManager
from services.screen_record import ScreenRecorder
from shared import ButtonWidget, CircleImage, HoverButton, Popover, QSChevronButton, LottieAnimation, LottieAnimationWidget
from shared.submenu import QuickSubMenu
from utils import BarConfig
from utils.icons import icons
from utils.widget_utils import util_fabricator

from ..media import PlayerBoxStack
from .shortcuts import ShortcutsContainer
from .sliders import (
    AudioSlider,
    BrightnessSlider,
    HyprSunsetIntensitySlider,
    MicrophoneSlider,
)
from .submenu.audiosink import AudioSinkSubMenu
from .submenu.bluetooth import BluetoothSubMenu, BluetoothToggle
from .submenu.ha_lights import HALightsSubMenu, HALightsToggle
from .submenu.mic import MicroPhoneSubMenu
from .submenu.power import PowerProfileSubMenu, PowerProfileToggle
from .submenu.wifi import WifiSubMenu, WifiToggle
from .togglers import (
    HyprIdleQuickSetting,
    HyprSunsetQuickSetting,
    NotificationQuickSetting,
)

gi.require_version("Gtk", "3.0")


class QuickSettingsButtonBox(Box):
    def __init__(self, config: Dict[str, Any], **kwargs):
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            name="quick-settings-button-box",
            spacing=4,
            v_align=Gtk.Align.START,
            v_expand=True,
            **kwargs,
        )
        self.grid = Gtk.Grid(
            row_spacing=10,
            column_spacing=10,
            column_homogeneous=config.get("togglers_grid_column_homogeneous", True),
            row_homogeneous=config.get("togglers_grid_row_homogeneous", True),
            visible=True,
            hexpand=True,
        )
        self.add(self.grid)
        self.active_submenu: Union[QuickSubMenu, None] = None
        self.all_created_submenus: List[QuickSubMenu] = []
        self.toggler_registry: Dict[str, Tuple[Type[Gtk.Widget], Union[Callable[[], Union[QuickSubMenu, None]], None]]] = {
            "wifi": (WifiToggle, lambda: WifiSubMenu()),
            "bluetooth": (BluetoothToggle, lambda: BluetoothSubMenu()),
            "home_assistant_lights": (HALightsToggle, lambda: HALightsSubMenu()),
            "power_profiles": (PowerProfileToggle, lambda: PowerProfileSubMenu()),
            "hypridle": (HyprIdleQuickSetting, None),
            "hyprsunset": (HyprSunsetQuickSetting, None),
            "notifications": (NotificationQuickSetting, None),
        }
        toggler_definitions = config.get("togglers", [])
        max_cols = config.get("togglers_max_cols", 2)
        self._populate_togglers(toggler_definitions, max_cols)
        for submenu_widget in self.all_created_submenus:
            self.add(submenu_widget)

    def _populate_togglers(self, toggler_definitions: List[Union[Dict[str, Any], str]], max_cols: int):
        col, row = 0, 0
        if not toggler_definitions:
            return
        for item_config in toggler_definitions:
            toggler_type: Union[str, None] = None
            if isinstance(item_config, str):
                toggler_type = item_config
            elif isinstance(item_config, dict):
                toggler_type = item_config.get("type")
            if not toggler_type or toggler_type not in self.toggler_registry:
                continue
            widget_class, submenu_factory = self.toggler_registry[toggler_type]
            instance: Union[Gtk.Widget, None] = None
            try:
                if submenu_factory:
                    submenu_instance = submenu_factory()
                    if submenu_instance is not None and not isinstance(submenu_instance, QuickSubMenu):
                        continue
                    instance = widget_class(submenu=submenu_instance)
                    if submenu_instance is not None:
                        self.all_created_submenus.append(submenu_instance)
                    if isinstance(instance, QSChevronButton):
                        instance.connect("reveal-clicked", self.set_active_submenu)
                else:
                    instance = widget_class()
            except Exception as e:
                logger.error(f"Failed to instantiate toggler '{toggler_type}': {e}")
                continue
            if instance:
                self.grid.attach(instance, col, row, 1, 1)
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1

    def set_active_submenu(self, clicked_button: QSChevronButton):
        """Sets the currently active submenu, handling visibility of others."""
        target_submenu = getattr(clicked_button, "submenu", None)
        if not target_submenu:
            if self.active_submenu is not None:
                self.active_submenu.do_reveal(False)
                for btn_widget in self.grid.get_children():
                    if isinstance(btn_widget, QSChevronButton) and getattr(btn_widget, "submenu", None) == self.active_submenu:
                        if hasattr(btn_widget, "set_active"):
                            btn_widget.set_active(False)
                        break
                self.active_submenu = None
            return
        previous_active_submenu = self.active_submenu
        if previous_active_submenu is not None and previous_active_submenu != target_submenu:
            previous_active_submenu.do_reveal(False)
            for btn_widget in self.grid.get_children():
                if isinstance(btn_widget, QSChevronButton) and getattr(btn_widget, "submenu", None) == previous_active_submenu:
                    if hasattr(btn_widget, "set_active"):
                        btn_widget.set_active(False)
                    break
        self.active_submenu = target_submenu
        if not hasattr(self.active_submenu, "toggle_reveal"):
            self.active_submenu = None
            if hasattr(clicked_button, "set_active"):
                clicked_button.set_active(False)
            return
        is_now_revealed = self.active_submenu.toggle_reveal()
        if hasattr(clicked_button, "set_active"):
            clicked_button.set_active(is_now_revealed)
        if not is_now_revealed:
            self.active_submenu = None

    def destroy(self):
        """Cleans up resources used by the QuickSettingsButtonBox."""
        for submenu in self.all_created_submenus:
            if hasattr(submenu, "destroy"):
                submenu.destroy()
        self.all_created_submenus.clear()
        for child in self.grid.get_children():
            if isinstance(child, QSChevronButton) and hasattr(child, "submenu") and child.submenu:
                try:
                    GLib.signal_handlers_disconnect_by_func(child, self.set_active_submenu)
                except (TypeError, AttributeError, ValueError):
                    pass
        super().destroy()


class QuickSettingsMenu(Box):
    def __init__(
        self, config: Dict[str, Any], screenshot_action_config: Dict[str, Any], screenrecord_action_config: Dict[str, Any], **kwargs
    ):
        super().__init__(name="quicksettings-menu", orientation=Gtk.Orientation.VERTICAL, all_visible=True, **kwargs)
        self.config = config
        self.screenshot_action_config = screenshot_action_config
        self.screenrecord_action_config = screenrecord_action_config
        self._uptime_signal_handler_id: Union[int, None] = None
        self.recorder_service = ScreenRecorder()
        self._screen_recorder_signal_id: Union[int, None] = None
        self_ref = weakref.ref(self)

        def _hide_parent_popover():
            menu_instance = self_ref()
            if not menu_instance:
                return
            parent_widget = menu_instance.get_parent()
            while parent_widget and not isinstance(parent_widget, (Popover, Gtk.Window, Gtk.Popover)):
                parent_widget = parent_widget.get_parent()
            if parent_widget:
                if hasattr(parent_widget, "popdown"):
                    parent_widget.popdown()
                elif hasattr(parent_widget, "hide"):
                    parent_widget.hide()

        def _handle_screenshot_click(_btn: Gtk.Widget):
            _hide_parent_popover()
            path = self.screenshot_action_config.get("path", "Pictures/Screenshots")
            fullscreen = self.screenshot_action_config.get("fullscreen", False)
            save_copy = self.screenshot_action_config.get("save_copy", True)
            self.recorder_service.screenshot(path=path, fullscreen=fullscreen, save_copy=save_copy)

        def _handle_screen_record_click(_btn: Gtk.Widget):
            path = self.screenrecord_action_config.get("path", "Videos/Screencasts")
            allow_audio = self.screenrecord_action_config.get("allow_audio", True)
            fullscreen_record = self.screenrecord_action_config.get("fullscreen", False)
            if self.recorder_service.is_recording:
                self.recorder_service.screenrecord_stop()
            else:
                _hide_parent_popover()
                self.recorder_service.screenrecord_start(path=path, allow_audio=allow_audio, fullscreen=fullscreen_record)

        def _handle_wlogout_click(_btn: Gtk.Widget):
            _hide_parent_popover()
            try:
                helpers.exec_shell_command_async("wlogout", lambda *_: None)
            except Exception as e:
                logger.error(f"Failed to execute wlogout: {e}")

        user_cfg = self.config.get("user", {})
        user_image_path = user_cfg.get("avatar", "~/.face")
        user_image_file = os.path.expanduser(user_image_path)
        user_image = get_relative_path("../../assets/images/banner.jpg") if not os.path.exists(user_image_file) else user_image_file
        username_setting = user_cfg.get("name", "system")
        username = GLib.get_user_name() if username_setting == "system" or username_setting is None else username_setting
        if user_cfg.get("distro_icon", False):
            username = f"{helpers.get_distro_icon()} {username}"
        username_label = FabricLabel(label=username, v_align="center", h_align="start", style_classes=["user"])

        self.uptime_box = Box(orientation="h", spacing=10, h_align="start", v_align="center", style_classes=["uptime"])
        self.uptime_icon_label = FabricLabel(label="", style_classes=["icon"], v_align="center")
        self.uptime_value_label = FabricLabel(label=helpers.uptime(), v_align="center")
        self.uptime_box.add(self.uptime_icon_label)
        self.uptime_box.add(self.uptime_value_label)

        self.user_box = Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
            name="user-box-layout",
            style_classes=["user-box"],
            hexpand=True,
            h_align=Gtk.Align.FILL,
        )
        avatar = CircleImage(image_file=user_image, size=65)
        avatar_container = Box(v_align=Gtk.Align.CENTER)
        avatar_container.add(avatar)
        self.user_box.pack_start(avatar_container, False, False, 0)

        user_info_vbox = Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2, v_align=Gtk.Align.CENTER, h_align=Gtk.Align.FILL, hexpand=True
        )
        user_info_vbox.add(username_label)
        user_info_vbox.add(self.uptime_box)
        self.user_box.pack_start(user_info_vbox, True, True, 10)

        wlogout_icon_name = icons.get("powermenu", {}).get("logout", "system-log-out-symbolic")
        self.wlogout_button = HoverButton(
            image=FabricImage(icon_name=wlogout_icon_name, icon_size=16),
            tooltip_text="Power Menu",
            v_align=Gtk.Align.END,
            on_clicked=_handle_wlogout_click,
        )
        self.wlogout_button.get_style_context().add_class("quickaction-button")
        self.wlogout_button.set_halign(Gtk.Align.END)

        ss_tooltip = self.screenshot_action_config.get("tooltip", "Take Screenshot")
        self.screenshot_button = HoverButton(
            image=FabricImage(icon_name=icons.get("ui", {}).get("camera", "camera-photo-symbolic"), icon_size=16),
            tooltip_text=ss_tooltip,
            v_align="center",
            on_clicked=_handle_screenshot_click,
        )
        self.screenshot_button.get_style_context().add_class("quickaction-button")

        initial_sr_tooltip = self.screenrecord_action_config.get("start_tooltip", "Start Recording")
        self.screen_record_button = HoverButton(
            image=FabricImage(icon_name=icons.get("ui", {}).get("camera-video", "video-display-symbolic"), icon_size=16),
            tooltip_text=initial_sr_tooltip,
            v_align="center",
            on_clicked=_handle_screen_record_click,
        )
        self.screen_record_button.get_style_context().add_class("quickaction-button")

        bottom_action_buttons_hbox = Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, h_align=Gtk.Align.CENTER)
        bottom_action_buttons_hbox.add(self.screenshot_button)
        bottom_action_buttons_hbox.add(self.screen_record_button)

        action_buttons_master_vbox = Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, v_align=Gtk.Align.CENTER)
        action_buttons_master_vbox.add(self.wlogout_button)
        action_buttons_master_vbox.add(bottom_action_buttons_hbox)

        self.user_box.pack_end(action_buttons_master_vbox, False, False, 0)

        controls_config = self.config.get("controls", {})
        qobb_config_dict = {
            "togglers": controls_config.get("togglers", []),
            "togglers_max_cols": controls_config.get("togglers_max_cols", 2),
            "togglers_grid_column_homogeneous": controls_config.get("togglers_grid_column_homogeneous", True),
            "togglers_grid_row_homogeneous": controls_config.get("togglers_grid_row_homogeneous", True),
        }
        self.quick_settings_button_box_instance = QuickSettingsButtonBox(config=qobb_config_dict, hexpand=True, h_align="fill")
        sliders_grid = Gtk.Grid(
            visible=True,
            row_spacing=10,
            column_spacing=10,
            column_homogeneous=True,
            row_homogeneous=False,
            valign=Gtk.Align.CENTER,
            hexpand=True,
            vexpand=False,
        )
        self.audio_submenu = AudioSinkSubMenu()
        self.mic_submenu = MicroPhoneSubMenu()
        sliders_box_children_content = [sliders_grid]
        configured_sliders = controls_config.get("sliders", [])
        active_sliders_count = 0
        if configured_sliders:
            for slider_name in configured_sliders:
                slider_widget: Union[Gtk.Widget, None] = None
                if slider_name == "volume":
                    slider_widget = AudioSlider()
                elif slider_name == "microphone":
                    slider_widget = MicrophoneSlider()
                elif slider_name == "brightness":
                    slider_widget = BrightnessSlider()
                elif slider_name == "hyprsunset_intensity":
                    slider_widget = HyprSunsetIntensitySlider()
                if slider_widget:
                    sliders_grid.attach(slider_widget, 0, active_sliders_count, 1, 1)
                    active_sliders_count += 1
        if "volume" in configured_sliders:
            sliders_box_children_content.append(self.audio_submenu)
        if "microphone" in configured_sliders:
            sliders_box_children_content.append(self.mic_submenu)
        shortcuts_config = self.config.get("shortcuts", {})
        slider_class = "slider-box-long"
        shortcuts_widget = None
        if shortcuts_config and shortcuts_config.get("enabled", False) and shortcuts_config.get("items"):
            num_shortcuts = len(shortcuts_config.get("items", []))
            slider_class = "slider-box-shorter" if num_shortcuts > 2 else "slider-box-short"
            shortcuts_widget = ShortcutsContainer(
                shortcuts_config=shortcuts_config["items"], style_classes=["shortcuts-grid"], v_align="start", h_align="fill"
            )
        sliders_container_box = Box(
            orientation="v",
            spacing=10,
            style_classes=[slider_class],
            children=sliders_box_children_content if sliders_grid.get_children() or len(sliders_box_children_content) > 1 else [],
            h_expand=True,
            h_align="fill",
            vexpand=False,
        )
        center_content_main_grid = Gtk.Grid(visible=True, column_spacing=10, hexpand=True, column_homogeneous=False)
        added_sliders_box = False
        if sliders_container_box.get_children():
            col_span = 2 if shortcuts_widget else 1
            center_content_main_grid.attach(sliders_container_box, 0, 0, col_span, 1)
            added_sliders_box = True
        if shortcuts_widget:
            col_attach = 2 if added_sliders_box else 0
            center_content_main_grid.attach(shortcuts_widget, col_attach, 0, 1, 1)
        start_section_content = Box(
            orientation="v",
            spacing=10,
            style_classes=["section-box"],
            children=(self.user_box, self.quick_settings_button_box_instance),
            hexpand=True,
            h_align="fill",
        )
        start_section_content.set_valign(Gtk.Align.START)
        center_section_content = Box(
            orientation="v",
            style_classes=["section-box"],
            children=[center_content_main_grid] if center_content_main_grid.get_children() else [],
            hexpand=True,
            h_align="fill",
        )
        media_player_section_content = None
        media_config = self.config.get("media", {})
        if media_config.get("enabled", False):
            media_player_section_content = Box(
                orientation="v",
                spacing=10,
                style_classes=["section-box"],
                children=(PlayerBoxStack(MprisPlayerManager(), config=media_config)),
                hexpand=True,
                h_align="fill",
            )
        cb_start_children = [start_section_content] if start_section_content.get_children() else None
        cb_center_children = [center_section_content] if center_section_content.get_children() else None
        cb_end_children = [media_player_section_content] if media_player_section_content else None
        main_layout_box = CenterBox(
            orientation="v",
            style_classes=["quick-settings-box"],
            start_children=cb_start_children,
            center_children=cb_center_children,
            end_children=cb_end_children,
        )
        self.add(main_layout_box)
        self._screen_recorder_signal_id = self.recorder_service.connect("recording", self._update_screen_record_button_state)
        GLib.idle_add(self._update_screen_record_button_state, self.recorder_service, self.recorder_service.is_recording)
        self._uptime_update_callback_ref = lambda _s, val: self.uptime_value_label.set_label(val.get("uptime", "N/A"))
        self._uptime_signal_handler_id = util_fabricator.connect("changed", self._uptime_update_callback_ref)

    def _update_screen_record_button_state(self, _service: ScreenRecorder, is_recording: bool):
        if not hasattr(self, "screen_record_button") or not self.screen_record_button:
            return GLib.SOURCE_REMOVE

        actual_image_widget = None
        if hasattr(self.screen_record_button, "get_image") and callable(self.screen_record_button.get_image):
            actual_image_widget = self.screen_record_button.get_image()
        elif hasattr(self.screen_record_button, "image_widget"):
            actual_image_widget = self.screen_record_button.image_widget
        elif hasattr(self.screen_record_button, "image") and isinstance(self.screen_record_button.image, (Gtk.Image, FabricImage)):
            actual_image_widget = self.screen_record_button.image

        if not actual_image_widget or not hasattr(actual_image_widget, "set_from_icon_name"):
            return GLib.SOURCE_REMOVE

        if is_recording:
            stop_icon = icons.get("custom", {}).get("recording_stop", "media-record-symbolic")
            actual_image_widget.set_from_icon_name(stop_icon, 16)
            tooltip = self.screenrecord_action_config.get("stop_tooltip", "Stop Recording")
            self.screen_record_button.set_tooltip_text(tooltip)
        else:
            start_icon = icons.get("ui", {}).get("camera-video", "video-display-symbolic")
            actual_image_widget.set_from_icon_name(start_icon, 16)
            tooltip = self.screenrecord_action_config.get("start_tooltip", "Start Recording")
            self.screen_record_button.set_tooltip_text(tooltip)
        return GLib.SOURCE_REMOVE

    def destroy(self):
        """Cleans up resources used by the QuickSettingsMenu."""
        if (
            self._uptime_signal_handler_id is not None
            and hasattr(util_fabricator, "handler_is_connected")
            and util_fabricator.handler_is_connected(self._uptime_signal_handler_id)
        ):
            util_fabricator.disconnect(self._uptime_signal_handler_id)
            self._uptime_signal_handler_id = None
        if hasattr(self, "recorder_service") and self._screen_recorder_signal_id is not None:
            if hasattr(self.recorder_service, "handler_is_connected") and self.recorder_service.handler_is_connected(
                self._screen_recorder_signal_id
            ):
                self.recorder_service.disconnect(self._screen_recorder_signal_id)
            self._screen_recorder_signal_id = None
        if hasattr(self, "quick_settings_button_box_instance") and hasattr(self.quick_settings_button_box_instance, "destroy"):
            self.quick_settings_button_box_instance.destroy()
        if hasattr(self, "audio_submenu") and hasattr(self.audio_submenu, "destroy"):
            self.audio_submenu.destroy()
        if hasattr(self, "mic_submenu") and hasattr(self.mic_submenu, "destroy"):
            self.mic_submenu.destroy()
        super().destroy()


class QuickSettingsButtonWidget(ButtonWidget):
    def __init__(self, widget_config: BarConfig, **kwargs):
        qs_menu_structure_config = widget_config.get("quick_settings", {})
        super().__init__(qs_menu_structure_config, name=widget_config.get("name", "quick_settings_bar_button"), **kwargs)
        self.quick_settings_menu_content_config: Dict[str, Any] = qs_menu_structure_config
        self.screenshot_action_config = widget_config.get("screen_shot", {})
        self.screenrecord_action_config = widget_config.get("screen_record", {})
        self.panel_icon_size = self.quick_settings_menu_content_config.get("panel_icon_size", 16)
        from services import audio_service, bluetooth_service, network_service

        self.recorder_service = ScreenRecorder()
        self._screen_recorder_bar_signal_id: Union[int, None] = None
        self.audio = audio_service
        self.network = network_service
        self.bluetooth_service = bluetooth_service
        self.network_icon = FabricImage(style_classes=["panel-icon"], visible=True)
        self.audio_icon = FabricImage(style_classes=["panel-icon"], visible=True)
        self.bluetooth_icon = FabricImage(style_classes=["panel-icon"], visible=True)
        lottie_path_config = self.screenrecord_action_config.get("bar_lottie_path", "../../assets/icons/lottie/recording.json")
        lottie_scale_config = self.screenrecord_action_config.get("bar_lottie_scale", 0.3)
        actual_lottie_file_path = ""
        try:
            actual_lottie_file_path = lottie_path_config
            if not os.path.isabs(lottie_path_config) and (".." in lottie_path_config or not lottie_path_config.startswith("/")):
                base_path_guess = os.path.dirname(os.path.abspath(__file__))
                actual_lottie_file_path = os.path.abspath(os.path.join(base_path_guess, lottie_path_config))
            if not os.path.exists(actual_lottie_file_path):
                actual_lottie_file_path = get_relative_path(lottie_path_config)
                if not os.path.exists(actual_lottie_file_path):
                    raise FileNotFoundError(f"Lottie file not found at {lottie_path_config} or resolved paths {actual_lottie_file_path}")
            self.recording_lottie_widget = LottieAnimationWidget(
                LottieAnimation.from_file(actual_lottie_file_path), scale=lottie_scale_config, visible=False
            )
        except Exception as e:
            logger.warning(
                f"[QSButtonWidget] Lottie load FAILED (path: '{lottie_path_config}', resolved: '{actual_lottie_file_path}'): {e}. Using static icon fallback."
            )
            fallback_icon_name = self.screenrecord_action_config.get(
                "bar_icon_active", icons.get("custom", {}).get("recording_active_bar", "media-record-symbolic")
            )
            self.recording_lottie_widget = FabricImage(
                icon_name=fallback_icon_name,
                style_classes=["panel-icon", "recording-indicator", "recording-indicator-active"],
                visible=False,
            )

        self._network_primary_dev_sid: Union[int, None] = None
        self._network_device_ready_sid: Union[int, None] = None
        self._network_prop_handler_ids: List[Tuple[Any, int]] = []
        self._bt_enabled_handler_id: Union[int, None] = None
        self._bt_connected_handler_id: Union[int, None] = None
        self._bt_devices_handler_id: Union[int, None] = None
        self._audio_speaker_changed_handler_id: Union[int, None] = None
        self._speaker_vol_h: Union[int, None] = None
        self._speaker_mut_h: Union[int, None] = None
        self._conn_spk_inst: Union[Any, None] = None
        if self.network:
            self._network_primary_dev_sid = self.network.connect("notify::primary-device", self._on_network_property_changed_cb)
            self._network_device_ready_sid = self.network.connect("device-ready", self._on_network_device_ready_cb)
        if self.audio:
            self._audio_speaker_changed_handler_id = self.audio.connect("notify::speaker", self._on_speaker_changed_cb)
        if self.bluetooth_service:
            self._bt_enabled_handler_id = self.bluetooth_service.connect("notify::enabled", self._on_bluetooth_property_changed_cb)
            self._connect_bluetooth_device_signals()
        if self.recorder_service:
            self._screen_recorder_bar_signal_id = self.recorder_service.connect("recording", self._on_recording_state_changed_bar)
        if self.network:
            GLib.idle_add(self.on_network_device_ready, self.network)
        else:
            GLib.idle_add(self.update_network_icon)
        GLib.idle_add(self.on_speaker_changed)
        GLib.idle_add(self.update_bluetooth_icon)
        GLib.idle_add(self._on_recording_state_changed_bar, self.recorder_service, self.recorder_service.is_recording)
        self.icon_container = Box(orientation="h", spacing=2, visible=True)
        self.icon_container.add(self.network_icon)
        self.icon_container.add(self.audio_icon)
        self.icon_container.add(self.bluetooth_icon)
        self.icon_container.add(self.recording_lottie_widget)
        if hasattr(self, "set_child") and callable(self.set_child):
            self.set_child(self.icon_container)
        elif isinstance(self, Gtk.Button) and not self.get_label():
            self.set_image(self.icon_container)
            self.set_always_show_image(True)
        self.connect("clicked", self._on_button_clicked)
        self.popup: Union[Popover, Gtk.Popover, None] = None

    def _connect_bluetooth_device_signals(self):
        if not self.bluetooth_service or not hasattr(self.bluetooth_service, "find_property"):
            return
        try:
            if self.bluetooth_service.find_property("connected-devices"):
                self._bt_connected_handler_id = self.bluetooth_service.connect(
                    "notify::connected-devices", self._on_bluetooth_property_changed_cb
                )
            if self.bluetooth_service.find_property("devices"):
                self._bt_devices_handler_id = self.bluetooth_service.connect("notify::devices", self._on_bluetooth_property_changed_cb)
        except Exception:
            pass

    def _on_network_property_changed_cb(self, _obj: Any, _pspec: Any):
        GLib.idle_add(self.update_network_icon)
        return GLib.SOURCE_REMOVE

    def _on_network_device_ready_cb(self, client: Any, *_extra_args: Any):
        GLib.idle_add(self.on_network_device_ready, client)
        return GLib.SOURCE_REMOVE

    def _on_speaker_changed_cb(self, _obj: Any, _pspec: Any):
        GLib.idle_add(self.on_speaker_changed)
        return GLib.SOURCE_REMOVE

    def _on_bluetooth_property_changed_cb(self, _obj: Any, _pspec: Any):
        GLib.idle_add(self.update_bluetooth_icon)
        return GLib.SOURCE_REMOVE

    def _on_button_clicked(self, _widget: Gtk.Widget):
        if self.popup is None:
            try:

                def _content_factory():
                    return QuickSettingsMenu(
                        config=self.quick_settings_menu_content_config,
                        screenshot_action_config=self.screenshot_action_config,
                        screenrecord_action_config=self.screenrecord_action_config,
                    )

                self.popup = Popover(content_factory=_content_factory, point_to=self)
            except Exception as e:
                logger.error(f"Error creating Popover instance: {e}")
                self.popup = None
                return True

        if self.popup:
            try:
                if hasattr(self.popup, "open"):
                    self.popup.open()
                elif hasattr(self.popup, "popup"):
                    self.popup.popup()
                else:
                    logger.error(f"Popover object {self.popup} has no open() or popup() method.")
            except Exception as e:
                logger.error(f"Error calling open/popup on Popover: {e}")
                if self.popup and hasattr(self.popup, "destroy"):
                    self.popup.destroy()
                self.popup = None
        return True

    def update_network_icon(self, *_args: Any):
        """Updates the network icon based on the current network state."""
        final_icon_name = icons.get("network-offline-symbolic", "network-offline-symbolic")
        if self.network:
            prim_device_type = getattr(self.network, "primary_device", None)
            if prim_device_type == "wifi":
                wifi_device = getattr(self.network, "wifi_device", None)
                if wifi_device and hasattr(wifi_device, "icon_name") and callable(wifi_device.icon_name):
                    final_icon_name = wifi_device.icon_name()
                elif wifi_device and hasattr(wifi_device, "get_property"):
                    try:
                        final_icon_name = wifi_device.get_property("icon-name") or final_icon_name
                    except:
                        pass
                else:
                    final_icon_name = icons.get("network", {}).get("wifi", {}).get("disabled", "network-wireless-offline-symbolic")
            elif prim_device_type == "wired":
                eth_device = getattr(self.network, "ethernet_device", None)
                if eth_device and hasattr(eth_device, "get_property"):
                    try:
                        reported_icon = eth_device.get_property("icon-name")
                        if reported_icon and "unknown" not in reported_icon.lower():
                            final_icon_name = reported_icon
                        else:
                            final_icon_name = icons.get("network", {}).get("wired-symbolic", "network-wired-symbolic")
                    except:
                        final_icon_name = icons.get("network", {}).get("wired-symbolic", "network-wired-symbolic")
                else:
                    final_icon_name = icons.get("network", {}).get("wired-no-route-symbolic", "network-offline-symbolic")
        self.network_icon.set_from_icon_name(final_icon_name, self.panel_icon_size)
        return GLib.SOURCE_REMOVE

    def _is_network_connected(self, _prim: Any, _wi: Any, _eth: Any) -> bool:
        try:
            if self.network and hasattr(self.network, "connectivity"):
                NM_CONNECTIVITY_FULL = 4
                if self.network.connectivity == NM_CONNECTIVITY_FULL:
                    return True
            active_conn = getattr(self.network, "primary_connection", getattr(self.network, "active_connection", None))
            if active_conn and hasattr(active_conn, "state"):
                NM_ACTIVE_CONNECTION_STATE_ACTIVATED = 2
                return active_conn.state == NM_ACTIVE_CONNECTION_STATE_ACTIVATED
        except Exception:
            pass
        return False

    def _disconnect_all_network_prop_handlers(self):
        for obj_with_signal, handler_id in list(self._network_prop_handler_ids):
            if (
                obj_with_signal
                and handler_id is not None
                and hasattr(obj_with_signal, "handler_is_connected")
                and obj_with_signal.handler_is_connected(handler_id)
            ):
                obj_with_signal.disconnect(handler_id)
        self._network_prop_handler_ids.clear()

    def on_network_device_ready(self, client: Any):
        """Sets up signal handlers for network device property changes."""
        self._disconnect_all_network_prop_handlers()
        devices_to_monitor = []
        if client:
            devices_to_monitor.append(client)
        wifi = getattr(client, "wifi_device", None) if client else None
        eth = getattr(client, "ethernet_device", None) if client else None
        if wifi:
            devices_to_monitor.append(wifi)
        if eth:
            devices_to_monitor.append(eth)
        props_to_watch = ["icon-name", "enabled", "state", "active-access-point", "carrier", "primary-device", "connectivity"]
        for device in devices_to_monitor:
            if device and hasattr(device, "connect") and hasattr(device, "find_property"):
                for prop_name in props_to_watch:
                    if device.find_property(prop_name):
                        try:
                            handler_id = device.connect(f"notify::{prop_name}", self._on_network_property_changed_cb)
                            self._network_prop_handler_ids.append((device, handler_id))
                        except TypeError:
                            pass
        GLib.idle_add(self.update_network_icon)
        return GLib.SOURCE_REMOVE

    def on_speaker_changed(self, *_args: Any):
        """Sets up signal handlers for speaker property changes."""
        speaker_obj_cb = lambda _o, _p: GLib.idle_add(self.update_volume)
        if self._conn_spk_inst:
            self._speaker_vol_h = self._disconnect_handler_id_safe(self._conn_spk_inst, self._speaker_vol_h)
            self._speaker_mut_h = self._disconnect_handler_id_safe(self._conn_spk_inst, self._speaker_mut_h)
        self._conn_spk_inst = None
        if self.audio and self.audio.speaker and hasattr(self.audio.speaker, "connect"):
            self._conn_spk_inst = self.audio.speaker
            speaker_obj = self._conn_spk_inst
            if hasattr(speaker_obj, "find_property") and speaker_obj.find_property("volume"):
                self._speaker_vol_h = speaker_obj.connect("notify::volume", speaker_obj_cb)
            mute_prop = "is-muted" if hasattr(speaker_obj, "find_property") and speaker_obj.find_property("is-muted") else "muted"
            if hasattr(speaker_obj, "find_property") and speaker_obj.find_property(mute_prop):
                self._speaker_mut_h = speaker_obj.connect(f"notify::{mute_prop}", speaker_obj_cb)
            GLib.idle_add(self.update_volume)
        else:
            GLib.idle_add(self.update_volume)
        return GLib.SOURCE_REMOVE

    def update_volume(self, *_args: Any):
        """Updates the volume icon based on the current audio state."""
        from utils.widget_utils import get_audio_icon_name

        key = icons.get("audio", {}).get("volume", {}).get("muted", "audio-volume-muted-symbolic")
        calc_vol = 0
        is_muted = True
        if self.audio and self.audio.speaker:
            spk = self.audio.speaker
            if hasattr(spk, "volume"):
                calc_vol = round(spk.volume)
            mute_val = getattr(spk, "is_muted", getattr(spk, "muted", True))
            is_muted = bool(mute_val)
            info = get_audio_icon_name(calc_vol, is_muted)
            if info and "icon" in info:
                key = info["icon"]
        else:
            info = get_audio_icon_name(0, True)
            key = (
                info["icon"]
                if info and "icon" in info
                else icons.get("audio", {}).get("volume", {}).get("muted-fallback", "audio-volume-muted-symbolic")
            )
        self.audio_icon.set_from_icon_name(key, self.panel_icon_size)
        return GLib.SOURCE_REMOVE

    def update_bluetooth_icon(self, *_args: Any):
        """Updates the bluetooth icon based on the current bluetooth state."""
        name = icons.get("bluetooth", {}).get("disabled-symbolic", "bluetooth-disabled-symbolic")
        if self.bluetooth_service and getattr(self.bluetooth_service, "enabled", False):
            name = icons.get("bluetooth", {}).get("active-symbolic", "bluetooth-active-symbolic")
            conn_dev = getattr(self.bluetooth_service, "connected_devices", [])
            if isinstance(conn_dev, (list, tuple)) and len(conn_dev) > 0:
                name = icons.get("bluetooth", {}).get("connected-symbolic", name)
        self.bluetooth_icon.set_from_icon_name(name, self.panel_icon_size)
        return GLib.SOURCE_REMOVE

    def _on_recording_state_changed_bar(self, _service: ScreenRecorder, is_recording: bool):
        if is_recording:
            self.recording_lottie_widget.show()
            if hasattr(self.recording_lottie_widget, "play_loop"):
                self.recording_lottie_widget.play_loop()
        else:
            if hasattr(self.recording_lottie_widget, "stop_play"):
                self.recording_lottie_widget.stop_play()
            self.recording_lottie_widget.hide()
        return GLib.SOURCE_REMOVE

    def _disconnect_handler_id_safe(self, obj: Any, handler_id: Union[int, None]) -> None:
        if obj and handler_id is not None and hasattr(obj, "handler_is_connected") and obj.handler_is_connected(handler_id):
            obj.disconnect(handler_id)
        return None

    def destroy(self):
        """Cleans up resources used by the QuickSettingsButtonWidget."""
        if hasattr(self, "recording_lottie_widget") and hasattr(self.recording_lottie_widget, "stop_play"):
            self.recording_lottie_widget.stop_play()
        if self.popup:
            self.popup.destroy()
            self.popup = None
        self._disconnect_all_network_prop_handlers()
        if self.network:
            self._network_primary_dev_sid = self._disconnect_handler_id_safe(self.network, self._network_primary_dev_sid)
            self._network_device_ready_sid = self._disconnect_handler_id_safe(self.network, self._network_device_ready_sid)
        if self.audio:
            self._audio_speaker_changed_handler_id = self._disconnect_handler_id_safe(self.audio, self._audio_speaker_changed_handler_id)
        if self._conn_spk_inst:
            self._speaker_vol_h = self._disconnect_handler_id_safe(self._conn_spk_inst, self._speaker_vol_h)
            self._speaker_mut_h = self._disconnect_handler_id_safe(self._conn_spk_inst, self._speaker_mut_h)
        if self.bluetooth_service:
            self._bt_enabled_handler_id = self._disconnect_handler_id_safe(self.bluetooth_service, self._bt_enabled_handler_id)
            self._bt_connected_handler_id = self._disconnect_handler_id_safe(self.bluetooth_service, self._bt_connected_handler_id)
            self._bt_devices_handler_id = self._disconnect_handler_id_safe(self.bluetooth_service, self._bt_devices_handler_id)
        if self.recorder_service and self._screen_recorder_bar_signal_id is not None:
            if hasattr(self.recorder_service, "handler_is_connected") and self.recorder_service.handler_is_connected(
                self._screen_recorder_bar_signal_id
            ):
                self.recorder_service.disconnect(self._screen_recorder_bar_signal_id)
            self._screen_recorder_bar_signal_id = None
        super().destroy()
