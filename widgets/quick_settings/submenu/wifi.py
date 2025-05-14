from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import GLib # Needed for potential future GLib.idle_add, and good practice if using Gtk stuff asynchronously

from services import NetworkClient, Wifi, network_service
from shared import QSChevronButton, QuickSubMenu
from shared.buttons import ScanButton # Assuming ScanButton is here in the new structure
from utils.icons import icons


class WifiSubMenu(QuickSubMenu):
    """A submenu to display the Wifi settings."""

    def __init__(self, **kwargs):
        self.client = network_service
        self.wifi_device = self.client.wifi_device
        self._device_ready_handler_id = self.client.connect("device-ready", self.on_device_ready)

        self.available_networks_box = Box(orientation="v", spacing=4, h_expand=True)

        self.scan_button = ScanButton()
        self.scan_button.connect("clicked", self.start_new_scan)

        self.child = ScrolledWindow(
            min_content_size=(-1, 190),
            max_content_size=(-1, 190),
            propagate_width=True,
            propagate_height=True,
            child=self.available_networks_box,
        )

        super().__init__(
            title="Network",
            title_icon=icons["network"]["wifi"]["generic"],
            scan_button=self.scan_button,
            child=self.child,
            **kwargs,
        )

        if self.client.wifi_device:
            self.build_wifi_options()


    def start_new_scan(self, _):
        if self.scan_button.get_sensitive():
            if self.client.wifi_device:
                self.client.wifi_device.scan()
                # Consider connecting to a "scan-finished" or "access-points-changed" signal
                # from self.client.wifi_device to call build_wifi_options for fresher data.
                # For now, building immediately.
                self.build_wifi_options() # Rebuild list after initiating scan
            self.scan_button.play_animation()

    def on_device_ready(self, client: NetworkClient, *args):
        self.wifi_device = client.wifi_device
        self.build_wifi_options()

    @staticmethod
    def get_strength_from_icon_name(icon_name: str | None) -> int:
        """
        Assigns a numerical strength based on common icon name patterns.
        Higher value means stronger signal.
        Adjust keywords based on actual icon names from your service.
        """
        if not icon_name:
            return 0 # No icon, no signal info

        # These are common patterns, adjust if your service uses different names
        # e.g., "network-wireless-signal-excellent", "network-wireless-signal-good", etc.
        # The order implies priority if multiple keywords match (e.g. "excellent" is better than "good")
        # This assumes icon_name might be like "network-wireless-signal-excellent-symbolic" or just "network-wireless-signal-excellent"
        strength_keywords_ordered = [
            ("excellent", 100),
            ("good", 75),
            ("ok", 50),
            ("weak", 25),
            ("none", 5), # Very low signal, but present
        ]

        for keyword, strength_value in strength_keywords_ordered:
            if keyword in icon_name:
                return strength_value
        
        # Fallback for generic or unrecognized icons
        # If it's the generic icon, assign a low default strength.
        if icons["network"]["wifi"]["generic"] in icon_name:
            return 1 # Generic icon, minimal presumed strength
        
        # If icon_name indicates encryption but no explicit signal strength,
        # give it a moderate default if no other keywords matched.
        # This part is highly speculative and depends on your icon naming.
        if "secure" in icon_name or "encrypted" in icon_name:
            return 10 # Generic secured, low-moderate strength

        return 0 # Default for completely unrecognized icons or truly no signal icons


    def build_wifi_options(self):
        # Clear existing list
        for child in self.available_networks_box.get_children():
            self.available_networks_box.remove(child)
            child.destroy() # Ensure proper cleanup of old widgets

        if not self.wifi_device:
            unavailable_label = Label(label="Wifi device unavailable", name="wifi-unavailable-label")
            self.available_networks_box.add(unavailable_label)
            return

        access_points = self.wifi_device.access_points
        if not access_points:
            no_networks_label = Label(label="No networks found", name="wifi-no-networks-label")
            self.available_networks_box.add(no_networks_label)
            return

        # --- BEGIN FIX: Filter for unique SSIDs with best signal ---
        unique_aps_by_ssid = {}
        for ap in access_points:
            ssid = ap.get("ssid")
            # Skip APs with no SSID or "Unknown" SSID
            if not ssid or ssid == "Unknown":
                continue

            current_ap_icon_name = ap.get("icon-name")
            current_ap_strength = WifiSubMenu.get_strength_from_icon_name(current_ap_icon_name)

            existing_ap_data = unique_aps_by_ssid.get(ssid)
            if existing_ap_data:
                existing_ap_strength = existing_ap_data["strength"]
                # If current AP is stronger, or if strengths are equal but current AP has a more specific icon
                # (less generic), replace the existing one.
                if current_ap_strength > existing_ap_strength:
                    unique_aps_by_ssid[ssid] = {"ap": ap, "strength": current_ap_strength}
                elif current_ap_strength == existing_ap_strength:
                    # Optional: Prefer APs that are not the generic icon if strengths are equal
                    is_current_generic = current_ap_icon_name == icons["network"]["wifi"]["generic"]
                    is_existing_generic = existing_ap_data["ap"].get("icon-name") == icons["network"]["wifi"]["generic"]
                    if is_existing_generic and not is_current_generic:
                         unique_aps_by_ssid[ssid] = {"ap": ap, "strength": current_ap_strength}
                    # You could add more tie-breaking rules here, e.g. preferring a secured network,
                    # or one that was previously connected if that info is available.
            else:
                unique_aps_by_ssid[ssid] = {"ap": ap, "strength": current_ap_strength}
        
        # Extract the AP objects from the filtered dictionary
        processed_aps_data = list(unique_aps_by_ssid.values())
        
        # Sort the displayed networks:
        # 1. By strength (descending)
        # 2. By SSID (alphabetically, ascending, case-insensitive)
        processed_aps_data.sort(
            key=lambda item: (
                -item["strength"], # Negative for descending strength
                item["ap"].get("ssid", "").lower() # SSID ascending
            )
        )
        
        # Get just the AP dictionaries for button creation
        final_ap_list = [item["ap"] for item in processed_aps_data]
        # --- END FIX ---

        if not final_ap_list: # Check if list is empty after filtering
            # This might happen if all found SSIDs were "Unknown" or had no name
            no_valid_networks_label = Label(label="No usable networks found", name="wifi-no-valid-networks-label")
            self.available_networks_box.add(no_valid_networks_label)
            return

        # Build buttons for the filtered and sorted unique networks
        for ap in final_ap_list:
            btn = self.make_button_from_ap(ap)
            self.available_networks_box.add(btn)

    def make_button_from_ap(self, ap) -> Button:
        ssid = ap.get("ssid", "Unknown")
        icon_name = ap.get("icon-name")
        bssid = ap.get("bssid") # BSSID of the chosen (strongest) AP

        ap_button = Button(style_classes="submenu-button", name="wifi-ap-button")
        ap_button.add(
            Box(
                style="padding: 5px;", # Consider making this a CSS style if consistent
                children=[
                    Image(
                        icon_name=icon_name if icon_name else icons["network"]["wifi"]["generic"],
                        icon_size=18,
                    ),
                    Label(label=f" {ssid}", style_classes="submenu-item-label"), # Added a space for better alignment
                ],
            )
        )
        
        if bssid: # Connect to the specific BSSID of this (strongest) AP
            ap_button.connect(
                "clicked", lambda _, ap_bssid=bssid: self.client.connect_wifi_bssid(ap_bssid)
            )
        
        # Tooltip showing details of the *selected* AP (which should be the strongest one for this SSID)
        tooltip_parts = [f"SSID: {ssid}"]
        if bssid:
            tooltip_parts.append(f"BSSID: {bssid}") # Shows which physical AP this entry represents
        if icon_name:
            tooltip_parts.append(f"Icon: {icon_name}")
        
        # You can also add the inferred strength to the tooltip for debugging/verification
        strength_val = WifiSubMenu.get_strength_from_icon_name(icon_name)
        tooltip_parts.append(f"Strength Score: {strength_val}")

        ap_button.set_tooltip_text("\n".join(tooltip_parts))

        return ap_button


class WifiToggle(QSChevronButton):
    """A widget to display a toggle button for Wifi."""

    def __init__(self, submenu: QuickSubMenu, **kwargs):
        super().__init__(
            action_icon=icons["network"]["wifi"]["disabled"], 
            action_label=" Wifi", 
            submenu=submenu,
            **kwargs,
        )
        self.client = network_service
        self._wifi_service_handler_ids = []
        self._device_ready_handler_id = None
        self._device_ready_handler_id = self.client.connect("device-ready", self.on_device_ready)
        self.connect("destroy", self.on_destroy)
        self.connect("action-clicked", self.on_action)

        if self.client.wifi_device:
            GLib.idle_add(self.on_device_ready, self.client, priority=GLib.PRIORITY_DEFAULT_IDLE)


    def on_device_ready(self, client: NetworkClient, *args):
        wifi: Wifi | None = client.wifi_device
        self._disconnect_wifi_service_handlers()

        if wifi:
            self.set_active_style(wifi.get_property("enabled"))
            icon_name_base = wifi.get_property("icon-name")
            if icon_name_base:
                # Assuming icon_name_base from service does NOT include "-symbolic"
                # If it does, remove the "+ '-symbolic'"
                self.action_icon.set_from_icon_name(icon_name_base + "-symbolic", 18)
            else:
                self.action_icon.set_from_icon_name(icons["network"]["wifi"]["generic"] + "-symbolic", 18)

            self.action_label.set_label(" " + wifi.get_property("ssid")) # Added space for consistency

            self._wifi_service_handler_ids.append(
                wifi.connect(
                    "notify::enabled",
                    lambda s, pspec: self.set_active_style(s.get_property("enabled")),
                )
            )
            self._wifi_service_handler_ids.append(
                wifi.connect(
                    "notify::icon-name",
                    lambda s, pspec: self.action_icon.set_from_icon_name(
                        s.get_property("icon-name") + "-symbolic", 18 
                    )
                )
            )
            self._wifi_service_handler_ids.append(
                wifi.connect(
                    "notify::ssid",
                    lambda s, pspec: self.action_label.set_label(" " + s.get_property("ssid"))
                )
            )
        else:
            self.set_active_style(False)
            self.action_icon.set_from_icon_name(icons["network"]["wifi"]["disabled"], 18)
            self.action_label.set_label(" Wifi Unavailable")
        
        # Important for GLib.idle_add: return False to remove the source
        return GLib.SOURCE_REMOVE


    def _disconnect_wifi_service_handlers(self):
        if self.client and self.client.wifi_device and self._wifi_service_handler_ids:
            for handler_id in self._wifi_service_handler_ids:
                try:
                    self.client.wifi_device.disconnect(handler_id)
                except Exception as e:
                    print(f"Error disconnecting wifi service handler {handler_id}: {e}")
            self._wifi_service_handler_ids = []

    def on_destroy(self, *args):
        self._disconnect_wifi_service_handlers()
        if self.client and self._device_ready_handler_id:
            try:
                self.client.disconnect(self._device_ready_handler_id)
            except Exception as e:
                print(f"Error disconnecting device-ready handler {self._device_ready_handler_id}: {e}")
            self._device_ready_handler_id = None

    def on_action(self, btn):
        wifi: Wifi | None = self.client.wifi_device
        if wifi:
            wifi.toggle_wifi()
