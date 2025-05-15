from typing import Any, List, Literal, Dict, Callable
import gi
from fabric.core.service import Property, Service, Signal
from fabric.utils import bulk_connect
from gi.repository import Gio, GLib, GObject
from loguru import logger
import shlex

SETTING_CONNECTION_NAME_STR = "connection"
SETTING_WIRELESS_NAME_STR = "802-11-wireless"
NM80211ApFlags = None

try:
    gi.require_version("NM", "1.0")
    from gi.repository import NM
    if hasattr(NM, "SETTING_CONNECTION_SETTING_NAME"): SETTING_CONNECTION_NAME_STR = NM.SETTING_CONNECTION_SETTING_NAME
    if hasattr(NM, "SETTING_WIRELESS_SETTING_NAME"): SETTING_WIRELESS_NAME_STR = NM.SETTING_WIRELESS_SETTING_NAME
    NM80211ApFlags_candidate = getattr(NM, "80211ApFlags", getattr(NM, "EightZeroTwoElevenApFlags", None))
    if NM80211ApFlags_candidate and hasattr(NM80211ApFlags_candidate, "PRIVACY"): NM80211ApFlags = NM80211ApFlags_candidate
    else:
        logger.warning("NM.\"80211ApFlags\" with .PRIVACY not found. Using fallback.")
        if NM80211ApFlags is None: NM80211ApFlags = type("NM80211ApFlagsDummy", (), {"NONE": 0, "PRIVACY": 1, "__members__": {"NONE":0, "PRIVACY":1}})()
except (ImportError, ValueError, AttributeError) as e: NM = None; logger.error(f"Failed to import or initialize NetworkManager components: {e}")
except Exception as e: logger.error(f"An unexpected error occurred importing NetworkManager: {e}"); NM = None
if NM is None: NM80211ApFlags = type("NM80211ApFlagsDummy", (), {"NONE": 0, "PRIVACY": 1, "__members__": {"NONE":0, "PRIVACY":1}})()

class Wifi(Service):
    @Signal
    def changed(self) -> None: ...

    def __init__(self, client: NM.Client, device: NM.DeviceWifi, **kwargs):
        self._client: NM.Client = client
        self._device: NM.DeviceWifi = device
        self._ap: NM.AccessPoint | None = None
        self._ap_signal_id: int | None = None
        self._is_updating_ap: bool = False 
        self._emit_ap_list_changed_timeout_id: int | None = None
        self._update_ap_notify_timeout_id: int | None = None 
        super().__init__(**kwargs)
        if self._client: self._client.connect("notify::wireless-enabled", self._handle_wireless_enabled_change)
        if self._device and not self._device.is_floating():
            bulk_connect(self._device, {
                "notify::active-access-point": self._on_device_active_ap_changed_service_level,
                "access-point-added": self._schedule_emit_ap_list_changed,
                "access-point-removed": self._schedule_emit_ap_list_changed,
                "state-changed": self._on_device_state_changed_service_level,
            })
            self._schedule_update_active_ap_and_notify()

    def _schedule_update_active_ap_and_notify(self, *args) -> bool:
        if self._update_ap_notify_timeout_id is not None: GLib.source_remove(self._update_ap_notify_timeout_id)
        self._update_ap_notify_timeout_id = GLib.timeout_add(75, self._execute_update_active_ap_and_notify_debounced)
        return True

    def _execute_update_active_ap_and_notify_debounced(self) -> Literal[GLib.SOURCE_REMOVE]:
        self._update_ap_notify_timeout_id = None 
        self._update_active_ap_and_notify()    
        return GLib.SOURCE_REMOVE

    def _handle_wireless_enabled_change(self, source_object: NM.Client, pspec: GObject.ParamSpec) -> bool:
        GLib.idle_add(self.notify, "enabled")
        self._schedule_update_active_ap_and_notify()
        return True

    def _schedule_emit_ap_list_changed(self, *args) -> bool:
       if self._emit_ap_list_changed_timeout_id is not None: GLib.source_remove(self._emit_ap_list_changed_timeout_id)
       self._emit_ap_list_changed_timeout_id = GLib.timeout_add(250, self._execute_emit_ap_list_changed)
       return True 

    def _execute_emit_ap_list_changed(self) -> Literal[GLib.SOURCE_REMOVE]:
       self._emit_changed_and_notify_aps_list()
       self._emit_ap_list_changed_timeout_id = None
       return GLib.SOURCE_REMOVE

    def _emit_changed_and_notify_aps_list(self, *args) -> bool:
        logger.debug("WifiSvc: AP list data changed (debounced). Notifying 'access-points'.")
        self.emit("changed"); GLib.idle_add(self.notify, "access-points") 
        return True

    def _on_device_state_changed_service_level(self, device: NM.Device, new_state, old_state, reason) -> bool:
        self._schedule_update_active_ap_and_notify()
        return True

    def _on_device_active_ap_changed_service_level(self, device: NM.Device, pspec: GObject.ParamSpec) -> bool:
        self._schedule_update_active_ap_and_notify()
        return True
        
    def _update_active_ap_and_notify(self) -> Literal[GLib.SOURCE_REMOVE]:
        if self._is_updating_ap: return GLib.SOURCE_REMOVE 
        self._is_updating_ap = True
        try:
            if not self._device or self._device.is_floating(): self._is_updating_ap = False; return GLib.SOURCE_REMOVE
            old_bssid = self._ap.get_bssid() if self._ap and not self._ap.is_floating() else None
            current_nm_ap = None
            if self.enabled:
                try: current_nm_ap = self._device.get_active_access_point()
                except GLib.Error as e: logger.warning(f"Error getting active AP: {e}")
            if self._ap and self._ap_signal_id and (not current_nm_ap or self._ap != current_nm_ap):
                if not self._ap.is_floating() and GObject.signal_handler_is_connected(self._ap, self._ap_signal_id):
                    try: self._ap.disconnect(self._ap_signal_id)
                    except Exception: pass 
                self._ap_signal_id = None
            self._ap = current_nm_ap 
            new_bssid = self._ap.get_bssid() if self._ap and not self._ap.is_floating() else None
            if old_bssid != new_bssid: logger.trace(f"WifiSvc: Active AP BSSID internally changed. Old: {old_bssid}, New: {new_bssid}")
            if self._ap and not self._ap.is_floating() and (self._ap_signal_id is None or old_bssid != new_bssid):
                try: self._ap_signal_id = self._ap.connect("notify::strength", lambda s,p: self._schedule_update_active_ap_and_notify())
                except Exception: self._ap_signal_id = None 
            self._notify_all_dependent_properties()
        finally: self._is_updating_ap = False
        return GLib.SOURCE_REMOVE

    def _notify_all_dependent_properties(self) -> bool:
        for sn in ["state", "internet", "strength", "ssid", "icon-name", "access-points", "frequency", "enabled"]:
            GLib.idle_add(self.notify, sn)
        self.emit("changed"); return True

    def toggle_wifi(self) -> None:
        if self._client: self._client.wireless_set_enabled(not self._client.wireless_get_enabled())

    def scan(self) -> None:
        if not self._device or self._device.is_floating() or not self.enabled: return
        try:
            logger.info("WifiSvc: Requesting Wi-Fi scan...")
            self._device.request_scan_async(None, self._on_scan_finished)
        except GLib.Error as e: logger.error(f"Error requesting scan: {e}")

    def _on_scan_finished(self, device: NM.DeviceWifi, result: Gio.AsyncResult) -> None:
        if not self._device or self._device.is_floating(): return
        try:
            device.request_scan_finish(result)
            logger.info("WifiSvc: Wi-Fi scan finished.")
        except GLib.Error as e: logger.warning(f"Scan finish error: {e}")
        finally: self._schedule_emit_ap_list_changed()

    @Property(bool, "read-write", default_value=False)
    def enabled(self) -> bool: 
        if self._client: return bool(self._client.wireless_get_enabled())
        return False
    @enabled.setter
    def enabled(self, value: bool) -> None: 
        if self._client: self._client.wireless_set_enabled(value)

    @Property(int, "readable")
    def strength(self) -> int: 
        if self._ap and not self._ap.is_floating(): return self._ap.get_strength()
        return 0 

    @Property(str, "readable")
    def icon_name(self) -> str: 
        if not self.enabled: return "network-wireless-disabled-symbolic"
        internet_state = self.internet
        if internet_state == "activated" and self._ap and not self._ap.is_floating():
            strength_val = self._ap.get_strength()
            if strength_val > 75: s_prefix = "excellent"
            elif strength_val > 55: s_prefix = "good"
            elif strength_val > 30: s_prefix = "ok"
            elif strength_val > 10: s_prefix = "weak"
            else: s_prefix = "none"
            return f"network-wireless-signal-{s_prefix}-symbolic"
        if internet_state == "activating" or self.state in ["prepare", "config", "need_auth", "ip_config", "ip_check"]:
            return "network-wireless-acquiring-symbolic"
        if self.enabled:
            if self.state == "disconnected": return "network-wireless-disconnected-symbolic" 
            return "network-wireless-symbolic" 
        return "network-wireless-offline-symbolic" 

    @Property(int, "readable")
    def frequency(self) -> int: 
        if self._ap and not self._ap.is_floating(): return self._ap.get_frequency()
        return -1

    @Property(str, "readable")
    def internet(self) -> str: 
        if not self._device or self._device.is_floating() or NM is None: return "unknown"
        active_conn = self._device.get_active_connection()
        if not active_conn or active_conn.is_floating():
            dev_state = self._device.get_state()
            if dev_state == NM.DeviceState.DISCONNECTED: return "deactivated"
            if dev_state in [NM.DeviceState.UNAVAILABLE, NM.DeviceState.UNMANAGED]: return "unknown"
            return "deactivated" 
        return {NM.ActiveConnectionState.ACTIVATED:"activated", NM.ActiveConnectionState.ACTIVATING:"activating",
                NM.ActiveConnectionState.DEACTIVATING:"deactivating", NM.ActiveConnectionState.DEACTIVATED:"deactivated",
                NM.ActiveConnectionState.UNKNOWN:"unknown"}.get(active_conn.get_state(), "unknown")

    @Property(object, "readable")
    def access_points(self) -> List[Dict[str, Any]]: 
        if not self._device or self._device.is_floating() or not self.enabled: return []
        if NM is None or NM80211ApFlags is None: return []
        points_raw: List[NM.AccessPoint] = []
        try:
            nm_aps = self._device.get_access_points()
            if nm_aps: points_raw.extend(nm_aps)
        except GLib.Error as e: logger.warning(f"GLib error getting APs: {e}"); return []
        if not points_raw: return []
        processed_aps: List[Dict[str, Any]] = []
        active_ap_bssid_on_service = self._ap.get_bssid() if self._ap and not self._ap.is_floating() else None
        is_currently_activated_for_check = False
        if self._device and not self._device.is_floating() and NM and hasattr(NM, 'ActiveConnectionState') and hasattr(NM, 'DeviceState'):
            active_conn_for_check = self._device.get_active_connection()
            if active_conn_for_check and not active_conn_for_check.is_floating():
                if active_conn_for_check.get_state() == NM.ActiveConnectionState.ACTIVATED: is_currently_activated_for_check = True
            elif self._device.get_state() == NM.DeviceState.ACTIVATED: is_currently_activated_for_check = True
        for ap in points_raw:
            if not ap or ap.is_floating(): continue
            ssid_gbytes = ap.get_ssid()
            ssid_str = NM.utils_ssid_to_utf8(ssid_gbytes.get_data()) if ssid_gbytes and ssid_gbytes.get_data() else "Unknown"
            is_secure = bool(ap.get_flags() & NM80211ApFlags.PRIVACY)
            strength, ap_bssid = ap.get_strength(), ap.get_bssid()
            icon_suffix = "excellent" if strength >= 75 else "good" if strength >= 55 else "ok" if strength >= 30 else "weak" if strength >= 10 else "none"
            ap_icon_name = f"network-wireless-signal-{icon_suffix}-symbolic"
            if icon_suffix == "none": ap_icon_name = "network-wireless-signal-none-symbolic"
            is_active = (active_ap_bssid_on_service == ap_bssid and is_currently_activated_for_check)
            processed_aps.append({
                "bssid": ap_bssid, "ssid": ssid_str, "is_secure": is_secure, "strength": strength, 
                "icon-name": ap_icon_name, "active_ap": is_active, "flags": ap.get_flags(), 
                "wpa_flags": ap.get_wpa_flags(), "rsn_flags": ap.get_rsn_flags(),
                "last_seen": ap.get_last_seen(), "frequency": ap.get_frequency(),
            })
        return processed_aps

    @Property(str, "readable")
    def ssid(self) -> str: 
        if self._ap and not self._ap.is_floating():
            ssid_gbytes = self._ap.get_ssid()
            if ssid_gbytes and ssid_gbytes.get_data() and NM:
                res_ssid = NM.utils_ssid_to_utf8(ssid_gbytes.get_data())
                return res_ssid if res_ssid else "SSID Error"
        if self.enabled and self.internet == "activated": return "Connected" 
        return "Disconnected"

    @Property(str, "readable")
    def state(self) -> str:
        if not self._device or self._device.is_floating() or NM is None: return "unknown"
        state_val = self._device.get_state()
        state_map = {NM.DeviceState.UNMANAGED:"unmanaged",NM.DeviceState.UNAVAILABLE:"unavailable",
                     NM.DeviceState.DISCONNECTED:"disconnected",NM.DeviceState.PREPARE:"prepare",
                     NM.DeviceState.CONFIG:"config",NM.DeviceState.NEED_AUTH:"need_auth",
                     NM.DeviceState.IP_CONFIG:"ip_config",NM.DeviceState.IP_CHECK:"ip_check",
                     NM.DeviceState.SECONDARIES:"secondaries",NM.DeviceState.ACTIVATED:"activated",
                     NM.DeviceState.DEACTIVATING:"deactivating",NM.DeviceState.FAILED:"failed",
                     NM.DeviceState.UNKNOWN:"unknown"}
        return state_map.get(state_val, f"unknown_{state_val}")

    def cleanup_signals_custom(self) -> None:
        if self._emit_ap_list_changed_timeout_id is not None: GLib.source_remove(self._emit_ap_list_changed_timeout_id)
        if self._update_ap_notify_timeout_id is not None: GLib.source_remove(self._update_ap_notify_timeout_id)
        if self._ap and self._ap_signal_id and not self._ap.is_floating() and GObject.signal_handler_is_connected(self._ap, self._ap_signal_id):
            try: self._ap.disconnect(self._ap_signal_id)
            except Exception: pass
        self._emit_ap_list_changed_timeout_id = self._update_ap_notify_timeout_id = self._ap_signal_id = None

class Ethernet(Service):
    @Signal
    def changed(self) -> None: ...
    @Signal
    def enabled(self) -> bool: ...
    
    @Property(int, "readable")
    def speed(self) -> int:
        if self._device and not self._device.is_floating(): return self._device.get_speed()
        return 0
    
    @Property(str, "readable")
    def internet(self) -> str:
        if not self._device or self._device.is_floating() or NM is None: return "disconnected"
        active_conn = self._device.get_active_connection()
        if not active_conn or active_conn.is_floating(): return "disconnected"
        return {
            NM.ActiveConnectionState.ACTIVATED: "activated", NM.ActiveConnectionState.ACTIVATING: "activating",
            NM.ActiveConnectionState.DEACTIVATING: "deactivating", NM.ActiveConnectionState.DEACTIVATED: "deactivated",
            NM.ActiveConnectionState.UNKNOWN: "unknown",
        }.get(active_conn.get_state(), "disconnected")

    @Property(str, "readable")
    def icon_name(self) -> str:
        conn_state = self.internet
        if conn_state == "activated": return "network-wired-symbolic"
        elif conn_state == "activating": return "network-wired-acquiring-symbolic"
        has_carrier = self._device.get_carrier() if self._device and not self._device.is_floating() else False
        if not has_carrier: return "network-wired-disconnected-symbolic"
        return "network-wired-no-route-symbolic"

    def __init__(self, client: NM.Client, device: NM.DeviceEthernet, **kwargs) -> None:
        super().__init__(**kwargs)
        self._client: NM.Client = client
        self._device: NM.DeviceEthernet = device
        self._signal_ids: List[Dict[str, Any]] = []
        if self._device and not self._device.is_floating():
            props_to_watch = ["active-connection", "carrier", "hw-address", "lldp-neighbors", "s390-subchannels", "speed", "state"]
            for name in props_to_watch:
                sig_id = self._device.connect(f"notify::{name}", lambda s, p, n=name: self.notifier(n))
                self._signal_ids.append({"obj": self._device, "id": sig_id})
            active_conn = self._device.get_active_connection()
            if active_conn and not active_conn.is_floating():
                sig_id = active_conn.connect("notify::state", lambda s,p: self.notifier("internet"))
                self._signal_ids.append({"obj": active_conn, "id": sig_id})

    def notifier(self, name: str) -> None:
        self.notify(name)
        if name in ["active-connection", "state", "carrier"]:
             GLib.idle_add(self.notify, "internet"); GLib.idle_add(self.notify, "icon-name")
        if name == "speed": GLib.idle_add(self.notify, "speed")
        self.emit("changed")

    def cleanup_signals(self) -> None:
        for sig_entry in self._signal_ids:
            obj, sig_id = sig_entry["obj"], sig_entry["id"]
            if obj and not obj.is_floating() and GObject.signal_handler_is_connected(obj, sig_id): 
                try: obj.disconnect(sig_id)
                except Exception: pass
        self._signal_ids = []

class NetworkClient(Service):
    @Signal
    def device_ready(self) -> None: ...

    def __init__(self, **kwargs):
        self._client: NM.Client | None = None
        self.wifi_device: Wifi | None = None
        self.ethernet_device: Ethernet | None = None
        self._nm_signal_ids: List[int] = []
        super().__init__(**kwargs)
        if NM and hasattr(NM.Client, "new_async"):
            NM.Client.new_async(None, self._init_network_client) # type: ignore
        else:
            logger.error("NM bindings unavailable. Network functionality disabled.")
            GLib.idle_add(self.emit, "device-ready")

    def _init_network_client(self, source_object: GObject.Object | None, task: Gio.Task, **kwargs) -> None:
        try:
            if NM is None or not hasattr(NM, "Client"): 
                raise GLib.Error(domain="NetworkClient", code=1, message="NM module or NM.Client not loaded")
            self._client = NM.Client.new_finish(task)
            logger.info("NetworkManager client initialized.")
        except GLib.Error as e:
            logger.error(f"Failed to initialize NM.Client: {e}")
            GLib.idle_add(self.emit, "device-ready"); return
        
        self._setup_devices()
        if self._client:
            sig_con = self._client.connect
            self._nm_signal_ids.extend([
                sig_con("device-added", self._on_device_added_or_removed),
                sig_con("device-removed", self._on_device_added_or_removed),
                sig_con("notify::primary-connection", lambda c,p: GLib.idle_add(self.notify,"primary-device")),
                sig_con("notify::wireless-enabled", self._handle_wireless_enabled_change),
                sig_con("notify::connectivity", self._handle_connectivity_change)
            ])
        GLib.idle_add(self.emit, "device-ready")
        GLib.idle_add(self.notify, "primary-device")

    def _handle_wireless_enabled_change(self, client: NM.Client, pspec: GObject.ParamSpec) -> None:
        if self.wifi_device:
            self.wifi_device._schedule_update_active_ap_and_notify()

    def _handle_connectivity_change(self, client: NM.Client, pspec: GObject.ParamSpec) -> None:
        if self.wifi_device: self.wifi_device._schedule_update_active_ap_and_notify()
        if self.ethernet_device: GLib.idle_add(self.ethernet_device.notifier, "internet")

    def _setup_devices(self) -> None:
        if not self._client or NM is None or not hasattr(NM, "DeviceType"): return
        all_devices = self._client.get_devices()
        nm_wifi_devices = [dev for dev in all_devices if dev.get_device_type() == NM.DeviceType.WIFI]
        nm_eth_devices = [dev for dev in all_devices if dev.get_device_type() == NM.DeviceType.ETHERNET]
        new_wifi_nm_device: NM.DeviceWifi | None = nm_wifi_devices[0] if nm_wifi_devices else None
        new_eth_nm_device: NM.DeviceEthernet | None = nm_eth_devices[0] if nm_eth_devices else None
        wifi_device_changed, eth_device_changed = False, False

        current_wifi_nm_device = self.wifi_device._device if self.wifi_device else None
        if new_wifi_nm_device != current_wifi_nm_device:
            old_iface = self.wifi_device._device.get_iface() if self.wifi_device and hasattr(self.wifi_device._device, 'get_iface') else 'N/A'
            if self.wifi_device: self.wifi_device.cleanup_signals_custom(); self.wifi_device = None
            if new_wifi_nm_device:
                self.wifi_device = Wifi(self._client, new_wifi_nm_device)
                logger.info(f"NetworkClient: Wi-Fi device changed from '{old_iface}' to '{new_wifi_nm_device.get_iface()}'.")
            else: logger.info(f"NetworkClient: Wi-Fi device '{old_iface}' removed.")
            wifi_device_changed = True

        current_eth_nm_device = self.ethernet_device._device if self.ethernet_device else None
        if new_eth_nm_device != current_eth_nm_device:
            old_iface = self.ethernet_device._device.get_iface() if self.ethernet_device and hasattr(self.ethernet_device._device, 'get_iface') else 'N/A'
            if self.ethernet_device: self.ethernet_device.cleanup_signals(); self.ethernet_device = None
            if new_eth_nm_device:
                self.ethernet_device = Ethernet(client=self._client, device=new_eth_nm_device)
                logger.info(f"NetworkClient: Ethernet device changed from '{old_iface}' to '{new_eth_nm_device.get_iface()}'.")
            else: logger.info(f"NetworkClient: Ethernet device '{old_iface}' removed.")
            eth_device_changed = True
        
        if wifi_device_changed or eth_device_changed:
            GLib.idle_add(self.emit, "device-ready")

    def _on_device_added_or_removed(self, client: NM.Client, device: NM.Device) -> None:
        is_added = bool(client.get_device_by_iface(device.get_iface())) if hasattr(device, 'get_iface') else False
        iface = device.get_iface() if hasattr(device, 'get_iface') else 'UnknownIface'
        logger.info(f"NetworkClient: NM Device {'added' if is_added else 'removed'}: {iface}")
        GLib.idle_add(self._setup_devices)
        GLib.idle_add(self.notify, "primary-device")

    def _get_primary_device(self) -> Literal["wifi", "wired"] | None:
        if not self._client: return None
        primary_conn = self._client.get_primary_connection()
        if not primary_conn or primary_conn.is_floating():
            if self.wifi_device and self.wifi_device.enabled and self.wifi_device.internet == "activated": return "wifi"
            if self.ethernet_device and self.ethernet_device.internet == "activated": return "wired"
            if self.wifi_device and self.wifi_device.enabled: return "wifi" 
            return None
        conn_type_str = primary_conn.get_connection_type()
        if "wireless" in conn_type_str: return "wifi"
        elif "ethernet" in conn_type_str: return "wired"
        return None

    def get_wifi_profiles(self) -> Dict[str, Dict[str, str]]:
        profiles: Dict[str, Dict[str, str]] = {}
        if not self._client or NM is None or not hasattr(NM, "RemoteConnection"): return profiles
        connections = self._client.get_connections() 
        for remote_conn in connections: 
            if remote_conn.is_floating(): continue
            try:
                s_connection = remote_conn.get_setting_connection()
                s_wifi = remote_conn.get_setting_wireless()
                if s_connection and s_wifi and s_connection.props.type == SETTING_WIRELESS_NAME_STR:
                    profile_name, profile_uuid = s_connection.props.id, s_connection.props.uuid
                    ssid_gbytes = s_wifi.props.ssid 
                    ssid = NM.utils_ssid_to_utf8(ssid_gbytes.get_data()) if ssid_gbytes and ssid_gbytes.get_data() else None
                    if ssid and profile_name and profile_uuid: 
                        profiles[ssid] = {"uuid": profile_uuid, "name": profile_name}
            except Exception as e:
                conn_id = remote_conn.get_id() if hasattr(remote_conn, "get_id") else "Unknown"
                logger.error(f"Error processing Wi-Fi profile ({conn_id}): {e}")
        return profiles

    def _execute_nmcli_command(self, cmd_parts: List[str], masked_cmd_for_log: str) -> None:
        logger.info(f"Executing: {masked_cmd_for_log}")
        try:
            proc = Gio.Subprocess.new(cmd_parts, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
            proc.communicate_async(None, None, self._on_nmcli_command_finish, masked_cmd_for_log)
        except GLib.Error as e:
            logger.error(f"Failed to spawn nmcli process for '{masked_cmd_for_log}': {e}.")
            if self.wifi_device: self.wifi_device.scan()

    def _on_nmcli_command_finish(self, proc: Gio.Subprocess, result: Gio.AsyncResult, masked_cmd_for_log: str) -> None:
        try:
            cmd_success, stdout_bytes, stderr_bytes = proc.communicate_finish(result)
            stdout = stdout_bytes.get_data().decode(errors='replace').strip() if stdout_bytes else ""
            stderr = stderr_bytes.get_data().decode(errors='replace').strip() if stderr_bytes else ""
            fail_patterns = ["Error: Connection activation failed", "Error: Secrets were required", 
                             "Error: 802-11-wireless-security.key-mgmt", "No network with SSID", 
                             "No connection profile found", "Connection .* not found"]
            is_fail = any(patt in stderr for patt in fail_patterns) or \
                      (not stdout and "successfully activated" not in stdout.lower() and stderr)
            if cmd_success and not is_fail: 
                logger.info(f"nmcli '{masked_cmd_for_log}' successful. STDOUT='{stdout}'")
                if stderr: logger.info(f"nmcli '{masked_cmd_for_log}' STDERR (though successful): '{stderr}'")
            else: 
                logger.error(f"nmcli '{masked_cmd_for_log}' failed. Exit success: {cmd_success}, STDOUT='{stdout}', STDERR='{stderr}'")
        except GLib.Error as e: logger.error(f"GLib error processing nmcli result for '{masked_cmd_for_log}': {e}")
        except Exception as e: logger.error(f"Unexpected error processing nmcli result for '{masked_cmd_for_log}': {e}")

    def activate_wifi_profile(self, profile_id: str) -> None:
        self._execute_nmcli_command(["nmcli", "connection", "up", profile_id], f"nmcli connection up '{shlex.quote(profile_id)}'")

    def connect_new_wifi_with_password(self, bssid: str, ssid: str, password: str) -> None:
        cmd = ["nmcli", "device", "wifi", "connect", bssid]
        if ssid and ssid != "Unknown": cmd.extend(["name", ssid])
        cmd.extend(["password", password])
        self._execute_nmcli_command(cmd, f"nmcli device wifi connect '{shlex.quote(bssid)}' name '{shlex.quote(ssid)}' password ********")

    def connect_open_wifi(self, bssid: str, ssid: str) -> None:
        cmd = ["nmcli", "device", "wifi", "connect", bssid]
        if ssid and ssid != "Unknown": cmd.extend(["name", ssid])
        self._execute_nmcli_command(cmd, f"nmcli device wifi connect '{shlex.quote(bssid)}' name '{shlex.quote(ssid)}'")

    def initiate_wifi_connection(self, ap_data: dict, password_prompt_needed_callback: Callable[[Dict[str, Any]], None]) -> None:
        ap_ssid, ap_bssid = ap_data.get("ssid"), ap_data.get("bssid")
        is_secure = ap_data.get("is_secure", False)
        logger.info(f"NetworkClient: Initiating Wi-Fi connection for SSID: {ap_ssid} (BSSID: {ap_bssid})")

        if not ap_ssid or ap_ssid == "Unknown" or not ap_bssid:
            logger.warning(f"NetworkClient: Invalid AP data provided: {ap_data}. Aborting."); return
        
        if self.wifi_device and self.wifi_device.enabled and self.wifi_device._ap and \
           not self.wifi_device._ap.is_floating() and self.wifi_device._ap.get_bssid() == ap_bssid and \
           self.wifi_device.internet == "activated":
            logger.info(f"Already active on selected BSSID {ap_bssid} ({ap_ssid})."); return
        
        known_profiles = self.get_wifi_profiles()
        profile_info = known_profiles.get(ap_ssid)

        if profile_info and (profile_id_to_use := profile_info.get("uuid") or profile_info.get("name")):
            logger.info(f"Found existing profile for SSID '{ap_ssid}': {profile_id_to_use}. Attempting to activate.")
            self.activate_wifi_profile(profile_id_to_use)
            return

        logger.info(f"No usable existing profile found for SSID '{ap_ssid}'. Proceeding as new connection attempt.")
        if is_secure:
            password_prompt_needed_callback(ap_data)
        else:
            self.connect_open_wifi(ap_bssid, ap_ssid)
            
    @Property(str, "readable")
    def primary_device(self) -> Literal["wifi", "wired"] | None: return self._get_primary_device()

    def cleanup(self) -> None:
        if self._client and self._nm_signal_ids:
            for sig_id in self._nm_signal_ids:
                if GObject.signal_handler_is_connected(self._client, sig_id):
                    try: self._client.disconnect(sig_id)
                    except Exception: pass
            self._nm_signal_ids = []
        if self.ethernet_device: self.ethernet_device.cleanup_signals()
        if self.wifi_device: self.wifi_device.cleanup_signals_custom()

if NM is None:
    class NMProxyFallback: pass
    NM = NMProxyFallback()
if NM80211ApFlags is None:
    NM80211ApFlags = type("NM80211ApFlagsDummy", (), {"NONE": 0, "PRIVACY": 1, "__members__": {"NONE":0, "PRIVACY":1}})()
if not (hasattr(NM, 'Client') and isinstance(NM, type(NM.Client if hasattr(NM, 'Client') else object))):
    class NMProxyMeta(type):
        def __getattr__(cls, name):
            if name == SETTING_CONNECTION_NAME_STR: return "connection"
            if name == SETTING_WIRELESS_NAME_STR: return "802-11-wireless"
            if name == "80211ApFlags" or name == "EightZeroTwoElevenApFlags" or name == "ApFlags":
                return type(name, (), {"NONE": 0, "PRIVACY": 1, "__members__": {"NONE":0, "PRIVACY":1}})()
            if name in ["Client", "DeviceWifi", "AccessPoint", "DeviceEthernet", "SettingWireless", "SettingConnection",
                        "ActiveConnectionState", "ConnectivityState", "DeviceState", "Device", 
                        "WpaFlags", "RsnFlags", "DeviceType", "RemoteConnection"]:
                dummy_s_conn_props = {"id":"dummy_id", "uuid":"dummy_uuid", "type":"802-11-wireless"}
                dummy_s_conn = type("SettingConnection", (), {"props": type("Props", (), dummy_s_conn_props)()})()
                dummy_s_wifi_props = {"ssid": GLib.Bytes.new(b"dummy_ssid") if GLib else None}
                dummy_s_wifi = type("SettingWireless", (), {"props": type("Props", (), dummy_s_wifi_props)()})()
                dummy_methods = { "is_floating": lambda: True, "get_id": lambda: "dummy_id",
                                  "get_setting_connection": lambda: dummy_s_conn if name == "RemoteConnection" else None,
                                  "get_setting_wireless": lambda: dummy_s_wifi if name == "RemoteConnection" else None }
                if name == "Device": dummy_methods["get_iface"] = lambda: "dummyiface"
                dummy_class = type(name, (object,), dummy_methods) 
                return dummy_class
            elif name == "utils_ssid_to_utf8":
                return lambda data: data.decode(errors='replace').strip() if data else "Unknown"
            raise AttributeError(f"'{cls.__name__}' object has no attribute '{name}' (type: {type(cls)})")
    class NMProxy(metaclass=NMProxyMeta): pass
    if not hasattr(NM, 'Client'): NM = NMProxy()
    if NM80211ApFlags is not None and hasattr(NM80211ApFlags, "__members__") and "PRIVACY" not in NM80211ApFlags.__members__:
         NM80211ApFlags = getattr(NM, "80211ApFlags", type("NM80211ApFlagsDummy", (), {"NONE": 0, "PRIVACY": 1, "__members__": {"NONE":0, "PRIVACY":1}})())

network_service = NetworkClient()
