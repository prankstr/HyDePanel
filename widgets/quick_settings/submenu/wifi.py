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
        # Keep the new connect name, the method body will be updated
        self._device_ready_handler_id = self.client.connect("device-ready", self.on_device_ready)

        self.available_networks_box = Box(orientation="v", spacing=4, h_expand=True)

        # Assuming ScanButton import path is correct in the new structure
        self.scan_button = ScanButton()
        self.scan_button.connect("clicked", self.start_new_scan)

        self.child = ScrolledWindow(
            min_content_size=(-1, 190),
            max_content_size=(-1, 190),
            propagate_width=True,
            propagate_height=True,
            child=self.available_networks_box,
        )

        # Keep the new title_icon from the icons dict
        super().__init__(
            title="Network",
            title_icon=icons["network"]["wifi"]["generic"],
            scan_button=self.scan_button,
            # Keep the new child structure (directly the ScrolledWindow)
            child=self.child,
            **kwargs,
        )

        # Attempt to build options immediately if device is ready on init
        if self.client.wifi_device:
             self.build_wifi_options()


    def start_new_scan(self, _):
        # Add a check for the scan_button itself to prevent double-animation if clicked rapidly
        if self.scan_button.get_sensitive():
            self.client.wifi_device.scan() if self.client.wifi_device else None
            # Build options *after* scan completes, maybe? Or just trigger build to show old list + animation
            # For now, keeping old behavior of building immediately after scan() call
            self.build_wifi_options()
            self.scan_button.play_animation()

    # Renamed from on_client_device_ready in old, matching new signal name
    def on_device_ready(self, client: NetworkClient, *args):
        # Set wifi_device attribute
        self.wifi_device = client.wifi_device
        # Build wifi options list
        self.build_wifi_options()

    def build_wifi_options(self):
        # Clear existing list
        self.available_networks_box.children = []
        # Check if wifi device is available
        if not self.wifi_device:
            # Optionally add a "Wifi unavailable" label
            unavailable_label = Label(label="Wifi device unavailable", name="wifi-unavailable-label")
            self.available_networks_box.add(unavailable_label)
            return
        # Get access points
        access_points = self.wifi_device.access_points # Assuming this list is available when build_wifi_options is called
        if not access_points:
             # Optionally add a "No networks found" label
            no_networks_label = Label(label="No networks found", name="wifi-no-networks-label")
            self.available_networks_box.add(no_networks_label)
            return

        # Build buttons for available networks
        for ap in access_points:
            # Ensure ssid is present and not "Unknown"
            ssid = ap.get("ssid")
            if ssid and ssid != "Unknown":
                btn = self.make_button_from_ap(ap)
                self.available_networks_box.add(btn)

    def make_button_from_ap(self, ap) -> Button:
        # Use get() with default None to avoid KeyError
        ssid = ap.get("ssid", "Unknown")
        icon_name = ap.get("icon-name")

        ap_button = Button(style_classes="submenu-button", name="wifi-ap-button")
        ap_button.add(
            Box(
                style="padding: 5px;",
                children=[
                    # Use the icon name provided by the service
                    Image(
                        icon_name=icon_name if icon_name else icons["network"]["wifi"]["generic"], # Fallback icon
                        icon_size=18,
                    ),
                    Label(label=ssid, style_classes="submenu-item-label"),
                ],
            )
        )
        # Ensure bssid is available before connecting signal
        bssid = ap.get("bssid")
        if bssid:
            ap_button.connect(
                "clicked", lambda _, ap_bssid=bssid: self.client.connect_wifi_bssid(ap_bssid)
            )
        # Add tooltip showing BSSID for debugging/info
        ap_button.set_tooltip_text(f"SSID: {ssid}\nBSSID: {bssid}\nIcon: {icon_name}")

        return ap_button


class WifiToggle(QSChevronButton):
    """A widget to display a toggle button for Wifi."""

    def __init__(self, submenu: QuickSubMenu, **kwargs):
        # Initial placeholder icon/label will be updated by on_device_ready
        # Using a disabled/generic state is reasonable here.
        super().__init__(
            action_icon=icons["network"]["wifi"]["disabled"], # Use disabled icon initially
            action_label=" Wifi", # Just "Wifi" initially
            submenu=submenu,
            **kwargs,
        )
        self.client = network_service

        # List to store signal handler IDs from the Wifi device
        self._wifi_service_handler_ids = []
        # Store the handler ID for the network_service "device-ready" signal
        self._device_ready_handler_id = None

        # Connect to the "device-ready" signal from the network service
        # This signal indicates that network devices (like wifi) are available
        self._device_ready_handler_id = self.client.connect("device-ready", self.on_device_ready)

        # Connect to the "destroy" signal of the widget for cleanup
        self.connect("destroy", self.on_destroy)

        # Connect the signal for the toggle action
        self.connect("action-clicked", self.on_action)

        # --- Start of fix: Handle case where device is already ready ---
        # It's possible the network service initialized and emitted "device-ready"
        # before this widget was fully created and connected the signal.
        # Check if the wifi_device is already available and call the handler manually.
        # Use GLib.idle_add to ensure GTK widget is fully realized before updating properties
        # or connecting signals on the underlying service object.
        if self.client.wifi_device:
             GLib.idle_add(self.on_device_ready, self.client)
        # --- End of fix ---


    # This method is called when the network_service emits "device-ready"
    # or manually from __init__ if the device is already ready.
    # It sets up signal handlers on the actual Wifi device object.
    # Renamed from on_client_device_ready in old, matching new signal name
    def on_device_ready(self, client: NetworkClient, *args):
        # Get the Wifi device object from the client
        wifi: Wifi | None = client.wifi_device

        # --- Start of fix: Disconnect old handlers and set state based on current wifi device ---
        # Disconnect any handlers from a previous Wifi device instance
        self._disconnect_wifi_service_handlers()

        if wifi:
            # Set the initial state based on the current properties of the wifi device
            # This replaces the problematic connect() call and the bind_property calls from the original new code

            # Set active style based on enabled state
            self.set_active_style(wifi.get_property("enabled"))

            # Set the initial icon. The old code added "-symbolic".
            # Let's assume the service provides a base name like "network-wireless" or "network-wireless-signal-good"
            # and we need to add "-symbolic". If the service *already* provides symbolic names, remove the "+ '-symbolic'".
            # Sticking to the working old code's pattern:
            icon_name_base = wifi.get_property("icon-name")
            if icon_name_base:
                 self.action_icon.set_from_icon_name(icon_name_base + "-symbolic", 18)
            else:
                 # Fallback if icon-name property is not set initially
                 self.action_icon.set_from_icon_name(icons["network"]["wifi"]["generic"] + "-symbolic", 18) # Or disabled?

            # Set the initial label (SSID)
            self.action_label.set_label(wifi.get_property("ssid"))

            # Connect signals to update the widget when wifi properties change
            # Store the handler IDs so we can disconnect them later

            # Handler for enabled state changes (updates button style)
            self._wifi_service_handler_ids.append(
                wifi.connect(
                    "notify::enabled",
                    # Use lambda to call set_active_style with the new enabled state when the signal fires
                    lambda s, pspec: self.set_active_style(s.get_property("enabled")),
                )
            )
            # Handler for icon-name changes
            self._wifi_service_handler_ids.append(
                wifi.connect(
                    "notify::icon-name",
                    # Use lambda to update the icon when the signal fires
                    lambda s, pspec: self.action_icon.set_from_icon_name(
                        s.get_property("icon-name") + "-symbolic", 18 # Keep adding -symbolic like old code
                    )
                )
            )
            # Handler for ssid changes
            self._wifi_service_handler_ids.append(
                wifi.connect(
                    "notify::ssid",
                    # Use lambda to update the label when the signal fires
                    lambda s, pspec: self.action_label.set_label(s.get_property("ssid"))
                )
            )
        else:
            # Wifi device is not available (e.g., no wifi adapter or device not found by NetworkManager)
            # Reset the widget to a disabled/unavailable state
            self.set_active_style(False) # Not active
            self.action_icon.set_from_icon_name(icons["network"]["wifi"]["disabled"], 18) # Disabled icon
            self.action_label.set_label(" Wifi Unavailable") # Indicate unavailability
        # --- End of fix ---

        # Return False to remove the idle source if it was called from GLib.idle_add
        return False


    # --- Start of fix: Methods for handler management ---
    # Disconnects all signal handlers connected to the Wifi device
    def _disconnect_wifi_service_handlers(self):
        # Check if we have a wifi device and handler IDs to disconnect
        if self.client and self.client.wifi_device and self._wifi_service_handler_ids:
            # Disconnect each handler by its ID
            for handler_id in self._wifi_service_handler_ids:
                try:
                    # Safely disconnect the signal
                    self.client.wifi_device.disconnect(handler_id)
                except Exception as e:
                    # Handle cases where handler_id might already be disconnected or invalid
                    print(f"Error disconnecting wifi service handler {handler_id}: {e}")
            # Clear the list of handler IDs
            self._wifi_service_handler_ids = []

    # Called when the widget is destroyed. Cleans up signal connections.
    def on_destroy(self, *args):
        # Disconnect handlers from the Wifi device
        self._disconnect_wifi_service_handlers()
        # Disconnect the handler from the network_service "device-ready" signal
        if self.client and self._device_ready_handler_id:
            try:
                self.client.disconnect(self._device_ready_handler_id)
            except Exception as e:
                 print(f"Error disconnecting device-ready handler {self._device_ready_handler_id}: {e}")
            self._device_ready_handler_id = None
    # --- End of fix ---


    # Called when the action part of the button is clicked
    def on_action(self, btn):
        # Get the current Wifi device object
        wifi: Wifi | None = self.client.wifi_device
        # If the wifi device exists, toggle its enabled state
        if wifi:
            wifi.toggle_wifi()
