# Quick Settings Module - Cleaned Imports

import os
import weakref

from fabric.utils import get_relative_path
from fabric.widgets.box import Box
from fabric.widgets.centerbox import CenterBox
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import GLib, Gtk # Gtk needed for PositionType, Grid, GLib for idle_add, etc.

import utils.functions as helpers
# Import needed services (those used *directly* or whose types are used in quick_settings.py)
from services import Brightness, MprisPlayerManager, audio_service, bluetooth_service, network_service, NetworkClient # NetworkClient is used in type hint


# --- REMOVED UNUSED IMPORTS ---
# Removed: from services import AudioStream # AudioStream is used in AudioSinkSubMenu, not directly here
# Removed: from utils.functions import exec_shell_command_async # exec_shell_command_async is used in AudioSinkSubMenu, not directly here
# Removed: import subprocess # Used by HyprSunsetIntensitySlider, not directly here
# Removed: import shutil # Used by HyprSunsetIntensitySlider, not directly here


from shared import (
    ButtonWidget,
    CircleImage,
    Dialog,
    Grid,
    HoverButton,
    Popover,
    QSChevronButton,
    QuickSubMenu,
    # Assume ScanButton is imported in the AudioSinkSubMenu file from shared.buttons
    # Assume SettingSlider is imported in the sliders file from shared
)
from utils import BarConfig
from utils.icons import icons
from utils.widget_utils import (
    get_audio_icon_name,
    get_brightness_icon_name, # Keep if potentially used elsewhere, though not by QuickSettingsButtonWidget
    util_fabricator, # Connected to in QuickSettingsMenu for uptime
)

from ..media import PlayerBoxStack
# Import needed sliders
from .shortcuts import ShortcutsContainer
from .sliders import AudioSlider, BrightnessSlider, MicrophoneSlider, HyprSunsetIntensitySlider # HyprSunsetIntensitySlider is instantiated here
# Import needed submenus
from .submenu import (
    AudioSinkSubMenu, # AudioSinkSubMenu is instantiated here
    BluetoothSubMenu, # BluetoothSubMenu is instantiated here
    BluetoothToggle, # BluetoothToggle is instantiated here
    PowerProfileSubMenu, # PowerProfileSubMenu is instantiated here
    PowerProfileToggle, # PowerProfileToggle is instantiated here
    WifiSubMenu, # WifiSubMenu is instantiated here
    WifiToggle, # WifiToggle is instantiated here
)
# Assume MicroPhoneSubMenu is still needed and correctly imported
from .submenu.mic import MicroPhoneSubMenu


from .togglers import (
    HyprIdleQuickSetting, # Instantiated here
    HyprSunsetQuickSetting, # Instantiated here
    NotificationQuickSetting, # Instantiated here
)


# QuickSettingsButtonBox remains unchanged
class QuickSettingsButtonBox(Box):
    """A box to display the quick settings buttons."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="v",
            name="quick-settings-button-box",
            spacing=4,
            h_align="start",
            v_align="start",
            v_expand=True,
            **kwargs,
        )

        self.grid = Gtk.Grid(
            row_spacing=10,
            column_spacing=10,
            column_homogeneous=True,
            row_homogeneous=True,
            visible=True
        )

        self.active_submenu = None

        bluetooth_submenu_instance = BluetoothSubMenu()
        self.bluetooth_toggle = BluetoothToggle(
            submenu=bluetooth_submenu_instance,
        )

        wifi_submenu_instance = WifiSubMenu()
        self.wifi_toggle = WifiToggle(
            submenu=wifi_submenu_instance,
        )

        powerprofile_submenu_instance = PowerProfileSubMenu()
        self.power_pfl = PowerProfileToggle(submenu=powerprofile_submenu_instance)

        self.hypr_idle = HyprIdleQuickSetting()
        self.hypr_sunset = HyprSunsetQuickSetting()
        self.notification_btn = NotificationQuickSetting()

        self.grid.attach(self.wifi_toggle, 1, 1, 1, 1)
        self.grid.attach_next_to(self.bluetooth_toggle, self.wifi_toggle, Gtk.PositionType.RIGHT, 1, 1)
        self.grid.attach_next_to(self.power_pfl, self.wifi_toggle, Gtk.PositionType.BOTTOM, 1, 1)
        self.grid.attach_next_to(self.hypr_sunset, self.bluetooth_toggle, Gtk.PositionType.BOTTOM, 1, 1)
        self.grid.attach_next_to(self.hypr_idle, self.power_pfl, Gtk.PositionType.BOTTOM, 1, 1)
        self.grid.attach_next_to(self.notification_btn, self.hypr_idle, Gtk.PositionType.RIGHT, 1, 1)

        self.wifi_toggle.connect("reveal-clicked", self.set_active_submenu)
        self.bluetooth_toggle.connect("reveal-clicked", self.set_active_submenu)
        self.power_pfl.connect("reveal-clicked", self.set_active_submenu)

        self.add(self.grid)
        self.add(wifi_submenu_instance)
        self.add(bluetooth_submenu_instance)
        self.add(powerprofile_submenu_instance)


    def set_active_submenu(self, btn: QSChevronButton):
        if self.active_submenu is not None and self.active_submenu != btn.submenu:
            self.active_submenu.do_reveal(False)
        self.active_submenu = btn.submenu
        self.active_submenu.toggle_reveal() if self.active_submenu else None


# QuickSettingsMenu - Modified to use AudioSinkSubMenu, fix uptime icon styling, and add HyprSunsetIntensitySlider
class QuickSettingsMenu(Box):
    """The main container widget for the Quick Settings menu."""

    def __init__(self, config, **kwargs):
        super().__init__( name="quicksettings-menu", orientation="v", all_visible=True, **kwargs )

        self.config = config
        self_ref = weakref.ref(self)

        # --- User Box Setup ---
        user_cfg = self.config.get("user", {}); user_image = (get_relative_path("../../assets/images/banner.jpg") if not os.path.exists(os.path.expandvars("$HOME/.face")) else os.path.expandvars("$HOME/.face")); username = (GLib.get_user_name() if user_cfg.get("name") == "system" or user_cfg.get("name") is None else user_cfg.get("name", GLib.get_user_name()));
        if user_cfg.get("distro_icon", False): username = f"{helpers.get_distro_icon()} {username}"; username_label = Label(label=username, v_align="center", h_align="start", style_classes="user");

        # --- Uptime Icon and Label (Corrected Styling and Spacing) ---
        self.uptime_box = Box(orientation="h", spacing=10, h_align="start", v_align="center", style_classes="uptime")

        self.uptime_icon_label = Label(
            label="",
            style_classes="icon",
            v_align="center",
        )

        self.uptime_value_label = Label(
            label=helpers.uptime(),
            v_align="center",
        )

        self.uptime_box.add(self.uptime_icon_label)
        self.uptime_box.add(self.uptime_value_label)
        # --- END Uptime ---

        self.user_box = Gtk.Grid(column_spacing=10, name="user-box-grid", visible=True, hexpand=True); avatar = CircleImage(image_file=user_image, size=65); avatar.set_size_request(65, 65); self.user_box.attach(avatar, 0, 0, 2, 2);
        power_dialog = Dialog(); button_box_end_content = Box(orientation="h", children=( HoverButton(image=Image(icon_name=icons["powermenu"]["reboot"], icon_size=16), v_align="center", on_clicked=lambda *_: (self_ref() and self_ref().get_parent_window() and self_ref().get_parent_window().hide(), power_dialog.add_content(title="Restart", body="Do you really want to restart?", command="systemctl reboot").toggle_popup())), HoverButton(image=Image(icon_name=icons["powermenu"]["shutdown"], icon_size=16), v_align="center", on_clicked=lambda *_: (self_ref() and self_ref().get_parent_window() and self_ref().get_parent_window().hide(), power_dialog.add_content(title="Shutdown", body="Do you really want to shutdown?", command="systemctl poweroff").toggle_popup())), )); button_box_main = Box(orientation="h", h_align="end", v_align="center", name="button-box", hexpand=True, vexpand=True); button_box_main.pack_end(button_box_end_content, False, False, 0); self.user_box.attach_next_to(username_label, avatar, Gtk.PositionType.RIGHT, 1, 1);
        self.user_box.attach_next_to(
            self.uptime_box,
            username_label,
            Gtk.PositionType.BOTTOM,
            1, 1,
        )
        self.user_box.attach_next_to(button_box_main, username_label, Gtk.PositionType.RIGHT, 4, 4);

        # --- Sliders Grid Setup ---
        sliders_grid = Gtk.Grid(visible=True, row_spacing=10, column_spacing=10, column_homogeneous=True, row_homogeneous=False, valign="center", hexpand=True, vexpand=False);
        # --- MODIFIED: Instantiate AudioSinkSubMenu ---
        self.audio_submenu = AudioSinkSubMenu() # Use the AudioSinkSubMenu
        # --- END MODIFIED ---
        self.mic_submenu = MicroPhoneSubMenu(); # Keep mic submenu

        # --- Center Box (Sliders & Shortcuts) ---
        center_box = Box(orientation="h", spacing=10, style_classes="section-box", hexpand=True); main_grid = Gtk.Grid(visible=True, column_spacing=10, hexpand=True, column_homogeneous=False); center_box.add(main_grid); [main_grid.insert_column(i) for i in range(3)];
        shortcuts_config = self.config.get("shortcuts", {}); slider_class = "slider-box-long";
        if shortcuts_config and shortcuts_config.get("enabled", False): num_shortcuts = len(shortcuts_config.get("items", [])); slider_class = "slider-box-shorter" if num_shortcuts > 2 else "slider-box-short";

        sliders_box_children = [sliders_grid];
        configured_controls = self.config.get("controls", {}).get("sliders", []) # Renamed to configured_controls

        # Add submenus based on configured controls
        # Audio submenu is added if "volume" control is configured
        if "volume" in configured_controls:
            sliders_box_children.append(self.audio_submenu)
        # Microphone submenu is added if "microphone" control is configured
        if "microphone" in configured_controls:
             sliders_box_children.append(self.mic_submenu)
        # No specific submenu needed for hyprsunset_intensity slider itself


        sliders_box = Box(orientation="v", spacing=10, style_classes=[slider_class], children=sliders_box_children, h_expand=False, vexpand=False);

        # --- Populate Sliders Grid ---
        active_controls_count = 0 # Renamed counter
        if not isinstance(configured_controls, list): configured_controls = []
        for control_name in configured_controls: # Loop through control names
            widget = None # Renamed to widget
            try:
                # --- MODIFIED: Instantiate sliders based on control_name ---
                if control_name == "volume":
                    widget = AudioSlider()
                elif control_name == "microphone":
                    widget = MicrophoneSlider()
                elif control_name == "brightness":
                     # Instantiate BrightnessSlider IF explicitly configured
                     widget = BrightnessSlider()
                elif control_name == "hyprsunset_intensity":
                    # Instantiate HyprSunsetIntensitySlider IF explicitly configured
                    widget = HyprSunsetIntensitySlider() # Use the imported slider
                else: print(f"WARNING: Unknown control type '{control_name}' in config. Skipping.")
            except Exception as e: print(f"ERROR creating control '{control_name}': {e}")

            if widget:
                 sliders_grid.attach(
                     widget, # Attach the created widget
                     0, active_controls_count, 1, 1,
                 )
                 active_controls_count += 1


        # --- Layout Sliders Box and Shortcuts Box ---
        if shortcuts_config and shortcuts_config.get("enabled", False) and "items" in shortcuts_config:
            shortcuts_box = Box( orientation="v", spacing=10, style_classes=["section-box", "shortcuts-box"], children=(ShortcutsContainer(shortcuts_config=shortcuts_config["items"], style_classes="shortcuts-grid", v_align="start", h_align="fill")), h_expand=False, v_expand=True,); main_grid.attach(sliders_box, 0, 0, 2, 1); main_grid.attach(shortcuts_box, 2, 0, 1, 1);
        else: main_grid.attach(sliders_box, 0, 0, 3, 1)

        # --- Main Layout (CenterBox) ---
        box = CenterBox( orientation="v", style_classes="quick-settings-box", start_children=Box( orientation="v", spacing=10, v_align="center", style_classes="section-box", children=(self.user_box, QuickSettingsButtonBox())), center_children=center_box,); media_config = self.config.get("media", {});
        if media_config.get("enabled", False): box.end_children = Box( orientation="v", spacing=10, style_classes="section-box", children=(PlayerBoxStack(MprisPlayerManager(), config=media_config)))
        self.add(box)

        # --- Uptime Update ---
        util_fabricator.connect(
            "changed",
            lambda _, value: (
                self.uptime_value_label.set_label(value.get('uptime', 'N/A'))
            ),
        )
        # --- END Uptime Update ---


# This is the Button Widget that goes in the bar/panel
class QuickSettingsButtonWidget(ButtonWidget):
    """A button widget in the bar to toggle the Quick Settings Popover."""

    def __init__(self, widget_config: BarConfig, **kwargs):
        super().__init__(
            widget_config.get("quick_settings", {}),
            name="quick_settings",
            **kwargs,
        )
        self.config = widget_config.get("quick_settings", {})
        if not self.config:
            print("WARNING: 'quick_settings' configuration missing in widget_config.")

        # --- Initialize Services & Properties ---
        self.panel_icon_size = self.config.get("panel_icon_size", 16)
        self.audio = audio_service
        self._timeout_id = None
        self.network = network_service
        self.bluetooth_service = bluetooth_service

        # Brightness service is NOT needed for the bar button icons in this version
        # self.brightness_service = Brightness()

        # --- NO QuickSettingsMenu instance stored here ---
        # A NEW menu instance will be created every time the button is clicked.


        # --- Setup Icons ---
        self.network_icon = Image(style_classes="panel-icon")
        self.audio_icon = Image(style_classes="panel-icon")
        self.bluetooth_icon = Image(style_classes="panel-icon")
        # Removed self.brightness_icon


        # --- Connect Signals to Services (Simplified Connections, no global lists) ---

        # Network Service Signals
        self.network.connect("notify::primary-device", lambda s, pspec: GLib.idle_add(self.update_network_icon))
        self.network.connect("device-ready", lambda client, *a: GLib.idle_add(self.on_network_device_ready, client))

        # Audio Service Signals
        self.audio.connect("notify::speaker", self.on_speaker_changed)

        # Removed Brightness Service Signals

        # Bluetooth Service Signals
        if self.bluetooth_service:
             self.bluetooth_service.connect("notify::enabled", lambda s, pspec: GLib.idle_add(self.update_bluetooth_icon))
             try:
                 # Use the correct handler list for bluetooth service signals
                 self._bluetooth_handler_ids.append(self.bluetooth_service.connect("notify::connected-devices", lambda s, pspec: GLib.idle_add(self.update_bluetooth_icon)))
                 self._bluetooth_handler_ids.append(self.bluetooth_service.connect("notify::devices", lambda s, pspec: GLib.idle_add(self.update_bluetooth_icon)))
             except Exception:
                 pass
        else:
             print("WARNING: Bluetooth service not available for bar icon.")


        # --- Set Initial Icon States ---
        GLib.idle_add(self.on_network_device_ready, self.network)
        GLib.idle_add(self.on_speaker_changed)
        GLib.idle_add(self.update_bluetooth_icon)


        # --- Define Button Children ---
        self.children = Box(
            children=(
                self.network_icon,
                self.audio_icon,
                self.bluetooth_icon,
            )
        )

        self.connect("clicked", self._on_button_clicked)

    def _on_button_clicked(self, *args):
        """Handler for the button click to create and open a new Popover."""
        try:
            new_menu_instance = QuickSettingsMenu(config=self.config)
            new_popup = Popover(
                point_to=self, # The button widget itself
                content=new_menu_instance # The NEW menu content widget
            )

            new_popup.open()

        except Exception as e:
             print(f"ERROR: Exception while creating/opening Popover/Menu on click: {e}")
             import traceback
             traceback.print_exc()

    _network_handler_ids = []

    def update_network_icon(self, *args):
        icon_name = icons.get("network-offline-symbolic", "network-offline-symbolic")
        primary = getattr(self.network, 'primary_device', None)
        wifi = self.network.wifi_device
        ethernet = self.network.ethernet_device
        size = self.panel_icon_size

        if primary == "wifi" and wifi:
            if wifi.get_property("enabled"):
                base_icon = wifi.get_property("icon-name")
                icon_name = base_icon + "-symbolic" if base_icon and isinstance(base_icon, str) else icons["network"]["wifi"]["generic"] + "-symbolic"
            else:
                icon_name = icons["network"]["wifi"]["disabled"]
        elif primary == "wired" and ethernet:
            base_icon = ethernet.get_property("icon-name")
            icon_name = base_icon or icons.get("network-wired-symbolic", "network-wired-symbolic") if base_icon and isinstance(base_icon, str) else icons.get("network-wired-symbolic", "network-wired-symbolic")

        if icon_name is None or not isinstance(icon_name, str) or icon_name.strip() == "" or icon_name == "network-offline-symbolic":
             icon_name = icons.get("network", {}).get("wifi", {}).get("disconnected", "network-offline-symbolic")

        if icon_name and isinstance(icon_name, str):
            self.network_icon.set_from_icon_name(icon_name, size)
        else:
            print(f"Warning: Invalid final network icon name '{icon_name}'. Using generic offline.")
            self.network_icon.set_from_icon_name(icons.get("network-offline-symbolic", "network-offline-symbolic"), size)
        return False

    def _disconnect_network_handlers(self):
         if self.network and self._network_handler_ids:
               current_wifi = self.network.wifi_device
               current_ethernet = self.network.ethernet_device
               for handler_id in self._network_handler_ids:
                    disconnected = False
                    if current_wifi:
                         try:
                              if current_wifi.handler_is_connected(handler_id):
                                   current_wifi.disconnect(handler_id)
                                   disconnected = True
                         except Exception: pass
                    if current_ethernet and not disconnected:
                         try:
                             if current_ethernet.handler_is_connected(handler_id):
                                  current_ethernet.disconnect(handler_id)
                                  disconnected = True
                         except Exception: pass
               self._network_handler_ids = []


    def on_network_device_ready(self, client: NetworkClient, *args):
        self._disconnect_network_handlers()

        wifi = self.network.wifi_device
        ethernet = self.network.ethernet_device

        if wifi:
             self._network_handler_ids.append(wifi.connect("notify::icon-name", self.update_network_icon))
             self._network_handler_ids.append(wifi.connect("notify::enabled", self.update_network_icon))
             try:
                 if wifi.find_property("state"):
                    self._network_handler_ids.append(wifi.connect("notify::state", self.update_network_icon))
             except Exception: pass

        if ethernet:
             self._network_handler_ids.append(ethernet.connect("notify::icon-name", self.update_network_icon))
             try:
                 if ethernet.find_property("state"):
                    self._network_handler_ids.append(ethernet.connect("notify::state", self.update_network_icon))
             except Exception: pass

        self.update_network_icon()

        return False


    _speaker_volume_handler_id = None
    _speaker_muted_handler_id = None
    _connected_speaker_instance = None

    def on_speaker_changed(self, _obj=None, _pspec=None):
        if self._connected_speaker_instance:
            try:
                 if self._speaker_volume_handler_id and self._connected_speaker_instance.handler_is_connected(self._speaker_volume_handler_id):
                     self._connected_speaker_instance.disconnect(self._speaker_volume_handler_id)
                 if self._speaker_muted_handler_id and self._connected_speaker_instance.handler_is_connected(self._speaker_muted_handler_id):
                     self._connected_speaker_instance.disconnect(self._speaker_muted_handler_id)
            except Exception: pass
        self._speaker_volume_handler_id = None
        self._speaker_muted_handler_id = None
        self._connected_speaker_instance = None

        if self.audio.speaker:
            self._speaker_volume_handler_id = self.audio.speaker.connect("notify::volume", self.update_volume)
            self._speaker_muted_handler_id = self.audio.speaker.connect("notify::muted", self.update_volume)
            self._connected_speaker_instance = self.audio.speaker

        GLib.idle_add(self.update_volume)
        return False

    def update_volume(self, *_):
        icon_key = icons["audio"]["volume"]["muted"]
        if self.audio.speaker:
            volume = round(self.audio.speaker.volume)
            muted = self.audio.speaker.muted
            icon_info = get_audio_icon_name(volume, muted)
            if icon_info and 'icon' in icon_info: icon_key = icon_info['icon']
        self.audio_icon.set_from_icon_name(icon_key, self.panel_icon_size)
        return False


    _bluetooth_handler_ids = []

    def update_bluetooth_icon(self, *args):
        icon_name = icons.get("bluetooth-disabled-symbolic", "bluetooth-disabled-symbolic")

        if self.bluetooth_service:
            if self.bluetooth_service.enabled:
                icon_name = icons.get("bluetooth-active-symbolic", "bluetooth-active-symbolic")

                try:
                    connected_devices = getattr(self.bluetooth_service, 'connected_devices', None)
                    if connected_devices is not None and hasattr(connected_devices, '__len__') and len(connected_devices) > 0:
                         icon_name = icons.get("bluetooth-connected-symbolic", icons.get("bluetooth-active-symbolic", "bluetooth-active-symbolic"))
                except Exception:
                    pass

        self.bluetooth_icon.set_from_icon_name(icon_name, self.panel_icon_size)
        return False
