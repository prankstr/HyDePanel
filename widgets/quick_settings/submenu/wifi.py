from typing import Dict, Callable, List, Any, Literal
from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.entry import Entry
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import GLib, Gtk, GObject
from fabric.core.service import Property 

import gi 

from services import NetworkClient, Wifi, network_service 
from shared import QSChevronButton, QuickSubMenu
from shared.buttons import ScanButton
from utils.icons import icons 
from loguru import logger

NM = None 
try:
    gi.require_version("NM", "1.0")
    from gi.repository import NM
except (ImportError, ValueError, AttributeError) as e:
    logger.warning(f"Could not import gi.repository.NM in wifi submenu: {e}. NM type checks will be limited.")


class WifiSubMenu(QuickSubMenu):
    def __init__(self, **kwargs):
        self.client: NetworkClient = network_service
        self._device_ready_handler_id: int | None = None
        self._map_handler_id: int | None = None
        self._wifi_device_handlers: List[Dict[str, Any]] = []
        self._connected_submenu_wifi_device_instance: Wifi | None = None
        self._ap_for_password_prompt: Dict | None = None
        self._build_options_timeout_id: int | None = None 
        self._status_label: Label | None = None 
        self._last_known_wifi_service_enabled_state: bool | None = None

        self.content_area = Box(orientation="v", spacing=6, h_expand=True, v_expand=True)
        self.available_networks_box = Box(orientation="v", spacing=4, h_expand=True)
        self.ap_list_scroll_window = ScrolledWindow(
            min_content_size=(-1, 150), max_content_size=(-1, 350),
            propagate_width=True, propagate_height=False,
            v_expand=True, h_expand=True, child=self.available_networks_box,
        )
        self.ap_list_scroll_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.prompt_ssid_label = Label(markup="", h_align=Gtk.Align.START, style_classes=["title-4"]) 
        self.password_entry = Entry(
            placeholder_text="Password", password=True, 
            activates_default=True, h_expand=True, style_classes=["input"],
        )
        self.connect_button = Button(label="Connect", style_classes=["button", "suggested-action"])
        self.cancel_button = Button(label="Cancel", style_classes=["button"])

        password_actions_box = Box(orientation="h", spacing=6, h_align=Gtk.Align.END, children=[self.cancel_button, self.connect_button])
        self.password_prompt_box = Box(
            orientation="v", spacing=10, h_expand=True, v_expand=False,
            style="padding: 10px; margin-top: 5px; margin-bottom: 5px;",
            children=[self.prompt_ssid_label, self.password_entry, password_actions_box,], visible=False,
        )
        
        self.content_area.add(self.ap_list_scroll_window)
        self.content_area.add(self.password_prompt_box)
        self.scan_button = ScanButton()

        _network_icons = icons.get("network", {})
        _wifi_icons = _network_icons.get("wifi", {})
        _title_icon = _wifi_icons.get("generic", "network-wireless-symbolic")
        super().__init__(title="Network", title_icon=_title_icon, scan_button=self.scan_button, child=self.content_area, **kwargs)

        self.password_entry.connect("activate", lambda _: self._on_password_connect_clicked())
        self.connect_button.connect("clicked", lambda _: self._on_password_connect_clicked())
        self.cancel_button.connect("clicked", lambda _: self._hide_password_prompt_ui())
        self.scan_button.connect("clicked", self.start_new_scan)

        if hasattr(self.client, "connect"):
            self._device_ready_handler_id = self.client.connect("device-ready", self._on_client_device_ready)
        
        self.connect("destroy", self._on_destroy)
        self._map_handler_id = self.connect("map", self._on_menu_mapped)
        GLib.idle_add(self._initialize_wifi_state)

    def _on_menu_mapped(self, widget: Gtk.Widget) -> None:
        logger.debug("WifiSubMenu: Menu mapped. Scheduling AP list build.")
        self._schedule_build_options_for_ap_list()

    def _initialize_wifi_state(self) -> Literal[GLib.SOURCE_REMOVE]:
        if hasattr(self.client, 'wifi_device'):
             self._on_client_device_ready(self.client)
        return GLib.SOURCE_REMOVE

    def _on_client_device_ready(self, client: NetworkClient, *args) -> bool:
        new_wifi_instance = getattr(client, 'wifi_device', None)
        is_initial_concrete_setup = (self._connected_submenu_wifi_device_instance is None and 
                                     new_wifi_instance is not None)

        if self._connected_submenu_wifi_device_instance != new_wifi_instance:
            logger.info(f"WifiSubMenu: Wifi service instance changed.")
            self._disconnect_wifi_device_signals()
            self._connected_submenu_wifi_device_instance = new_wifi_instance
            self._last_known_wifi_service_enabled_state = None 
            if self._connected_submenu_wifi_device_instance:
                self._connect_relevant_signals(self._connected_submenu_wifi_device_instance)
        
        if self.password_prompt_box.get_visible():
            self._hide_password_prompt_ui(refresh_list=False)

        self._schedule_build_options_for_ap_list() 

        if is_initial_concrete_setup and self._connected_submenu_wifi_device_instance:
            try:
                if not self._connected_submenu_wifi_device_instance.access_points and \
                   self._connected_submenu_wifi_device_instance.enabled:
                    logger.info("WifiSubMenu: Initial setup, no APs found, triggering a scan.")
                    self._connected_submenu_wifi_device_instance.scan()
            except Exception as e:
                logger.warning(f"WifiSubMenu: Error during initial AP check/scan trigger: {e}")
        return True

    def _connect_relevant_signals(self, wifi_service: Wifi) -> None:
        if not wifi_service: return
        nm_device = getattr(wifi_service, '_device', None)
        if nm_device and not nm_device.is_floating():
            signals_to_connect = ["state-changed", "notify::active-access-point", 
                                  "access-point-added", "access-point-removed"]
            for sig_name in signals_to_connect:
                handler_id = nm_device.connect(sig_name, self._schedule_build_options_for_ap_list)
                self._wifi_device_handlers.append({'obj': nm_device, 'id': handler_id})
        
        self._wifi_device_handlers.append({'obj': wifi_service, 
                                           'id': wifi_service.connect("notify::access-points", self._schedule_build_options_for_ap_list)})
        self._wifi_device_handlers.append({'obj': wifi_service, 
                                           'id': wifi_service.connect("notify::enabled", self._handle_wifi_enabled_changed_for_status)})

    def _handle_wifi_enabled_changed_for_status(self, wifi_service: Wifi, gparam_spec: GObject.ParamSpec) -> bool:
        current_is_enabled = False
        if self._connected_submenu_wifi_device_instance:
            try:
                current_is_enabled = self._connected_submenu_wifi_device_instance.enabled
            except Exception as e:
                logger.warning(f"Error getting enabled state in _handle_wifi_enabled_changed_for_status: {e}")
                self._schedule_build_options_for_ap_list(); return True

        if self._last_known_wifi_service_enabled_state is None or \
           self._last_known_wifi_service_enabled_state != current_is_enabled:
            logger.info(f"WifiSubMenu: Wi-Fi enabled state changed for UI from {self._last_known_wifi_service_enabled_state} to {current_is_enabled}. Scheduling list build.")
            self._last_known_wifi_service_enabled_state = current_is_enabled
            self._schedule_build_options_for_ap_list()
        return True

    def _schedule_build_options_for_ap_list(self, *args) -> bool:
        if not self.password_prompt_box.get_visible():
            if self._build_options_timeout_id is not None:
                GLib.source_remove(self._build_options_timeout_id)
                self._build_options_timeout_id = None
            self._build_options_timeout_id = GLib.timeout_add(300, self._execute_build_wifi_options)
        return True

    def _execute_build_wifi_options(self) -> Literal[GLib.SOURCE_REMOVE]:
        logger.debug("WifiSubMenu: Rebuilding Wi-Fi options list (debounced).")
        self._build_options_timeout_id = None 
        self.build_wifi_options()
        return GLib.SOURCE_REMOVE 

    def _disconnect_wifi_device_signals(self) -> None:
        if not self._wifi_device_handlers: return
        for handler_info in self._wifi_device_handlers:
            obj, handler_id = handler_info['obj'], handler_info['id']
            if obj and (not hasattr(obj, 'is_floating') or not obj.is_floating()) and GObject.signal_handler_is_connected(obj, handler_id):
                try:
                    if NM and hasattr(NM, "Device") and isinstance(obj, NM.Device):
                        GObject.signal_handler_disconnect(obj, handler_id)
                    else:
                        obj.disconnect(handler_id)
                except Exception as e:
                    logger.warning(f"WifiSubMenu: Error disconnecting signal (id: {handler_id}) from {obj} (type: {type(obj)}): {e}")
        self._wifi_device_handlers = []
        if self._build_options_timeout_id is not None:
            GLib.source_remove(self._build_options_timeout_id)
            self._build_options_timeout_id = None

    @Property(object, "readable")
    def wifi_device(self) -> Wifi | None:
        return self._connected_submenu_wifi_device_instance

    def start_new_scan(self, _: Gtk.Widget) -> None:
        if self.scan_button.get_sensitive() and not self.password_prompt_box.get_visible():
            active_wifi_service = self._connected_submenu_wifi_device_instance
            if active_wifi_service and active_wifi_service.enabled:
                logger.info("WifiSubMenu: Initiating Wi-Fi scan.")
                active_wifi_service.scan(); self.scan_button.play_animation()
            elif active_wifi_service: logger.info("Wi-Fi is disabled, cannot scan.")
            else: logger.info("Wi-Fi device not available, cannot scan.")

    def build_wifi_options(self) -> Literal[GLib.SOURCE_REMOVE]:
        if self.password_prompt_box.get_visible(): return GLib.SOURCE_REMOVE
        for child in list(self.available_networks_box.get_children()):
            self.available_networks_box.remove(child); child.destroy() 
        self._status_label = None 

        current_wifi_device = self._connected_submenu_wifi_device_instance
        status_message = ""
        if not current_wifi_device: status_message = "Wifi device unavailable."
        elif not current_wifi_device.enabled: status_message = "Wifi is disabled."
        
        if status_message:
            self._status_label = Label(label=status_message, name="wifi-status-label", halign="center", valign="center", hexpand=True, vexpand=True)
            self.available_networks_box.add(self._status_label); self.available_networks_box.show_all()
            self.available_networks_box.queue_draw(); return GLib.SOURCE_REMOVE

        access_points = current_wifi_device.access_points
        if not access_points:
            self._status_label = Label(label="Scanning or no networks found...", name="wifi-no-networks-label", halign="center", valign="center", hexpand=True, vexpand=True)
            self.available_networks_box.add(self._status_label); self.available_networks_box.show_all()
            self.available_networks_box.queue_draw(); return GLib.SOURCE_REMOVE
        
        known_profiles = self.client.get_wifi_profiles()
        unique_aps_by_ssid_dict = {}
        for ap_data_item in access_points:
            ssid = ap_data_item.get("ssid")
            if not ssid or ssid == "Unknown": continue
            current_strength = ap_data_item.get("strength", 0)
            is_current_ap_active = ap_data_item.get("active_ap", False)
            existing_entry = unique_aps_by_ssid_dict.get(ssid)
            if existing_entry:
                if is_current_ap_active: unique_aps_by_ssid_dict[ssid] = {"ap_data": ap_data_item, "strength": current_strength}
                elif not existing_entry["ap_data"].get("active_ap", False) and current_strength > existing_entry["strength"]:
                    unique_aps_by_ssid_dict[ssid] = {"ap_data": ap_data_item, "strength": current_strength}
            else: unique_aps_by_ssid_dict[ssid] = {"ap_data": ap_data_item, "strength": current_strength}
        
        sorted_unique_ap_wrappers = sorted(
            list(unique_aps_by_ssid_dict.values()), 
            key=lambda i: (not i["ap_data"].get("active_ap", False), -i["strength"], i["ap_data"].get("ssid", "").lower())
        )
        
        known_ap_buttons, other_ap_buttons = [], []
        for ap_wrapper in sorted_unique_ap_wrappers:
            ap_data = ap_wrapper["ap_data"] 
            button = self.make_button_from_ap_data(ap_data)
            if ap_data.get("active_ap"): known_ap_buttons.insert(0, button)
            elif ap_data.get("ssid") in known_profiles: known_ap_buttons.append(button)
            else: other_ap_buttons.append(button)

        has_content = False
        if known_ap_buttons:
            has_content = True
            self.available_networks_box.add(Label(label="Known Networks", name="wifi-section-label", h_align=Gtk.Align.START, style_classes=["dim-label", "caption", "group-title"]))
            for btn in known_ap_buttons: self.available_networks_box.add(btn)
        if other_ap_buttons:
            has_content = True
            if known_ap_buttons: self.available_networks_box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=5, margin_bottom=5))
            self.available_networks_box.add(Label(label="Other Available Networks", name="wifi-section-label", h_align=Gtk.Align.START, style_classes=["dim-label", "caption", "group-title"]))
            for btn in other_ap_buttons: self.available_networks_box.add(btn)
        if not has_content:
             self._status_label = Label(label="No networks to display.", name="wifi-no-networks-label", halign="center", valign="center", hexpand=True, vexpand=True)
             self.available_networks_box.add(self._status_label)
        
        self.available_networks_box.show_all()
        self.available_networks_box.queue_draw() 
        if (parent := self.available_networks_box.get_parent()): parent.queue_draw()
        return GLib.SOURCE_REMOVE

    def _show_password_prompt_ui_for_new_connection(self, ap_data: Dict[str, Any]) -> None: 
        self._ap_for_password_prompt = ap_data 
        ssid = ap_data.get("ssid", "Unknown")
        logger.info(f"Showing password prompt for SSID: {ssid}")
        self.prompt_ssid_label.set_markup(f"Password for <b>{GLib.markup_escape_text(ssid)}</b>")
        self.password_entry.set_text("")
        self.ap_list_scroll_window.set_visible(False)
        self.password_prompt_box.set_visible(True); self.scan_button.set_sensitive(False) 
        GLib.idle_add(self.password_entry.grab_focus)
        
    def _hide_password_prompt_ui(self, refresh_list: bool = True) -> None:
        self._ap_for_password_prompt = None; self.password_prompt_box.set_visible(False)
        self.ap_list_scroll_window.set_visible(True); self.scan_button.set_sensitive(True)
        if refresh_list: self._schedule_build_options_for_ap_list()

    def _on_password_connect_clicked(self, _: Gtk.Widget | None = None) -> None:
        if not self._ap_for_password_prompt:
            logger.warning("Password connect clicked but no AP data stored."); self._hide_password_prompt_ui(); return
        password = self.password_entry.get_text()
        bssid = self._ap_for_password_prompt.get("bssid")
        ssid = self._ap_for_password_prompt.get("ssid")
        if not bssid or not ssid:
            logger.error(f"BSSID or SSID missing in password connect data."); self._hide_password_prompt_ui(); return
        logger.info(f"Attempting new connection to SSID: {ssid} (BSSID: {bssid})")
        self.client.connect_new_wifi_with_password(bssid, ssid, password)
        self._hide_password_prompt_ui(refresh_list=False)

    def make_button_from_ap_data(self, ap_data: dict) -> Button:
        ssid = ap_data.get("ssid", "Unknown")
        icon_name = ap_data.get("icon-name", icons.get("network", {}).get("wifi", {}).get("generic", "network-wireless-symbolic"))
        is_secure = ap_data.get("is_secure", False)
        is_active = ap_data.get("active_ap", False)
        
        ssid_escaped = GLib.markup_escape_text(ssid)
        main_label = Label(markup=f"<b>{ssid_escaped}</b>" if is_active else ssid_escaped, 
                           h_expand=True, h_align=Gtk.Align.START)

        button_content = Box(orientation="h", spacing=6)
        button_content.add(Image(icon_name=icon_name, icon_size=18, pixel_size=18))
        button_content.add(main_label)
        
        if is_active: 
            active_icon_name = icons.get("status",{}).get("active_connection", "object-select-symbolic")
            button_content.add(Image(icon_name=active_icon_name, icon_size=16, pixel_size=16, halign="end", style_classes=["dim-label"]))
        elif is_secure: 
            lock_icon_name = icons.get("status", {}).get("encrypted", "changes-prevent-symbolic")
            button_content.add(Image(icon_name=lock_icon_name, icon_size=16, pixel_size=16, halign="end", style_classes=["dim-label"]))
        
        ap_button = Button(child=button_content, style_classes=["submenu-button"], h_expand=True)
        ap_button.set_sensitive(not is_active)
        ap_button.connect("clicked", lambda _, d=ap_data: self._handle_ap_button_clicked(d))
        
        tooltip_parts = [f"SSID: {ssid}"]
        if bssid_val := ap_data.get("bssid"): tooltip_parts.append(f"BSSID: {bssid_val}")
        tooltip_parts.append(f"Strength: {ap_data.get('strength',0)}%")
        tooltip_parts.append(f"Secure: {'Yes' if is_secure else 'No'}")
        if is_active: tooltip_parts.append("Status: Connected & Active")
        ap_button.set_tooltip_text("\n".join(tooltip_parts))
        return ap_button

    def _handle_ap_button_clicked(self, ap_data: dict) -> None:
        ssid = ap_data.get("ssid", "Unknown")
        if ap_data.get("active_ap", False): logger.info(f"AP {ssid} is already active."); return
        if not self.client: logger.error("NetworkClient not available."); return
        logger.info(f"WifiSubMenu: Initiating connection for SSID {ssid}")
        self.client.initiate_wifi_connection(ap_data, self._show_password_prompt_ui_for_new_connection)

    def _on_destroy(self, *args) -> None:
        logger.debug("WifiSubMenu: Destroying...")
        self._disconnect_wifi_device_signals()
        if self.client and self._device_ready_handler_id and \
           GObject.signal_handler_is_connected(self.client, self._device_ready_handler_id):
            self.client.disconnect(self._device_ready_handler_id)
        self._device_ready_handler_id = None
        if self._map_handler_id and GObject.signal_handler_is_connected(self, self._map_handler_id):
            self.disconnect(self._map_handler_id)
        self._map_handler_id = None

class WifiToggle(QSChevronButton):
    def __init__(self, submenu: WifiSubMenu, **kwargs):
        _wifi_icons = icons.get("network", {}).get("wifi", {})
        super().__init__(action_icon=_wifi_icons.get("disabled", "network-wireless-disabled-symbolic"), 
                         action_label=" Wifi", submenu=submenu, **kwargs)
        self.client: NetworkClient = network_service
        self._signal_handlers: List[Dict[str, Any]] = []
        self._device_ready_handler_id: int | None = None
        self._connected_wifi_device_instance: Wifi | None = None
        
        if hasattr(self.client, "connect"):
            self._device_ready_handler_id = self.client.connect("device-ready", self._on_client_device_ready)
        self.connect("destroy", self.on_destroy)
        self.connect("action-clicked", self.on_action_clicked)
        GLib.idle_add(self._initialize_toggle_state)

    def _initialize_toggle_state(self) -> Literal[GLib.SOURCE_REMOVE]:
        if hasattr(self.client, 'wifi_device'): self._on_client_device_ready(self.client)
        return GLib.SOURCE_REMOVE

    def _update_ui(self, enabled: bool, ssid: str, icon_name: str, sensitive: bool = True) -> None:
        self.set_active_style(enabled)
        self.action_icon.set_from_icon_name(icon_name, 18)
        self.action_label.set_label(" " + ssid if ssid else " Wifi")
        self.set_sensitive(sensitive)

    def _on_client_device_ready(self, client: NetworkClient, *args) -> bool:
        new_wifi_instance = getattr(client, 'wifi_device', None)
        if self._connected_wifi_device_instance != new_wifi_instance:
            logger.info(f"WifiToggle: Wifi service instance changed.")
            self._disconnect_all_service_handlers()
            self._connected_wifi_device_instance = new_wifi_instance
            if self._connected_wifi_device_instance:
                props = ["enabled", "icon-name", "ssid", "state", "internet"]
                for p_name in props:
                    sig_id = self._connected_wifi_device_instance.connect(f"notify::{p_name}", self._on_wifi_service_property_changed)
                    self._signal_handlers.append({'obj': self._connected_wifi_device_instance, 'id': sig_id})
        self._update_ui_from_service_properties()
        return True

    def _on_wifi_service_property_changed(self, wifi_service_instance: Wifi, gparam_spec: GObject.ParamSpec) -> bool:
        GLib.idle_add(self._update_ui_from_service_properties)
        return True

    def _update_ui_from_service_properties(self) -> Literal[GLib.SOURCE_REMOVE]:
        _wifi_icons = icons.get("network", {}).get("wifi", {})
        def_generic = _wifi_icons.get("generic", "network-wireless-symbolic")
        def_disabled = _wifi_icons.get("disabled", "network-wireless-disabled-symbolic")

        if self._connected_wifi_device_instance:
            try:
                wifi = self._connected_wifi_device_instance
                is_en, ssid_p, icon_p, state_p, net_p = wifi.enabled, wifi.ssid, wifi.icon_name, wifi.state, wifi.internet
                disp_ssid = "Wifi"
                if is_en:
                    if net_p=="activated": disp_ssid=ssid_p if ssid_p and ssid_p not in ["Disconnected","Unknown","Connected"] else "Connected"
                    elif net_p=="activating" or state_p in ["prepare","config","need_auth","ip_config","ip_check"]: disp_ssid="Connecting..."
                    elif state_p=="disconnected": disp_ssid="Disconnected"
                else: disp_ssid = "Wifi Off"
                
                final_icon = icon_p
                if not icon_p: final_icon = def_generic if is_en else def_disabled
                elif is_en and icon_p == "network-wireless-symbolic" and net_p not in ["activated","activating"] and state_p != "activated":
                    final_icon = "network-wireless-disconnected-symbolic" if state_p == "disconnected" else def_generic
                elif not is_en: final_icon = def_disabled
                
                old_lbl, old_icon_p = self.action_label.get_label().strip(), self.action_icon.get_icon_name()
                old_icon = old_icon_p[0] if old_icon_p and len(old_icon_p) > 0 else ""

                if old_lbl != disp_ssid or old_icon != final_icon:
                     logger.info(f"WifiToggle UI Update: Lbl '{old_lbl}'->'{disp_ssid}', Icon '{old_icon}'->'{final_icon}' (en={is_en}, net='{net_p}', state='{state_p}')")
                self._update_ui(is_en, disp_ssid, final_icon, True)
            except GLib.Error as e:
                logger.warning(f"WifiToggle: Error getting properties: {e}"); self._update_ui(False, "Wifi Error", def_disabled, False)
        else: self._update_ui(False, "Wifi Unavailable", def_disabled, False)
        return GLib.SOURCE_REMOVE

    def _disconnect_all_service_handlers(self) -> None:
        if not self._signal_handlers: return
        for h_info in self._signal_handlers:
            obj, sig_id = h_info['obj'], h_info['id']
            if obj and (not hasattr(obj, 'is_floating') or not obj.is_floating()) and GObject.signal_handler_is_connected(obj, sig_id):
                try: obj.disconnect(sig_id)
                except Exception: pass 
        self._signal_handlers = []

    def on_destroy(self, *args) -> None:
        self._disconnect_all_service_handlers()
        if self.client and self._device_ready_handler_id and \
           GObject.signal_handler_is_connected(self.client, self._device_ready_handler_id):
            try: self.client.disconnect(self._device_ready_handler_id)
            except Exception: pass
        self._device_ready_handler_id = None

    def on_action_clicked(self, _: Gtk.Button) -> None:
        if self._connected_wifi_device_instance:
            logger.info("WifiToggle: Action clicked, toggling Wi-Fi.")
            self._connected_wifi_device_instance.toggle_wifi()
        else: logger.warning("WifiToggle: Action clicked, but no wifi device instance available.")
