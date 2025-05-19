import contextlib
import os
import weakref
from typing import Any, Callable, Dict, List, Tuple, Type, Union

import gi
from fabric.utils import get_relative_path
from fabric.widgets.box import Box
from fabric.widgets.centerbox import CenterBox
from fabric.widgets.image import Image as FabricImage
from fabric.widgets.label import Label as FabricLabel
from gi.repository import Gdk, GLib, GObject, Gtk
from loguru import logger

import utils.functions as helpers
from services import MprisPlayerManager
from services.screen_record import ScreenRecorder
from shared import ButtonWidget, CircleImage, HoverButton, LottieAnimation, LottieAnimationWidget, Popover, QSChevronButton
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
gi.require_version("Gdk", "3.0")
gi.require_version("GObject", "2.0")


class QuickSettingsButtonBox(Box):
    """A box to display the quick settings buttons."""

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
        self._reveal_clicked_handlers: List[Tuple[QSChevronButton, int]] = []

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
            if isinstance(submenu_widget, Gtk.Widget):
                self.add(submenu_widget)
                submenu_widget.set_visible(False)

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
                        logger.warning(f"Submenu for {toggler_type} is not a QuickSubMenu.")
                        continue
                    instance = widget_class(submenu=submenu_instance)
                    if submenu_instance is not None:
                        self.all_created_submenus.append(submenu_instance)
                    if isinstance(instance, QSChevronButton):
                        handler_id = instance.connect("reveal-clicked", self.set_active_submenu)
                        self._reveal_clicked_handlers.append((instance, handler_id))
                else:
                    instance = widget_class()
            except Exception as e:
                logger.error(f"Failed to instantiate toggler '{toggler_type}': {e}", exc_info=True)
                continue
            if instance:
                self.grid.attach(instance, col, row, 1, 1)
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1

    def set_active_submenu(self, clicked_button: QSChevronButton):
        target_submenu = getattr(clicked_button, "submenu", None)

        if self.active_submenu is not None and self.active_submenu != target_submenu:
            if hasattr(self.active_submenu, "do_reveal"):
                self.active_submenu.do_reveal(False)
            elif hasattr(self.active_submenu, "set_visible"):
                self.active_submenu.set_visible(False)

            for btn_widget_child in self.grid.get_children():
                if isinstance(btn_widget_child, QSChevronButton) and getattr(btn_widget_child, "submenu", None) == self.active_submenu:
                    if hasattr(btn_widget_child, "set_active"):
                        btn_widget_child.set_active(False)
                    break
            self.active_submenu = None

        if target_submenu is None:
            return

        self.active_submenu = target_submenu
        is_now_revealed = False

        current_active_submenu = self.active_submenu
        if current_active_submenu is not None:
            if hasattr(current_active_submenu, "toggle_reveal"):
                is_now_revealed = current_active_submenu.toggle_reveal()
            elif hasattr(current_active_submenu, "get_visible") and hasattr(current_active_submenu, "set_visible"):
                current_state = current_active_submenu.get_visible()
                current_active_submenu.set_visible(not current_state)
                is_now_revealed = not current_state
            else:
                logger.error(f"Active submenu {current_active_submenu} has no suitable toggle method.")
                self.active_submenu = None
                if hasattr(clicked_button, "set_active"):
                    clicked_button.set_active(False)
                return
        else:
            if hasattr(clicked_button, "set_active"):
                clicked_button.set_active(False)
            return

        if hasattr(clicked_button, "set_active"):
            clicked_button.set_active(is_now_revealed)

        if not is_now_revealed:
            self.active_submenu = None

    def destroy(self):
        logger.debug(f"QuickSettingsButtonBox ({self.get_name()}): Destroying.")
        for submenu in self.all_created_submenus:
            if submenu and hasattr(submenu, "destroy"):
                submenu.destroy()
        self.all_created_submenus.clear()

        for button, handler_id in self._reveal_clicked_handlers:
            if button and hasattr(button, "handler_is_connected") and button.handler_is_connected(handler_id):
                with contextlib.suppress(Exception):
                    button.disconnect(handler_id)
        self._reveal_clicked_handlers.clear()

        children_to_remove = list(self.grid.get_children())
        for child in children_to_remove:
            self.grid.remove(child)
            if hasattr(child, "destroy"):
                child.destroy()
        super().destroy()
        logger.debug(f"QuickSettingsButtonBox ({self.get_name()}): Destroyed.")


class QuickSettingsMenu(Box):
    """A menu to quick settings."""

    def __init__(
        self, config: Dict[str, Any], screenshot_action_config: Dict[str, Any], screenrecord_action_config: Dict[str, Any], **kwargs
    ):
        super().__init__(name="quicksettings-menu", orientation=Gtk.Orientation.VERTICAL, **kwargs)
        self.config = config
        self.screenshot_action_config: Dict[str, Any] = screenshot_action_config
        self.screenrecord_action_config: Dict[str, Any] = screenrecord_action_config
        self._uptime_signal_handler_id: Union[int, None] = None
        self.recorder_service = ScreenRecorder()
        self._screen_recorder_signal_id: Union[int, None] = None
        self_ref = weakref.ref(self)

        def _hide_parent_popover():
            menu_instance = self_ref()
            if not menu_instance:
                return

            parent_popover = menu_instance.get_ancestor(Popover)
            if not parent_popover:
                parent_popover = menu_instance.get_ancestor(Gtk.Popover)

            if parent_popover:
                if hasattr(parent_popover, "close"):
                    parent_popover.close()
                elif hasattr(parent_popover, "popdown"):
                    parent_popover.popdown()
                elif hasattr(parent_popover, "hide"):
                    parent_popover.hide()
            else:
                logger.warning("Could not find parent Popover to hide for QuickSettingsMenu.")

        def _handle_screenshot_click(_btn: Gtk.Widget):
            _hide_parent_popover()
            path = str(self.screenshot_action_config.get("path", "Pictures/Screenshots"))
            fullscreen = bool(self.screenshot_action_config.get("fullscreen", False))
            save_copy = bool(self.screenshot_action_config.get("save_copy", True))
            self.recorder_service.screenshot(path=path, fullscreen=fullscreen, save_copy=save_copy)

        def _handle_screen_record_click(_btn: Gtk.Widget):
            path = str(self.screenrecord_action_config.get("path", "Videos/Screencasts"))
            allow_audio = bool(self.screenrecord_action_config.get("allow_audio", True))
            fullscreen_record = bool(self.screenrecord_action_config.get("fullscreen", False))
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
        user_image_file = os.path.expanduser(str(user_image_path))
        user_image = get_relative_path("../../assets/images/banner.jpg") if not os.path.exists(user_image_file) else user_image_file
        username_setting = user_cfg.get("name", "system")
        username = GLib.get_user_name() if username_setting == "system" or username_setting is None else str(username_setting)
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

        wlogout_icon_name_raw = icons.get("powermenu", {}).get("logout", "system-log-out-symbolic")
        wlogout_icon_name = str(wlogout_icon_name_raw) if wlogout_icon_name_raw is not None else "system-log-out-symbolic"
        self.wlogout_button = HoverButton(
            image=FabricImage(icon_name=wlogout_icon_name, icon_size=16),
            tooltip_text="Power Menu",
            v_align=Gtk.Align.END,
            on_clicked=_handle_wlogout_click,
        )
        self.wlogout_button.get_style_context().add_class("quickaction-button")
        self.wlogout_button.set_halign(Gtk.Align.END)

        ss_tooltip = str(self.screenshot_action_config.get("tooltip", "Take Screenshot"))
        ss_icon_raw = icons.get("ui", {}).get("camera", "camera-photo-symbolic")
        ss_icon = str(ss_icon_raw) if ss_icon_raw is not None else "camera-photo-symbolic"
        self.screenshot_button = HoverButton(
            image=FabricImage(icon_name=ss_icon, icon_size=16),
            tooltip_text=ss_tooltip,
            v_align="center",
            on_clicked=_handle_screenshot_click,
        )
        self.screenshot_button.get_style_context().add_class("quickaction-button")

        initial_sr_tooltip = str(self.screenrecord_action_config.get("start_tooltip", "Start Recording"))
        sr_icon_raw = icons.get("ui", {}).get("camera-video", "video-display-symbolic")
        sr_icon = str(sr_icon_raw) if sr_icon_raw is not None else "video-display-symbolic"
        self.screen_record_button = HoverButton(
            image=FabricImage(icon_name=sr_icon, icon_size=16),
            tooltip_text=initial_sr_tooltip,
            v_align="center",
            on_clicked=_handle_screen_record_click,
        )
        self.screen_record_button.get_style_context().add_class("quickaction-button")

        bottom_action_buttons_hbox = Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0, h_align=Gtk.Align.CENTER)
        bottom_action_buttons_hbox.add(self.screenshot_button)
        bottom_action_buttons_hbox.add(self.screen_record_button)

        action_buttons_master_vbox = Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, v_align=Gtk.Align.CENTER)
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

        if "volume" in configured_sliders and self.audio_submenu:
            sliders_box_children_content.append(self.audio_submenu)
        if "microphone" in configured_sliders and self.mic_submenu:
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
            col_attach = 1 if added_sliders_box else 0
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

        if self.recorder_service:
            self._screen_recorder_signal_id = self.recorder_service.connect("recording", self._update_screen_record_button_state)
            GLib.idle_add(self._update_screen_record_button_state, self.recorder_service, self.recorder_service.is_recording)

        self._uptime_update_callback_ref = lambda _s, val: self.uptime_value_label.set_label(val.get("uptime", "N/A"))
        if util_fabricator:
            self._uptime_signal_handler_id = util_fabricator.connect("changed", self._uptime_update_callback_ref)

    def _update_screen_record_button_state(self, _service: ScreenRecorder, is_recording: bool):
        if not (
            hasattr(self, "screen_record_button")
            and self.screen_record_button
            and isinstance(self.screen_record_button, Gtk.Widget)
            and self.screen_record_button.get_realized()
        ):
            logger.debug("[QuickSettingsMenu] screen_record_button not valid/realized for state update, skipping.")
            return GLib.SOURCE_REMOVE

        actual_image_widget = None
        if hasattr(self.screen_record_button, "get_image") and callable(self.screen_record_button.get_image):
            actual_image_widget = self.screen_record_button.get_image()
        elif hasattr(self.screen_record_button, "image_widget"):
            actual_image_widget = self.screen_record_button.image_widget
        elif hasattr(self.screen_record_button, "image") and isinstance(self.screen_record_button.image, (Gtk.Image, FabricImage)):
            actual_image_widget = self.screen_record_button.image

        if not (
            actual_image_widget
            and hasattr(actual_image_widget, "set_from_icon_name")
            and isinstance(actual_image_widget, Gtk.Widget)
            and actual_image_widget.get_realized()
        ):
            logger.debug("[QuickSettingsMenu] actual_image_widget for screen_record_button not valid/realized, skipping update.")
            return GLib.SOURCE_REMOVE

        tooltip_text = ""
        icon_name = ""

        if is_recording:
            icon_name_raw = self.screenrecord_action_config.get(
                "menu_icon_active", icons.get("custom", {}).get("recording_stop", "media-record-symbolic")
            )
            icon_name = str(icon_name_raw) if icon_name_raw is not None else "media-record-symbolic"
            tooltip_text = str(self.screenrecord_action_config.get("stop_tooltip", "Stop Recording"))
        else:
            icon_name_raw = self.screenrecord_action_config.get(
                "menu_icon_idle", icons.get("ui", {}).get("camera-video", "video-display-symbolic")
            )
            icon_name = str(icon_name_raw) if icon_name_raw is not None else "video-display-symbolic"
            tooltip_text = str(self.screenrecord_action_config.get("start_tooltip", "Start Recording"))

        actual_image_widget.set_from_icon_name(icon_name, 16)
        if hasattr(self.screen_record_button, "set_tooltip_text"):
            self.screen_record_button.set_tooltip_text(tooltip_text)

        return GLib.SOURCE_REMOVE

    def destroy(self):
        logger.debug(f"QuickSettingsMenu ({self.get_name()}): Destroying.")
        if (
            self._uptime_signal_handler_id is not None
            and util_fabricator
            and hasattr(util_fabricator, "handler_is_connected")
            and util_fabricator.handler_is_connected(self._uptime_signal_handler_id)
        ):
            util_fabricator.disconnect(self._uptime_signal_handler_id)
            self._uptime_signal_handler_id = None

        if hasattr(self, "recorder_service") and self.recorder_service and self._screen_recorder_signal_id is not None:
            if hasattr(self.recorder_service, "handler_is_connected") and self.recorder_service.handler_is_connected(
                self._screen_recorder_signal_id
            ):
                with contextlib.suppress(Exception):
                    self.recorder_service.disconnect(self._screen_recorder_signal_id)
            self._screen_recorder_signal_id = None

        if (
            hasattr(self, "quick_settings_button_box_instance")
            and self.quick_settings_button_box_instance
            and hasattr(self.quick_settings_button_box_instance, "destroy")
        ):
            self.quick_settings_button_box_instance.destroy()
            self.quick_settings_button_box_instance = None

        if hasattr(self, "audio_submenu") and self.audio_submenu and hasattr(self.audio_submenu, "destroy"):
            self.audio_submenu.destroy()
            self.audio_submenu = None
        if hasattr(self, "mic_submenu") and self.mic_submenu and hasattr(self.mic_submenu, "destroy"):
            self.mic_submenu.destroy()
            self.mic_submenu = None

        super().destroy()
        logger.debug(f"QuickSettingsMenu ({self.get_name()}): Destroyed.")


class QuickSettingsButtonWidget(ButtonWidget):
    """A button to display icons and open the menu."""

    def __init__(self, widget_config: BarConfig, **kwargs):
        qs_menu_structure_config_raw = widget_config.get("quick_settings", {})
        qs_menu_structure_config: Dict[str, Any] = qs_menu_structure_config_raw if isinstance(qs_menu_structure_config_raw, dict) else {}

        super().__init__(qs_menu_structure_config, name=widget_config.get("name", "quick_settings_bar_button"), **kwargs)

        self.quick_settings_menu_content_config: Dict[str, Any] = qs_menu_structure_config

        screenshot_action_config_raw = widget_config.get("screen_shot", {})
        self.screenshot_action_config: Dict[str, Any] = (
            screenshot_action_config_raw if isinstance(screenshot_action_config_raw, dict) else {}
        )

        screenrecord_action_config_raw = widget_config.get("screen_record", {})
        self.screenrecord_action_config: Dict[str, Any] = (
            screenrecord_action_config_raw if isinstance(screenrecord_action_config_raw, dict) else {}
        )

        self.panel_icon_size = int(self.quick_settings_menu_content_config.get("panel_icon_size", 16))

        from services import audio_service, bluetooth_service, network_service

        self.recorder_service = ScreenRecorder()
        self._screen_recorder_bar_signal_id: Union[int, None] = None
        self.audio = audio_service
        self.network = network_service
        self.bluetooth_service = bluetooth_service

        self.network_icon = FabricImage(style_classes=["panel-icon"], visible=True)
        self.audio_icon = FabricImage(style_classes=["panel-icon"], visible=True)
        self.bluetooth_icon = FabricImage(style_classes=["panel-icon"], visible=True)

        lottie_path_config = str(self.screenrecord_action_config.get("bar_lottie_path", "../../assets/icons/lottie/recording.json"))
        lottie_scale_config = float(self.screenrecord_action_config.get("bar_lottie_scale", 0.3))
        actual_lottie_file_path = ""

        self._raw_recording_indicator_widget: Union[LottieAnimationWidget, FabricImage]

        try:
            actual_lottie_file_path = lottie_path_config
            if not os.path.isabs(lottie_path_config) and (".." in lottie_path_config or not lottie_path_config.startswith("/")):
                base_path_guess = os.path.dirname(os.path.abspath(__file__))
                actual_lottie_file_path = os.path.abspath(os.path.join(base_path_guess, lottie_path_config))
            if not os.path.exists(actual_lottie_file_path):
                actual_lottie_file_path = get_relative_path(lottie_path_config)
                if not os.path.exists(actual_lottie_file_path):
                    raise FileNotFoundError(f"Lottie file not found at {lottie_path_config} or resolved paths {actual_lottie_file_path}")
            self._raw_recording_indicator_widget = LottieAnimationWidget(
                LottieAnimation.from_file(actual_lottie_file_path), scale=lottie_scale_config, visible=False
            )
        except Exception as e:
            logger.debug(
                f"[QSButtonWidget] Lottie load FAILED (path: '{lottie_path_config}', resolved: '{actual_lottie_file_path}'): {e}. Using static icon fallback."
            )
            fallback_icon_name_raw = self.screenrecord_action_config.get(
                "bar_icon_active", icons.get("custom", {}).get("recording_active_bar", "media-record-symbolic")
            )
            fallback_icon_name = str(fallback_icon_name_raw) if fallback_icon_name_raw is not None else "media-record-symbolic"
            self._raw_recording_indicator_widget = FabricImage(
                icon_name=fallback_icon_name,
                icon_size=self.panel_icon_size,
                style_classes=["panel-icon", "recording-indicator", "recording-indicator-active"],
                visible=False,
            )

        self.recording_indicator_event_box = Gtk.EventBox()
        self.recording_indicator_event_box.set_visible_window(False)
        self.recording_indicator_event_box.add(self._raw_recording_indicator_widget)

        self._indicator_interaction_in_progress = False
        self.recording_indicator_event_box.connect("button-press-event", self._on_recording_indicator_press)
        self.recording_indicator_event_box.connect("button-release-event", self._on_recording_indicator_release)

        self.recording_indicator_event_box.set_sensitive(False)
        self._raw_recording_indicator_widget.connect(
            "notify::visible", lambda obj, pspec: self.recording_indicator_event_box.set_visible(obj.get_visible())
        )
        self.recording_indicator_event_box.set_tooltip_text("Stop Recording (when active)")

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
        self.icon_container.add(self.recording_indicator_event_box)

        if hasattr(self, "set_child") and callable(self.set_child):
            self.set_child(self.icon_container)
        elif isinstance(self, Gtk.Button) and not self.get_label():
            self.set_image(self.icon_container)
            self.set_always_show_image(True)

        self.connect("clicked", self._on_main_button_clicked_for_popover)
        self.popup: Union[Popover, None] = None
        self._popover_closed_handler_id: Union[int, None] = None

        self.connect("destroy", self._on_destroy)

    def _on_recording_indicator_press(self, event_box: Gtk.EventBox, event: Gdk.EventButton) -> bool:
        if event.button == Gdk.BUTTON_PRIMARY and self.recorder_service and self.recorder_service.is_recording:
            self._indicator_interaction_in_progress = True
            return True
        return False

    def _on_recording_indicator_release(self, event_box: Gtk.EventBox, event: Gdk.EventButton) -> bool:
        should_consume_event = False
        if self._indicator_interaction_in_progress and event.button == Gdk.BUTTON_PRIMARY:
            allocation = event_box.get_allocation()
            is_click_inside = 0 <= event.x < allocation.width and 0 <= event.y < allocation.height

            if is_click_inside and self.recorder_service and self.recorder_service.is_recording:
                self.recorder_service.screenrecord_stop()
                should_consume_event = True

        self._indicator_interaction_in_progress = False
        return should_consume_event

    def _on_recording_state_changed_bar(self, _service: ScreenRecorder, is_recording: bool):
        if is_recording:
            self._raw_recording_indicator_widget.show()
            if hasattr(self._raw_recording_indicator_widget, "play_loop"):
                self._raw_recording_indicator_widget.play_loop()
            self.recording_indicator_event_box.set_sensitive(True)
            self.recording_indicator_event_box.set_tooltip_text("Stop Recording")
        else:
            if hasattr(self._raw_recording_indicator_widget, "stop_play"):
                self._raw_recording_indicator_widget.stop_play()
            self._raw_recording_indicator_widget.hide()
            self.recording_indicator_event_box.set_sensitive(False)
            self.recording_indicator_event_box.set_tooltip_text("")
            self._indicator_interaction_in_progress = False
        return GLib.SOURCE_REMOVE

    def _on_popover_externally_closed(self, popover_instance: Popover):
        logger.debug(f"[QSButtonWidget] Popover '{popover_instance}' reported closed by its own signal.")
        if self.popup is popover_instance:
            if self._popover_closed_handler_id is not None:
                is_connected = False
                if hasattr(self.popup, "handler_is_connected") and callable(self.popup.handler_is_connected):
                    with contextlib.suppress(TypeError, ValueError):
                        is_connected = self.popup.handler_is_connected(self._popover_closed_handler_id)

                if is_connected:
                    with contextlib.suppress(Exception):
                        if hasattr(self.popup, "disconnect_signal_by_id"):
                            self.popup.disconnect_signal_by_id(self._popover_closed_handler_id)
                        elif hasattr(self.popup, "disconnect"):
                            self.popup.disconnect(self._popover_closed_handler_id)
                self._popover_closed_handler_id = None
            self.popup = None
            logger.debug("[QSButtonWidget] self.popup reference nullified by _on_popover_externally_closed.")

    def _on_main_button_clicked_for_popover(self, main_button_widget: Gtk.Widget):
        if self._indicator_interaction_in_progress:
            logger.debug("[QSButtonWidget] Main button click for popover ignored: indicator interaction was in progress.")
            return True

        if self.popup is None:
            logger.info("[QSButtonWidget] Popover is None, creating new instance.")
            try:

                def _content_factory():
                    return QuickSettingsMenu(
                        config=self.quick_settings_menu_content_config,
                        screenshot_action_config=self.screenshot_action_config,
                        screenrecord_action_config=self.screenrecord_action_config,
                    )

                self.popup = Popover(content_factory=_content_factory, point_to=self)
                logger.info(f"[QSButtonWidget] Popover instance created: {self.popup}")

                try:
                    self._popover_closed_handler_id = self.popup.connect("popover-closed", self._on_popover_externally_closed)
                    logger.info(f"[QSButtonWidget] Successfully connected 'popover-closed' to {self.popup}")
                except (TypeError, GObject.GErrorException) as e_connect:
                    logger.error(
                        f"[QSButtonWidget] Failed to connect 'popover-closed' signal on {self.popup}. Error: {e_connect}", exc_info=True
                    )
                    self._popover_closed_handler_id = None

                if hasattr(self.popup, "open"):
                    self.popup.open()
                    GLib.timeout_add(100, self._check_popover_visibility, "newly created - open")
                else:
                    logger.error(f"[QSButtonWidget] Newly created Popover {self.popup} has no open() method.")
                    if hasattr(self.popup, "destroy"):
                        self.popup.destroy()
                    self.popup = None

            except Exception as e:
                logger.error(f"[QSButtonWidget] Error creating/opening Popover instance: {e}", exc_info=True)
                if self.popup and hasattr(self.popup, "destroy"):
                    self.popup.destroy()
                self.popup = None

        else:
            try:
                if not (hasattr(self.popup, "get_visible") and hasattr(self.popup, "open") and hasattr(self.popup, "close")):
                    logger.error(f"[QSButtonWidget] Existing Popover {self.popup} lacks required methods. Destroying and nullifying.")
                    if hasattr(self.popup, "destroy"):
                        self.popup.destroy()
                    self.popup = None
                    return True

                if self.popup.get_visible():
                    logger.info(f"[QSButtonWidget] Popover is visible. Attempting to close {self.popup}.")
                    self.popup.close()
                else:
                    logger.info(f"[QSButtonWidget] Popover is not visible. Attempting to open {self.popup}.")
                    self.popup.open()
                    GLib.timeout_add(100, self._check_popover_visibility, "existing - open")

            except Exception as e:
                logger.error(f"[QSButtonWidget] Error during popover toggle (existing instance): {e}", exc_info=True)
                if self.popup and hasattr(self.popup, "destroy"):
                    with contextlib.suppress(Exception):
                        self.popup.destroy()
                self.popup = None

        return True

    def _check_popover_visibility(self, origin: str):
        if self.popup:
            is_visible_after = False
            if hasattr(self.popup, "get_visible"):
                is_visible_after = self.popup.get_visible()
            elif isinstance(self.popup, Gtk.Popover):
                is_visible_after = self.popup.is_visible()
            logger.info(f"[QSButtonWidget] Popover visibility check (from {origin}) after timeout: {is_visible_after}")
            if not is_visible_after and "open" in origin.lower():
                logger.warning(f"[QSButtonWidget] Popover failed to become visible after {origin} call.")
        else:
            logger.info(f"[QSButtonWidget] Popover visibility check (from {origin}): self.popup is None.")
        return GLib.SOURCE_REMOVE

    def _connect_bluetooth_device_signals(self):
        if not self.bluetooth_service or not hasattr(self.bluetooth_service, "find_property"):
            return
        with contextlib.suppress(Exception):
            if self.bluetooth_service.find_property("connected-devices"):
                self._bt_connected_handler_id = self.bluetooth_service.connect(
                    "notify::connected-devices", self._on_bluetooth_property_changed_cb
                )
            if self.bluetooth_service.find_property("devices"):
                self._bt_devices_handler_id = self.bluetooth_service.connect("notify::devices", self._on_bluetooth_property_changed_cb)

    def _on_network_property_changed_cb(self, _obj: Any, _pspec: Any):
        GLib.idle_add(self.update_network_icon)
        return GLib.SOURCE_REMOVE

    def _on_network_device_ready_cb(self, client: Any, *_extra_args: Any):
        GLib.idle_add(self.on_network_device_ready, client)
        return GLib.SOURCE_REMOVE

    def _speaker_property_changed_cb(self, obj: GObject.Object, pspec: GObject.ParamSpec):
        GLib.idle_add(self.update_volume)
        return True

    def _on_speaker_changed_cb(self, _obj: Any, _pspec: Any):
        GLib.idle_add(self.on_speaker_changed)
        return GLib.SOURCE_REMOVE

    def _on_bluetooth_property_changed_cb(self, _obj: Any, _pspec: Any):
        GLib.idle_add(self.update_bluetooth_icon)
        return GLib.SOURCE_REMOVE

    def update_network_icon(self, *_args: Any):
        final_icon_name_raw = icons.get("network-offline-symbolic", "network-offline-symbolic")
        final_icon_name = str(final_icon_name_raw) if final_icon_name_raw is not None else "network-offline-symbolic"

        if self.network:
            prim_device_type = getattr(self.network, "primary_device", None)
            if prim_device_type == "wifi":
                wifi_device = getattr(self.network, "wifi_device", None)
                icon_candidate = None
                if wifi_device and hasattr(wifi_device, "icon_name") and callable(wifi_device.icon_name):
                    icon_candidate = wifi_device.icon_name()
                elif wifi_device and hasattr(wifi_device, "get_property"):
                    with contextlib.suppress(Exception):
                        icon_candidate = wifi_device.get_property("icon-name")

                if isinstance(icon_candidate, str) and icon_candidate:
                    final_icon_name = icon_candidate
                else:
                    fallback_raw = icons.get("network", {}).get("wifi", {}).get("disabled", "network-wireless-offline-symbolic")
                    final_icon_name = str(fallback_raw) if fallback_raw is not None else "network-wireless-offline-symbolic"

            elif prim_device_type == "wired":
                eth_device = getattr(self.network, "ethernet_device", None)
                icon_candidate = None
                if eth_device and hasattr(eth_device, "get_property"):
                    with contextlib.suppress(Exception):
                        reported_icon = eth_device.get_property("icon-name")
                        if reported_icon and "unknown" not in str(reported_icon).lower():
                            icon_candidate = str(reported_icon)

                if isinstance(icon_candidate, str) and icon_candidate:
                    final_icon_name = icon_candidate
                else:
                    fallback_raw = icons.get("network", {}).get("wired-symbolic", "network-wired-symbolic")
                    final_icon_name = str(fallback_raw) if fallback_raw is not None else "network-wired-symbolic"
            else:
                fallback_raw = icons.get("network", {}).get("wired-no-route-symbolic", "network-offline-symbolic")
                final_icon_name = str(fallback_raw) if fallback_raw is not None else "network-offline-symbolic"

        self.network_icon.set_from_icon_name(final_icon_name, self.panel_icon_size)
        return GLib.SOURCE_REMOVE

    def _is_network_connected(self, _prim: Any, _wi: Any, _eth: Any) -> bool:
        try:
            if self.network and hasattr(self.network, "connectivity"):
                nm_connectivity_full = 4
                if self.network.connectivity == nm_connectivity_full:
                    return True
            active_conn = getattr(self.network, "primary_connection", getattr(self.network, "active_connection", None))
            if active_conn and hasattr(active_conn, "state"):
                nm_active_connection_state_activated = 2
                return active_conn.state == nm_active_connection_state_activated
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
                with contextlib.suppress(Exception):
                    obj_with_signal.disconnect(handler_id)
        self._network_prop_handler_ids.clear()

    def on_network_device_ready(self, client: Any):
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
                        with contextlib.suppress(TypeError):
                            handler_id = device.connect(f"notify::{prop_name}", self._on_network_property_changed_cb)
                            self._network_prop_handler_ids.append((device, handler_id))
        GLib.idle_add(self.update_network_icon)
        return GLib.SOURCE_REMOVE

    def on_speaker_changed(self, *_args: Any):
        if self._conn_spk_inst:
            self._speaker_vol_h = self._disconnect_handler_id_safe(self._conn_spk_inst, self._speaker_vol_h)
            self._speaker_mut_h = self._disconnect_handler_id_safe(self._conn_spk_inst, self._speaker_mut_h)
        self._conn_spk_inst = None

        if self.audio and self.audio.speaker and hasattr(self.audio.speaker, "connect"):
            self._conn_spk_inst = self.audio.speaker
            speaker_obj = self._conn_spk_inst

            if hasattr(speaker_obj, "find_property") and speaker_obj.find_property("volume"):
                self._speaker_vol_h = speaker_obj.connect("notify::volume", self._speaker_property_changed_cb)

            mute_prop_name = None
            if hasattr(speaker_obj, "find_property"):
                if speaker_obj.find_property("is-muted"):
                    mute_prop_name = "is-muted"
                elif speaker_obj.find_property("muted"):
                    mute_prop_name = "muted"

            if mute_prop_name:
                self._speaker_mut_h = speaker_obj.connect(f"notify::{mute_prop_name}", self._speaker_property_changed_cb)

            GLib.idle_add(self.update_volume)
        else:
            GLib.idle_add(self.update_volume)
        return GLib.SOURCE_REMOVE

    def update_volume(self, *_args: Any):
        from utils.widget_utils import get_audio_icon_name

        key_raw = icons.get("audio", {}).get("volume", {}).get("muted", "audio-volume-muted-symbolic")
        key = str(key_raw) if key_raw is not None else "audio-volume-muted-symbolic"
        calc_vol = 0
        is_muted = True
        if self.audio and self.audio.speaker:
            spk = self.audio.speaker
            if hasattr(spk, "volume"):
                calc_vol = round(float(spk.volume))
            mute_val = getattr(spk, "is_muted", getattr(spk, "muted", True))
            is_muted = bool(mute_val)
            info = get_audio_icon_name(calc_vol, is_muted)
            if info and "icon" in info and isinstance(info["icon"], str):
                key = info["icon"]
        else:
            info = get_audio_icon_name(0, True)
            if info and "icon" in info and isinstance(info["icon"], str):
                key = info["icon"]
            else:
                fallback_raw = icons.get("audio", {}).get("volume", {}).get("muted-fallback", "audio-volume-muted-symbolic")
                key = str(fallback_raw) if fallback_raw is not None else "audio-volume-muted-symbolic"

        self.audio_icon.set_from_icon_name(key, self.panel_icon_size)
        return GLib.SOURCE_REMOVE

    def update_bluetooth_icon(self, *_args: Any):
        name_raw = icons.get("bluetooth", {}).get("disabled-symbolic", "bluetooth-disabled-symbolic")
        name = str(name_raw) if name_raw is not None else "bluetooth-disabled-symbolic"

        if self.bluetooth_service and getattr(self.bluetooth_service, "enabled", False):
            active_raw = icons.get("bluetooth", {}).get("active-symbolic", "bluetooth-active-symbolic")
            name = str(active_raw) if active_raw is not None else "bluetooth-active-symbolic"
            conn_dev = getattr(self.bluetooth_service, "connected_devices", [])
            if isinstance(conn_dev, (list, tuple)) and len(conn_dev) > 0:
                connected_raw = icons.get("bluetooth", {}).get("connected-symbolic", name)
                name = str(connected_raw) if connected_raw is not None else name
        self.bluetooth_icon.set_from_icon_name(name, self.panel_icon_size)
        return GLib.SOURCE_REMOVE

    def _disconnect_handler_id_safe(self, obj: Any, handler_id: Union[int, None]) -> None:
        if obj and handler_id is not None and hasattr(obj, "handler_is_connected") and obj.handler_is_connected(handler_id):
            with contextlib.suppress(Exception):
                obj.disconnect(handler_id)
        return None

    def _on_destroy(self, *args):
        logger.debug(f"QuickSettingsButtonWidget ({self.get_name()}): Destroying.")

        raw_widget = getattr(self, "_raw_recording_indicator_widget", None)
        if (
            raw_widget is not None
            and hasattr(raw_widget, "stop_play")
            and hasattr(raw_widget, "get_visible")
            and callable(raw_widget.get_visible)
            and raw_widget.get_visible()
        ):
            with contextlib.suppress(Exception):
                raw_widget.stop_play()

        if self.popup:
            if self._popover_closed_handler_id is not None:
                is_connected = False
                if hasattr(self.popup, "handler_is_connected") and callable(self.popup.handler_is_connected):
                    with contextlib.suppress(TypeError, ValueError):
                        is_connected = self.popup.handler_is_connected(self._popover_closed_handler_id)

                if is_connected:
                    with contextlib.suppress(Exception):
                        if hasattr(self.popup, "disconnect_signal_by_id"):
                            self.popup.disconnect_signal_by_id(self._popover_closed_handler_id)
                        elif hasattr(self.popup, "disconnect"):
                            self.popup.disconnect(self._popover_closed_handler_id)
                self._popover_closed_handler_id = None

            if hasattr(self.popup, "destroy"):
                with contextlib.suppress(Exception):
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
                with contextlib.suppress(Exception):
                    self.recorder_service.disconnect(self._screen_recorder_bar_signal_id)
            self._screen_recorder_bar_signal_id = None

        super().destroy()
        logger.debug(f"QuickSettingsButtonWidget ({self.get_name()}): Destroyed.")
