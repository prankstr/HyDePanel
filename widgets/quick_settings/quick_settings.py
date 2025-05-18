# widgets/quick_settings/quick_settings.py

import os
import weakref
from typing import Any, Callable, Dict, List, Tuple, Type, Union, Optional

import gi
from fabric.utils import get_relative_path
from fabric.widgets.box import Box
from fabric.widgets.centerbox import CenterBox
from fabric.widgets.image import Image as FabricImage
from fabric.widgets.label import Label as FabricLabel
from gi.repository import GLib, Gtk, Gdk, GObject, Pango  # Added GObject, Pango
from loguru import logger

import utils.functions as helpers
from services import MprisPlayerManager
from services import audio_service
from services.screen_record import ScreenRecorder

# Assuming Popover is now correctly imported from the modified shared.pop_over
from shared.pop_over import Popover
from shared import ButtonWidget, CircleImage, HoverButton, QSChevronButton, LottieAnimation, LottieAnimationWidget

# from shared.buttons import ScanButton # Imported in submenus directly
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

# IMPORTANT: These submenus should import *your modified versions*
# that include the robustness checks (visible/realized) and proper destroy methods.
from .submenu.audiosink import AudioSinkSubMenu
from .submenu.bluetooth import BluetoothSubMenu, BluetoothToggle
from .submenu.ha_lights import HALightsSubMenu, HALightsToggle
from .submenu.mic import MicroPhoneSubMenu
from .submenu.power import PowerProfileSubMenu, PowerProfileToggle
from .submenu.wifi import WifiSubMenu, WifiToggle  # YOU MUST MODIFY WifiSubMenu.py

from .togglers import (
    HyprIdleQuickSetting,
    HyprSunsetQuickSetting,
    NotificationQuickSetting,
)

gi.require_version("Gtk", "3.0")


class QuickSettingsButtonBox(Box):
    def __init__(self, config: Dict[str, Any], **kwargs):
        logger.info(f"INIT: {self.__class__.__name__}")
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
        self.active_submenu: Optional[QuickSubMenu] = None
        self.all_created_submenus: List[QuickSubMenu] = []
        self.toggler_registry: Dict[str, Tuple[Type[Gtk.Widget], Optional[Callable[[], Optional[QuickSubMenu]]]]] = {
            "wifi": (WifiToggle, lambda: WifiSubMenu()),  # WifiSubMenu needs robustness
            "bluetooth": (BluetoothToggle, lambda: BluetoothSubMenu()),  # BluetoothSubMenu needs robustness if it has ScrolledWindow/Scale
            "home_assistant_lights": (HALightsToggle, lambda: HALightsSubMenu()),
            "power_profiles": (PowerProfileToggle, lambda: PowerProfileSubMenu()),
            "hypridle": (HyprIdleQuickSetting, None),
            "hyprsunset": (HyprSunsetQuickSetting, None),
            "notifications": (NotificationQuickSetting, None),
        }
        toggler_definitions = config.get("togglers", [])
        max_cols = config.get("togglers_max_cols", 2)
        self._populate_togglers(toggler_definitions, max_cols)
        logger.info(f"{self.__class__.__name__}: Adding {len(self.all_created_submenus)} submenus to layout.")
        for submenu_widget in self.all_created_submenus:  # Add all created submenus
            if submenu_widget and isinstance(submenu_widget, Gtk.Widget):
                self.add(submenu_widget)

    def _populate_togglers(self, toggler_definitions, max_cols):  # Original logic
        col, row = 0, 0
        if not toggler_definitions:
            return
        for item_config in toggler_definitions:
            toggler_type = item_config if isinstance(item_config, str) else item_config.get("type")
            if not toggler_type or toggler_type not in self.toggler_registry:
                continue
            widget_class, submenu_factory = self.toggler_registry[toggler_type]
            instance = None
            try:
                if submenu_factory:
                    submenu_instance = submenu_factory()
                    if submenu_instance and not isinstance(submenu_instance, QuickSubMenu):
                        continue
                    instance = widget_class(submenu=submenu_instance) if submenu_instance else widget_class()
                    if submenu_instance:
                        self.all_created_submenus.append(submenu_instance)
                    if isinstance(instance, QSChevronButton):
                        instance.connect("reveal-clicked", self.set_active_submenu)
                else:
                    instance = widget_class()
            except Exception as e:
                logger.error(f"Failed toggler '{toggler_type}': {e}", exc_info=True)
                continue
            if instance:
                self.grid.attach(instance, col, row, 1, 1)
                col = (col + 1) % max_cols
                row += 1 if col == 0 else 0

    def set_active_submenu(self, clicked_button: QSChevronButton):  # Original logic
        target_submenu = getattr(clicked_button, "submenu", None)
        # ... (rest of your original set_active_submenu logic) ...
        if not target_submenu:
            if self.active_submenu:
                self.active_submenu.do_reveal(False)
            for btn in self.grid.get_children():
                if isinstance(btn, QSChevronButton) and getattr(btn, "submenu", None) == self.active_submenu and hasattr(btn, "set_active"):
                    btn.set_active(False)
                    break
            self.active_submenu = None
            return
        prev_active = self.active_submenu
        if prev_active and prev_active != target_submenu:
            prev_active.do_reveal(False)
            for btn in self.grid.get_children():
                if isinstance(btn, QSChevronButton) and getattr(btn, "submenu", None) == prev_active and hasattr(btn, "set_active"):
                    btn.set_active(False)
                    break
        self.active_submenu = target_submenu
        if not hasattr(self.active_submenu, "toggle_reveal"):
            self.active_submenu = None
            clicked_button.set_active(False)
            return
        revealed = self.active_submenu.toggle_reveal()
        if hasattr(clicked_button, "set_active"):
            clicked_button.set_active(revealed)
        if not revealed:
            self.active_submenu = None

    def destroy(self):  # Original logic with enhanced logging/safety
        logger.info(f"DESTROY: {self.__class__.__name__}")
        for i in range(len(self.all_created_submenus) - 1, -1, -1):  # Iterate backwards
            submenu = self.all_created_submenus.pop(i)
            if submenu and hasattr(submenu, "destroy"):
                submenu.destroy()
            elif submenu and isinstance(submenu, Gtk.Widget):
                submenu.destroy()  # Fallback
        for child in self.grid.get_children():  # Disconnect signals
            if isinstance(child, QSChevronButton):
                try:
                    GLib.signal_handlers_disconnect_by_func(child, self.set_active_submenu)
                except:
                    pass
        super().destroy()


class QuickSettingsMenu(Box):
    def __init__(self, config, screenshot_action_config, screenrecord_action_config, **kwargs):
        logger.info(f"INIT: {self.__class__.__name__}")
        super().__init__(name="quicksettings-menu", orientation=Gtk.Orientation.VERTICAL, all_visible=True, **kwargs)
        self.config = config
        self.screenshot_action_config = screenshot_action_config
        self.screenrecord_action_config = screenrecord_action_config
        self._uptime_signal_handler_id = None
        self.recorder_service = ScreenRecorder()
        self._screen_recorder_signal_id = None
        self.popover_instance_ref: Optional[weakref.ReferenceType[Popover]] = None

        def _hide_parent_popover_internal():
            logger.debug(f"QSMenu: _hide_parent_popover_internal called.")
            actual_popover = self.popover_instance_ref() if self.popover_instance_ref else None
            if actual_popover and hasattr(actual_popover, "hide_popover"):
                logger.info(f"QSMenu: Calling hide_popover() on stored Popover: {actual_popover}")
                actual_popover.hide_popover()
            else:
                logger.warning(f"QSMenu: No valid Popover ref to hide. Ref: {self.popover_instance_ref}")

        def _handle_screenshot_click(_btn):
            _hide_parent_popover_internal()
            self.recorder_service.screenshot(
                path=str(self.screenshot_action_config.get("path", "Pictures/Screenshots")),
                fullscreen=self.screenshot_action_config.get("fullscreen", False),
                save_copy=self.screenshot_action_config.get("save_copy", True),
            )

        def _handle_screen_record_click(_btn):
            path = str(self.screenrecord_action_config.get("path", "Videos/Screencasts"))
            allow_audio = self.screenrecord_action_config.get("allow_audio", True)
            fullscreen = self.screenrecord_action_config.get("fullscreen", False)
            logger.info(f"QSMenu: Record Click. IsRecording: {self.recorder_service.is_recording}. AllowAudio: {allow_audio}")
            if self.recorder_service.is_recording:
                self.recorder_service.screenrecord_stop()
            else:
                _hide_parent_popover_internal()
                self.recorder_service.screenrecord_start(path=path, allow_audio=allow_audio, fullscreen=fullscreen)

        def _handle_wlogout_click(_btn):
            _hide_parent_popover_internal()
            helpers.exec_shell_command_async("wlogout", lambda *_: None)

        user_cfg = self.config.get("user", {})
        user_img_path = str(user_cfg.get("avatar", "~/.face"))
        user_img_file = os.path.expanduser(user_img_path)
        default_banner = str(get_relative_path("../../assets/images/banner.jpg"))
        user_image = default_banner if not os.path.exists(user_img_file) else user_img_file
        username_setting = user_cfg.get("name", "system")
        username_val = GLib.get_user_name() if username_setting == "system" or username_setting is None else str(username_setting)
        if user_cfg.get("distro_icon", False):
            username_val = f"{str(helpers.get_distro_icon() if callable(helpers.get_distro_icon) else '')} {username_val}"
        username_label = FabricLabel(label=username_val, v_align="center", h_align="start", style_classes=["user"])
        self.uptime_box = Box(orientation="h", spacing=10, h_align="start", v_align="center", style_classes=["uptime"])
        self.uptime_icon_label = FabricLabel(label="", style_classes=["icon"], v_align="center")
        self.uptime_value_label = FabricLabel(label=str(helpers.uptime() if callable(helpers.uptime) else "N/A"), v_align="center")
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
        wlogout_icon = str(icons.get("powermenu", {}).get("logout", "system-log-out-symbolic"))
        self.wlogout_button = HoverButton(
            image=FabricImage(icon_name=wlogout_icon, icon_size=16),
            tooltip_text="Power Menu",
            v_align=Gtk.Align.CENTER,
            on_clicked=_handle_wlogout_click,
        )
        self.wlogout_button.get_style_context().add_class("quickaction-button")
        self.wlogout_button.set_halign(Gtk.Align.END)
        ss_tooltip = str(self.screenshot_action_config.get("tooltip", "Take Screenshot"))
        ss_icon = str(icons.get("ui", {}).get("camera", "camera-photo-symbolic"))
        self.screenshot_button = HoverButton(
            image=FabricImage(icon_name=ss_icon, icon_size=16),
            tooltip_text=ss_tooltip,
            v_align="center",
            on_clicked=_handle_screenshot_click,
        )
        self.screenshot_button.get_style_context().add_class("quickaction-button")
        sr_start_tooltip = str(self.screenrecord_action_config.get("start_tooltip", "Start Recording"))
        sr_icon = str(icons.get("ui", {}).get("camera-video", "video-display-symbolic"))
        self.screen_record_button = HoverButton(
            image=FabricImage(icon_name=sr_icon, icon_size=16),
            tooltip_text=sr_start_tooltip,
            v_align="center",
            on_clicked=_handle_screen_record_click,
        )
        self.screen_record_button.get_style_context().add_class("quickaction-button")
        bottom_actions = Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, h_align=Gtk.Align.CENTER)
        bottom_actions.add(self.screenshot_button)
        bottom_actions.add(self.screen_record_button)
        actions_vbox = Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, v_align=Gtk.Align.END)
        actions_vbox.add(self.wlogout_button)
        actions_vbox.add(bottom_actions)
        self.user_box.pack_end(actions_vbox, False, False, 0)

        controls_cfg = self.config.get("controls", {})
        qobb_cfg = {
            "togglers": controls_cfg.get("togglers", []),
            "togglers_max_cols": controls_cfg.get("togglers_max_cols", 2),
            "togglers_grid_column_homogeneous": controls_cfg.get("togglers_grid_column_homogeneous", True),
            "togglers_grid_row_homogeneous": controls_cfg.get("togglers_grid_row_homogeneous", True),
        }
        self.quick_settings_button_box_instance = QuickSettingsButtonBox(config=qobb_cfg, hexpand=True, h_align="fill")

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
        logger.info(f"QSMenu: Instantiating AudioSinkSubMenu and MicroPhoneSubMenu (ensure these are your MODIFIED versions).")
        self.audio_submenu = AudioSinkSubMenu()
        self.mic_submenu = MicroPhoneSubMenu()
        sliders_box_children = [sliders_grid]
        configured_sliders = controls_cfg.get("sliders", [])
        slider_count = 0
        if configured_sliders:
            for name in configured_sliders:
                widget = None
                if name == "volume":
                    widget = AudioSlider()
                elif name == "microphone":
                    widget = MicrophoneSlider()
                elif name == "brightness":
                    widget = BrightnessSlider()
                elif name == "hyprsunset_intensity":
                    widget = HyprSunsetIntensitySlider()
                if widget:
                    sliders_grid.attach(widget, 0, slider_count, 1, 1)
                    slider_count += 1
        if "volume" in configured_sliders and self.audio_submenu:
            sliders_box_children.append(self.audio_submenu)
        if "microphone" in configured_sliders and self.mic_submenu:
            sliders_box_children.append(self.mic_submenu)

        shortcuts_cfg = self.config.get("shortcuts", {})
        slider_cls_name = "slider-box-long"
        s_widget = None
        if shortcuts_cfg and shortcuts_cfg.get("enabled", False) and shortcuts_cfg.get("items"):
            slider_cls_name = "slider-box-shorter" if len(shortcuts_cfg.get("items", [])) > 2 else "slider-box-short"
            s_widget = ShortcutsContainer(
                shortcuts_config=shortcuts_cfg["items"], style_classes=["shortcuts-grid"], v_align="start", h_align="fill"
            )
        sliders_container = Box(
            orientation="v",
            spacing=10,
            style_classes=[slider_cls_name],
            children=sliders_box_children if sliders_grid.get_children() or len(sliders_box_children) > 1 else [],
            h_expand=True,
            h_align="fill",
            vexpand=False,
        )
        center_main_grid = Gtk.Grid(visible=True, column_spacing=10, hexpand=True, column_homogeneous=False)
        if sliders_container.get_children():
            center_main_grid.attach(sliders_container, 0, 0, 2 if s_widget else 1, 1)
        if s_widget:
            center_main_grid.attach(s_widget, 2 if sliders_container.get_children() else 0, 0, 1, 1)

        start_section_cont = Box(
            orientation="v",
            spacing=10,
            style_classes=["section-box"],
            children=(self.user_box, self.quick_settings_button_box_instance),
            hexpand=True,
            h_align="fill",
        )
        start_section_cont.set_valign(Gtk.Align.START)
        center_section_cont = Box(
            orientation="v",
            style_classes=["section-box"],
            children=[center_main_grid] if center_main_grid.get_children() else [],
            hexpand=True,
            h_align="fill",
        )
        media_section_cont = None
        media_cfg_dict = self.config.get("media", {})
        if media_cfg_dict.get("enabled", False):
            media_section_cont = Box(
                orientation="v",
                spacing=10,
                style_classes=["section-box"],
                children=(PlayerBoxStack(MprisPlayerManager(), config=media_cfg_dict)),
                hexpand=True,
                h_align="fill",
            )

        main_layout_cont = CenterBox(
            orientation="v",
            style_classes=["quick-settings-box"],
            start_children=[start_section_cont] if start_section_cont.get_children() else None,
            center_children=[center_section_cont] if center_section_cont.get_children() else None,
            end_children=[media_section_cont] if media_section_cont else None,
        )
        self.add(main_layout_cont)
        self._screen_recorder_signal_id = self.recorder_service.connect("recording", self._update_screen_record_button_state)
        GLib.idle_add(self._update_screen_record_button_state, self.recorder_service, self.recorder_service.is_recording)
        self._uptime_cb_ref = lambda _s, val: self.uptime_value_label.set_label(str(val.get("uptime", "N/A")))
        if hasattr(util_fabricator, "connect") and callable(util_fabricator.connect):
            self._uptime_signal_handler_id = util_fabricator.connect("changed", self._uptime_cb_ref)

    def set_actual_popover_instance(self, popover_instance: Popover):
        logger.debug(f"QSMenu: Actual Popover instance set via callback: {popover_instance}")
        self.popover_instance_ref = weakref.ref(popover_instance)

    def _update_screen_record_button_state(self, _service, is_recording):  # Original logic with str casts
        if not hasattr(self, "screen_record_button") or not self.screen_record_button:
            return GLib.SOURCE_REMOVE
        img_widget = None
        btn = self.screen_record_button
        if hasattr(btn, "get_image") and callable(btn.get_image):
            img_widget = btn.get_image()
        elif hasattr(btn, "image_widget"):
            img_widget = btn.image_widget
        elif hasattr(btn, "image") and isinstance(btn.image, (Gtk.Image, FabricImage)):
            img_widget = btn.image
        if not img_widget or not hasattr(img_widget, "set_from_icon_name"):
            return GLib.SOURCE_REMOVE
        icon_key = "recording_stop" if is_recording else "camera-video"
        icon_cat = "custom" if is_recording else "ui"
        default_icon = "media-record-symbolic" if is_recording else "video-display-symbolic"
        icon = str(icons.get(icon_cat, {}).get(icon_key, default_icon))
        tooltip_key = "stop_tooltip" if is_recording else "start_tooltip"
        default_tooltip = "Stop" if is_recording else "Start"
        tooltip = str(self.screenrecord_action_config.get(tooltip_key, default_tooltip + " Recording"))
        img_widget.set_from_icon_name(icon, 16)
        btn.set_tooltip_text(tooltip)
        return GLib.SOURCE_REMOVE

    def destroy(self):  # Original logic with more robust cleanup
        logger.info(f"DESTROY: {self.__class__.__name__}")
        if (
            self._uptime_signal_handler_id
            and hasattr(util_fabricator, "handler_is_connected")
            and callable(getattr(util_fabricator, "disconnect", None))
        ):
            if util_fabricator.handler_is_connected(self._uptime_signal_handler_id):
                util_fabricator.disconnect(self._uptime_signal_handler_id)
        if (
            hasattr(self, "recorder_service")
            and self._screen_recorder_signal_id
            and hasattr(self.recorder_service, "handler_is_connected")
            and self.recorder_service.handler_is_connected(self._screen_recorder_signal_id)
        ):
            self.recorder_service.disconnect(self._screen_recorder_signal_id)

        # Destroy owned composite widgets
        if hasattr(self, "quick_settings_button_box_instance") and self.quick_settings_button_box_instance:
            self.quick_settings_button_box_instance.destroy()
        if hasattr(self, "audio_submenu") and self.audio_submenu and hasattr(self.audio_submenu, "destroy"):
            self.audio_submenu.destroy()
        if hasattr(self, "mic_submenu") and self.mic_submenu and hasattr(self.mic_submenu, "destroy"):
            self.mic_submenu.destroy()

        # Nullify references
        self._uptime_signal_handler_id = self._screen_recorder_signal_id = self.recorder_service = None
        self.quick_settings_button_box_instance = self.audio_submenu = self.mic_submenu = self.popover_instance_ref = None
        super().destroy()


class QuickSettingsButtonWidget(ButtonWidget):  # Original structure, with Lottie TypeError fix
    def __init__(self, widget_config: BarConfig, **kwargs):
        logger.info(f"INIT: {self.__class__.__name__}")
        qs_menu_cfg = widget_config.get("quick_settings", {})
        super().__init__(qs_menu_cfg, name=widget_config.get("name", "quick_settings_bar_button"), **kwargs)
        self.quick_settings_menu_content_config = qs_menu_cfg
        self.screenshot_action_config = widget_config.get("screen_shot", {})
        self.screenrecord_action_config = widget_config.get("screen_record", {})
        self.panel_icon_size = self.quick_settings_menu_content_config.get("panel_icon_size", 16)

        services_mod = __import__("services")  # To access services.network_service etc.
        self.audio = audio_service
        self.network = getattr(services_mod, "network_service", None)
        self.bluetooth_service = getattr(services_mod, "bluetooth_service", None)
        self.recorder_service = ScreenRecorder()
        self._screen_recorder_bar_signal_id = None

        self.network_icon = FabricImage(style_classes=["panel-icon"], visible=True)
        self.audio_icon = FabricImage(style_classes=["panel-icon"], visible=True)
        self.bluetooth_icon = FabricImage(style_classes=["panel-icon"], visible=True)
        lottie_path = self.screenrecord_action_config.get("bar_lottie_path", "../../assets/icons/lottie/recording.json")
        lottie_scale = self.screenrecord_action_config.get("bar_lottie_scale", 0.3)
        self.clickable_recording_indicator = None
        self._recording_lottie_animation_widget_actual = None
        try:
            actual_path = lottie_path
            if not os.path.isabs(lottie_path):
                script_dir_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), lottie_path))
                actual_path = script_dir_path if os.path.exists(script_dir_path) else get_relative_path(lottie_path)
            if not os.path.exists(actual_path):
                raise FileNotFoundError(f"Lottie missing: {lottie_path} -> {actual_path}")
            self._recording_lottie_animation_widget_actual = LottieAnimationWidget(
                LottieAnimation.from_file(actual_path), scale=lottie_scale, visible=True
            )
            eb = Gtk.EventBox(visible=False, sensitive=False)
            getattr(eb, "set_child", eb.add)(self._recording_lottie_animation_widget_actual)
            eb.connect("button-press-event", self._on_recording_indicator_clicked)
            self.clickable_recording_indicator = eb
        except Exception as e:
            logger.warning(f"Lottie FAILED: {e}. Fallback icon.", exc_info=True)
            fallback = str(
                self.screenrecord_action_config.get(
                    "bar_icon_active", icons.get("custom", {}).get("recording_active_bar", "media-record-symbolic")
                )
            )
            fb_img = FabricImage(
                icon_name=fallback,
                icon_size=self.panel_icon_size,
                style_classes=["panel-icon", "recording-indicator", "recording-indicator-active"],
            )
            eb = Gtk.EventBox(visible=False, sensitive=False)
            getattr(eb, "set_child", eb.add)(fb_img)
            eb.connect("button-press-event", self._on_recording_indicator_clicked)
            self.clickable_recording_indicator = eb
            self._recording_lottie_animation_widget_actual = None

        self._net_primary_sid = None
        self._net_ready_sid = None
        self._net_prop_hids = []
        self._bt_enabled_hid = None
        self._bt_conn_hid = None
        self._bt_dev_hid = None
        self._aud_spk_ch_hid = None
        self._spk_vol_h = None
        self._spk_mut_h = None
        self._conn_spk = None
        if self.network:
            self._net_primary_sid = self.network.connect("notify::primary-device", self._on_network_property_changed_cb)
            self._net_ready_sid = self.network.connect("device-ready", self._on_network_device_ready_cb)
        if self.audio:
            self._aud_spk_ch_hid = self.audio.connect("notify::speaker", self._on_speaker_changed_cb)
        if self.bluetooth_service:
            self._bt_enabled_hid = self.bluetooth_service.connect("notify::enabled", self._on_bluetooth_property_changed_cb)
            self._connect_bluetooth_device_signals()
        if self.recorder_service:
            self._screen_recorder_bar_signal_id = self.recorder_service.connect("recording", self._on_recording_state_changed_bar)

        if self.network:
            GLib.idle_add(self.on_network_device_ready, self.network)
        else:
            GLib.idle_add(self.update_network_icon)
        GLib.idle_add(self.on_speaker_changed)
        GLib.idle_add(self.update_bluetooth_icon)
        if self.recorder_service:
            GLib.idle_add(self._on_recording_state_changed_bar, self.recorder_service, self.recorder_service.is_recording)

        self.icon_container = Box(orientation="h", spacing=2, visible=True)
        self.icon_container.add(self.network_icon)
        self.icon_container.add(self.audio_icon)
        self.icon_container.add(self.bluetooth_icon)
        self.icon_container.add(self.clickable_recording_indicator)
        if hasattr(self, "set_child") and callable(self.set_child):
            self.set_child(self.icon_container)
        elif isinstance(self, Gtk.Button) and not self.get_label():
            self.set_image(self.icon_container)
            self.set_always_show_image(True)
        self.connect("clicked", self._on_button_clicked)
        self.popup = None

    def _on_recording_indicator_clicked(self, eb, ev):
        if (
            ev.type == Gdk.EventType.BUTTON_PRESS
            and ev.button == Gdk.BUTTON_PRIMARY
            and self.recorder_service
            and self.recorder_service.is_recording
        ):
            self.recorder_service.screenrecord_stop()
            return True
        return False

    def _on_recording_state_changed_bar(self, _service, is_recording):
        lottie = self._recording_lottie_animation_widget_actual
        if is_recording:
            self.network_icon.hide()
            self.audio_icon.hide()
            self.bluetooth_icon.hide()
            self.clickable_recording_indicator.show()
            self.clickable_recording_indicator.set_sensitive(True)
            if lottie and hasattr(lottie, "play_loop"):
                lottie.play_loop()
        else:
            if lottie and hasattr(lottie, "stop_play"):
                # Lottie fix: ensure timeout exists if stop_play relies on it
                if hasattr(lottie, "timeout") and lottie.timeout is not None:
                    lottie.stop_play()
                elif not hasattr(lottie, "timeout"):
                    lottie.stop_play()  # If stop_play doesn't need it
            self.clickable_recording_indicator.hide()
            self.clickable_recording_indicator.set_sensitive(False)
            self.network_icon.show()
            self.audio_icon.show()
            self.bluetooth_icon.show()
            GLib.idle_add(self.update_network_icon)
            GLib.idle_add(self.update_volume)
            GLib.idle_add(self.update_bluetooth_icon)
        return GLib.SOURCE_REMOVE

    def _connect_bluetooth_device_signals(self):  # ... (original)
        if not self.bluetooth_service or not hasattr(self.bluetooth_service, "find_property"):
            return
        try:
            if self.bluetooth_service.find_property("connected-devices"):
                self._bt_conn_hid = self.bluetooth_service.connect("notify::connected-devices", self._on_bluetooth_property_changed_cb)
            if self.bluetooth_service.find_property("devices"):
                self._bt_dev_hid = self.bluetooth_service.connect("notify::devices", self._on_bluetooth_property_changed_cb)
        except:
            pass

    def _on_network_property_changed_cb(self, o, p):
        GLib.idle_add(self.update_network_icon)
        return GLib.SOURCE_REMOVE

    def _on_network_device_ready_cb(self, c, *a):
        GLib.idle_add(self.on_network_device_ready, c)
        return GLib.SOURCE_REMOVE

    def _on_speaker_changed_cb(self, o, p):
        GLib.idle_add(self.on_speaker_changed)
        return GLib.SOURCE_REMOVE

    def _on_bluetooth_property_changed_cb(self, o, p):
        GLib.idle_add(self.update_bluetooth_icon)
        return GLib.SOURCE_REMOVE

    def _on_button_clicked(self, w):  # As per original, with Popover integration
        if self.popup is None:
            try:
                self.popup = Popover(
                    content_factory=lambda: QuickSettingsMenu(
                        config=self.quick_settings_menu_content_config,
                        screenshot_action_config=self.screenshot_action_config,
                        screenrecord_action_config=self.screenrecord_action_config,
                    ),
                    point_to=self,
                )
                logger.info(f"{self.__class__.__name__}: Popover created: {self.popup}")
            except Exception as e:
                logger.error(f"Popover creation error: {e}", exc_info=True)
                self.popup = None
                return True
        if self.popup:
            try:
                if hasattr(self.popup, "open") and callable(self.popup.open):
                    self.popup.open()
                elif hasattr(self.popup, "popup") and callable(self.popup.popup):
                    self.popup.popup()
                else:
                    logger.error(f"Popover has no open/popup method: {self.popup}")
            except Exception as e:
                logger.error(f"Error opening Popover: {e}", exc_info=True)
                self.popup.destroy()
                self.popup = None
        return True

    def update_network_icon(self, *_):  # Original logic with str() safety
        # ... (Full original logic with str() casts for icon names)
        final_icon_name = str(icons.get("network-offline-symbolic", "network-offline-symbolic"))
        if self.network:
            prim_type = getattr(self.network, "primary_device", None)
            if prim_type == "wifi":
                wifi_dev = getattr(self.network, "wifi_device", None)
                if wifi_dev and hasattr(wifi_dev, "icon_name") and callable(wifi_dev.icon_name):
                    final_icon_name = str(wifi_dev.icon_name())
                elif wifi_dev and hasattr(wifi_dev, "get_property"):
                    try:
                        final_icon_name = str(wifi_dev.get_property("icon-name") or final_icon_name)
                    except:
                        pass
                else:
                    final_icon_name = str(icons.get("network", {}).get("wifi", {}).get("disabled", "network-wireless-offline-symbolic"))
            elif prim_type == "wired":
                eth_dev = getattr(self.network, "ethernet_device", None)
                if eth_dev and hasattr(eth_dev, "get_property"):
                    try:
                        rep_icon = eth_dev.get_property("icon-name")
                        if rep_icon and "unknown" not in str(rep_icon).lower():
                            final_icon_name = str(rep_icon)
                        else:
                            final_icon_name = str(icons.get("network", {}).get("wired-symbolic", "network-wired-symbolic"))
                    except:
                        final_icon_name = str(icons.get("network", {}).get("wired-symbolic", "network-wired-symbolic"))
                else:
                    final_icon_name = str(icons.get("network", {}).get("wired-no-route-symbolic", "network-offline-symbolic"))
        if self.network_icon.get_visible() or not (self.recorder_service and self.recorder_service.is_recording):
            self.network_icon.set_from_icon_name(final_icon_name, self.panel_icon_size)
        return GLib.SOURCE_REMOVE

    def _is_network_connected(self, p, w, e):  # ... (original)
        try:
            if self.network and hasattr(self.network, "connectivity") and self.network.connectivity == 4:
                return True  # NM_CONNECTIVITY_FULL
            ac = getattr(self.network, "primary_connection", getattr(self.network, "active_connection", None))
            if ac and hasattr(ac, "state") and ac.state == 2:
                return True  # NM_ACTIVE_CONNECTION_STATE_ACTIVATED
        except:
            pass
            return False

    def _disconnect_all_network_prop_handlers(self):  # ... (original)
        for o, h in list(self._net_prop_hids):
            if o and h and hasattr(o, "handler_is_connected") and o.handler_is_connected(h):
                o.disconnect(h)
        self._net_prop_hids.clear()

    def on_network_device_ready(self, client):  # ... (original)
        self._disconnect_all_network_prop_handlers()
        devs = [client] if client else []
        if client:
            w = getattr(client, "wifi_device", None)
            e = getattr(client, "ethernet_device", None)
            (devs.append(w) if w else None)
            (devs.append(e) if e else None)
        props = ["icon-name", "enabled", "state", "active-access-point", "carrier", "primary-device", "connectivity"]
        for d in devs:
            if d and hasattr(d, "connect") and hasattr(d, "find_property"):
                for p_name in props:
                    if d.find_property(p_name):
                        try:
                            self._net_prop_hids.append((d, d.connect(f"notify::{p_name}", self._on_network_property_changed_cb)))
                        except:
                            pass
        GLib.idle_add(self.update_network_icon)
        return GLib.SOURCE_REMOVE

    def on_speaker_changed(self, *_):  # ... (original)
        cb = lambda o, p: GLib.idle_add(self.update_volume)
        if self._conn_spk:
            self._spk_vol_h = self._disconnect_handler_id_safe(self._conn_spk, self._spk_vol_h)
            self._spk_mut_h = self._disconnect_handler_id_safe(self._conn_spk, self._spk_mut_h)
        self._conn_spk = None
        if self.audio and self.audio.speaker and hasattr(self.audio.speaker, "connect"):
            self._conn_spk = self.audio.speaker
            spk_obj = self._conn_spk
            if hasattr(spk_obj, "find_property") and spk_obj.find_property("volume"):
                self._spk_vol_h = spk_obj.connect("notify::volume", cb)
            mp = "is-muted" if hasattr(spk_obj, "find_property") and spk_obj.find_property("is-muted") else "muted"
            if hasattr(spk_obj, "find_property") and spk_obj.find_property(mp):
                self._spk_mut_h = spk_obj.connect(f"notify::{mp}", cb)
        GLib.idle_add(self.update_volume)
        return GLib.SOURCE_REMOVE

    def update_volume(self, *_):  # Using local import as per original
        from utils.widget_utils import get_audio_icon_name

        key = str(icons.get("audio", {}).get("volume", {}).get("muted", "audio-volume-muted-symbolic"))
        calc_vol = 0
        is_muted = True
        if self.audio and self.audio.speaker:
            spk = self.audio.speaker
            calc_vol = round(getattr(spk, "volume", 0))
            is_muted = bool(getattr(spk, "is_muted", getattr(spk, "muted", True)))
            info = get_audio_icon_name(calc_vol, is_muted) if callable(get_audio_icon_name) else {"icon": key}
            key = str(info["icon"] if info and "icon" in info else key)
        else:
            info = get_audio_icon_name(0, True) if callable(get_audio_icon_name) else {"icon": key}
            key = str(
                info["icon"]
                if info and "icon" in info
                else icons.get("audio", {}).get("volume", {}).get("muted-fallback", "audio-volume-muted-symbolic")
            )
        if self.audio_icon.get_visible() or not (self.recorder_service and self.recorder_service.is_recording):
            self.audio_icon.set_from_icon_name(key, self.panel_icon_size)
        return GLib.SOURCE_REMOVE

    def update_bluetooth_icon(self, *_):  # ... (original with str() safety)
        name = str(icons.get("bluetooth", {}).get("disabled-symbolic", "bluetooth-disabled-symbolic"))
        if self.bluetooth_service and getattr(self.bluetooth_service, "enabled", False):
            name = str(icons.get("bluetooth", {}).get("active-symbolic", "bluetooth-active-symbolic"))
            if (
                isinstance(getattr(self.bluetooth_service, "connected_devices", []), (list, tuple))
                and len(getattr(self.bluetooth_service, "connected_devices", [])) > 0
            ):
                name = str(icons.get("bluetooth", {}).get("connected-symbolic", name))
        if self.bluetooth_icon.get_visible() or not (self.recorder_service and self.recorder_service.is_recording):
            self.bluetooth_icon.set_from_icon_name(name, self.panel_icon_size)
        return GLib.SOURCE_REMOVE

    def _disconnect_handler_id_safe(self, obj, hid):  # ... (original)
        if obj and hid is not None and hasattr(obj, "handler_is_connected") and obj.handler_is_connected(hid):
            obj.disconnect(hid)
        return None

    def destroy(self):  # Original logic with Lottie fix and logging
        logger.info(f"DESTROY: {self.__class__.__name__}")
        lottie = self._recording_lottie_animation_widget_actual
        if lottie and hasattr(lottie, "stop_play"):
            if hasattr(lottie, "timeout") and lottie.timeout is not None:
                lottie.stop_play()
            elif not hasattr(lottie, "timeout"):
                lottie.stop_play()
        if self.popup:
            self.popup.destroy()
            self.popup = None
        self._disconnect_all_network_prop_handlers()
        if self.network:
            self._net_primary_sid = self._disconnect_handler_id_safe(self.network, self._net_primary_sid)
            self._net_ready_sid = self._disconnect_handler_id_safe(self.network, self._net_ready_sid)
        if self.audio:
            self._aud_spk_ch_hid = self._disconnect_handler_id_safe(self.audio, self._aud_spk_ch_hid)
        if self._conn_spk:
            self._spk_vol_h = self._disconnect_handler_id_safe(self._conn_spk, self._spk_vol_h)
            self._spk_mut_h = self._disconnect_handler_id_safe(self._conn_spk, self._spk_mut_h)
        if self.bluetooth_service:
            self._bt_enabled_hid = self._disconnect_handler_id_safe(self.bluetooth_service, self._bt_enabled_hid)
            self._bt_conn_hid = self._disconnect_handler_id_safe(self.bluetooth_service, self._bt_conn_hid)
            self._bt_dev_hid = self._disconnect_handler_id_safe(self.bluetooth_service, self._bt_dev_hid)
        if (
            self.recorder_service
            and self._screen_recorder_bar_signal_id
            and hasattr(self.recorder_service, "handler_is_connected")
            and self.recorder_service.handler_is_connected(self._screen_recorder_bar_signal_id)
        ):
            self.recorder_service.disconnect(self._screen_recorder_bar_signal_id)
        self.network = self.audio = self.bluetooth_service = self.recorder_service = self._conn_spk = lottie = (
            self.clickable_recording_indicator
        ) = None  # Clear many refs
        super().destroy()
