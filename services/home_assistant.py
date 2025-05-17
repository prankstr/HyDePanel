import sys
import threading
import time
from pathlib import Path

import gi
import httpx

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, GObject  # noqa: E402

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


class HomeAssistantLight(GObject.Object):
    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, entity_id, name, state, attributes=None):
        super().__init__()
        self.entity_id = entity_id
        self._name = name
        self._state = state
        self._attributes = attributes if attributes is not None else {}

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        if self._state != value:
            self._state = value
            GLib.idle_add(self.emit, "state-changed")

    @property
    def is_on(self):
        return self._state == "on"


class HomeAssistantService(GObject.Object):
    __gsignals__ = {
        "lights-updated": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "master-state-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "service-availability-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }

    def __init__(self, ha_specific_config: dict | None):
        super().__init__()

        self._base_url = None
        self._token = None
        self._entity_ids = []
        self._request_timeout = 5
        self._poll_interval_seconds = 30
        self._headers = {}
        self._client = None
        self._lights = {}
        self._polling_thread = None
        self._stop_polling = threading.Event()
        self._service_available = False
        self._initial_refresh_done = False

        if not ha_specific_config:
            print(
                "CRITICAL: HomeAssistantService initialized with no 'home_assistant' configuration. Service will be non-functional."
            )
            GLib.idle_add(self._emit_initial_unavailable_state)
            return

        self._base_url = ha_specific_config.get("url")
        self._token = ha_specific_config.get("token")
        self._entity_ids = ha_specific_config.get("entities", [])
        try:
            self._request_timeout = int(ha_specific_config.get("request_timeout", 5))
        except (ValueError, TypeError):
            print(
                f"Warning: Invalid request_timeout value '{ha_specific_config.get('request_timeout')}', using default 5s."
            )
            self._request_timeout = 5
        try:
            self._poll_interval_seconds = int(
                ha_specific_config.get("poll_interval", 30)
            )
        except (ValueError, TypeError):
            print(
                f"Warning: Invalid poll_interval value '{ha_specific_config.get('poll_interval')}', using default 30s."
            )
            self._poll_interval_seconds = 30

        if not self._base_url or not self._token:
            print(
                "CRITICAL: Home Assistant URL or Token is missing in the 'home_assistant' configuration section. Service will be non-functional."
            )
            GLib.idle_add(self._emit_initial_unavailable_state)
            return

        self._base_url = self._base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "content-type": "application/json",
        }

        try:
            self._client = httpx.Client(
                base_url=self._base_url,
                headers=self._headers,
                timeout=self._request_timeout,
                verify=False,
            )
        except Exception as e:
            print(
                f"CRITICAL: Failed to initialize httpx client for Home Assistant: {e}. Service will be non-functional."
            )
            self._client = None
            GLib.idle_add(self._emit_initial_unavailable_state)
            return

        if self._entity_ids:
            self._start_threaded_task(self.refresh_all_lights_threaded_target)
            self.start_polling()
        else:
            print(
                "HomeAssistantService: No entities configured. Will attempt an initial API availability check."
            )
            self._start_threaded_task(self._check_service_availability_once)
            GLib.idle_add(self.emit, "lights-updated")
            GLib.idle_add(self.emit, "master-state-changed", False)

    def _emit_initial_unavailable_state(self):
        self.emit("service-availability-changed", False)
        self.emit("master-state-changed", False)
        self.emit("lights-updated")
        self._initial_refresh_done = True
        return False

    def _check_service_availability_once(self):
        if not self._client:
            self._set_service_availability(False)
            if not self._initial_refresh_done:
                self._initial_refresh_done = True
            return
        try:
            response = self._client.get("/api/")
            response.raise_for_status()
            print(
                "HomeAssistantService: Successfully connected to Home Assistant API (initial check)."
            )
            self._set_service_availability(True)
        except Exception as e:
            print(
                f"HomeAssistantService: Failed to connect to Home Assistant API (initial check): {e}"
            )
            self._set_service_availability(False)
        finally:
            if not self._initial_refresh_done:
                self._initial_refresh_done = True

    def _set_service_availability(self, available: bool):
        if self._service_available != available:
            self._service_available = available
            GLib.idle_add(self.emit, "service-availability-changed", available)
            if not available:
                GLib.idle_add(self.emit, "master-state-changed", False)
                GLib.idle_add(self.emit, "lights-updated")

    def _fetch_light_state_sync(self, entity_id):
        if not self._client:
            self._set_service_availability(False)
            return None
        try:
            response = self._client.get(f"/api/states/{entity_id}")
            response.raise_for_status()
            self._set_service_availability(True)
            return response.json()
        except httpx.TimeoutException:
            print(
                f"HA Timeout fetching {entity_id} (timeout: {self._request_timeout}s)"
            )
            self._set_service_availability(False)
        except httpx.HTTPStatusError as e:
            print(
                f"HA API Error fetching {entity_id}: {e.response.status_code} - {e.response.text}"
            )
            self._set_service_availability(e.response.status_code < 500)
        except httpx.RequestError as e:
            print(f"HA Request Error fetching {entity_id}: {e}")
            self._set_service_availability(False)
        except Exception as e:
            print(f"HA Generic error fetching {entity_id}: {e}")
            self._set_service_availability(False)
        return None

    def _process_fetched_data_in_main_thread(self, entity_id, data):
        light_obj_updated = False
        if data:
            name = data.get("attributes", {}).get("friendly_name", entity_id)
            state = data.get("state")
            attributes = data.get("attributes")

            if entity_id not in self._lights:
                self._lights[entity_id] = HomeAssistantLight(
                    entity_id, name, state, attributes
                )
                light_obj_updated = True
            else:
                light = self._lights[entity_id]
                if (
                    light.state != state
                    or light._name != name
                    or light._attributes != attributes
                ):
                    light.state = state
                    light._name = name
                    light._attributes = attributes
                    light_obj_updated = True
        return light_obj_updated

    def _fetch_and_process_one_light_target(self, entity_id):
        data = self._fetch_light_state_sync(entity_id)
        GLib.idle_add(self._handle_single_light_update_results, entity_id, data)

    def _handle_single_light_update_results(self, entity_id, data):
        was_light_gobject_updated = self._process_fetched_data_in_main_thread(
            entity_id, data
        )
        if was_light_gobject_updated:
            GLib.idle_add(self.emit, "lights-updated")
        GLib.idle_add(self.emit, "master-state-changed", self.get_master_state())
        return False

    def refresh_all_lights_threaded_target(self):
        if not self._client:
            self._set_service_availability(False)
            if not self._initial_refresh_done:
                self._initial_refresh_done = True
            return

        if not self._entity_ids:
            if not self._initial_refresh_done:
                self._start_threaded_task(self._check_service_availability_once)
            return

        all_data = {}
        for entity_id in self._entity_ids:
            if self._stop_polling.is_set():
                break
            data = self._fetch_light_state_sync(entity_id)
            if data:
                all_data[entity_id] = data

        GLib.idle_add(self._process_all_lights_data_in_main_thread, all_data)
        if not self._initial_refresh_done:
            self._initial_refresh_done = True

    def _process_all_lights_data_in_main_thread(self, all_data):
        any_gobject_updated = False
        for entity_id, data in all_data.items():
            if self._process_fetched_data_in_main_thread(entity_id, data):
                any_gobject_updated = True

        if any_gobject_updated or (
            self._entity_ids and not all_data and self._service_available
        ):
            GLib.idle_add(self.emit, "lights-updated")

        GLib.idle_add(self.emit, "master-state-changed", self.get_master_state())
        return False

    def get_lights(self):
        return [self._lights[eid] for eid in self._entity_ids if eid in self._lights]

    def get_master_state(self):
        if not self._client or not self._service_available:
            return False
        if not self._lights:
            return False
        return any(light.is_on for light in self._lights.values())

    def _call_service_sync(self, domain, service, entity_id):
        if not self._client:
            self._set_service_availability(False)
            return False
        payload = {"entity_id": entity_id}
        try:
            response = self._client.post(
                f"/api/services/{domain}/{service}", json=payload
            )
            response.raise_for_status()
            self._set_service_availability(True)
            return True
        except httpx.TimeoutException:
            print(
                f"HA Timeout calling {domain}.{service} for {entity_id} (timeout: {self._request_timeout}s)"
            )
            self._set_service_availability(False)
        except httpx.HTTPStatusError as e:
            print(
                f"HA API Error calling {domain}.{service} for {entity_id}: {e.response.status_code} - {e.response.text}"
            )
            self._set_service_availability(e.response.status_code < 500)
        except httpx.RequestError as e:
            print(f"HA Request Error calling {domain}.{service} for {entity_id}: {e}")
            self._set_service_availability(False)
        except Exception as e:
            print(
                f"HA Generic error calling service {domain}.{service} for {entity_id}: {e}"
            )
            self._set_service_availability(False)
        return False

    def _call_service_threaded_target(self, domain, service, entity_id):
        success = self._call_service_sync(domain, service, entity_id)
        if success:
            self._start_threaded_task(
                self._fetch_and_process_one_light_target, entity_id
            )

    def _start_threaded_task(self, target_func, *args):
        thread = threading.Thread(target=target_func, args=args)
        thread.daemon = True
        thread.start()

    def toggle_light(self, entity_id):
        if not self._client or not self._service_available:
            return
        light = self._lights.get(entity_id)
        if not light:
            print(f"HomeAssistantService: Light {entity_id} not found for toggling.")
            return
        service_to_call = "turn_on" if not light.is_on else "turn_off"
        self._start_threaded_task(
            self._call_service_threaded_target, "light", service_to_call, entity_id
        )

    def toggle_all_lights(self):
        if not self._client or not self._entity_ids or not self._service_available:
            return

        target_on_state = not self.get_master_state()
        service_to_call = "turn_on" if target_on_state else "turn_off"

        entities_to_toggle = [
            entity_id
            for entity_id in self._entity_ids
            if self._lights.get(entity_id) is None
            or (self._lights[entity_id].is_on != target_on_state)
        ]

        for entity_id in entities_to_toggle:
            self._start_threaded_task(
                self._call_service_threaded_target, "light", service_to_call, entity_id
            )

    def _poll_loop(self):
        if not self._client:
            print("HomeAssistantService: Poll loop cannot run, client not initialized.")
            return

        sleep_chunk = 0.1
        num_chunks = (
            int(self._poll_interval_seconds / sleep_chunk)
            if self._poll_interval_seconds > 0
            else 1
        )
        if num_chunks < 1:
            num_chunks = 1

        while not self._stop_polling.is_set():
            if self._entity_ids:
                self._start_threaded_task(self.refresh_all_lights_threaded_target)
            elif not self._initial_refresh_done:
                self._start_threaded_task(self._check_service_availability_once)

            for _ in range(num_chunks):
                if self._stop_polling.is_set():
                    break
                time.sleep(sleep_chunk)

    def start_polling(self):
        if not self._client:
            print("HomeAssistantService: Cannot start polling, client not initialized.")
            return

        if self._polling_thread is None or not self._polling_thread.is_alive():
            self._stop_polling.clear()
            self._polling_thread = threading.Thread(target=self._poll_loop)
            self._polling_thread.daemon = True
            self._polling_thread.start()

    def stop_polling(self):
        self._stop_polling.set()
        if self._polling_thread and self._polling_thread.is_alive():
            join_timeout = max(
                2,
                self._poll_interval_seconds / 10
                if self._poll_interval_seconds > 0
                else 2,
            )
            self._polling_thread.join(timeout=join_timeout)
            if self._polling_thread.is_alive():
                print(
                    f"HomeAssistantService: Warning - Polling thread did not stop within {join_timeout}s timeout."
                )


_ha_service_config_block = None
_widget_config_source_info = "utils package"

try:
    import utils

    _widget_config_source_info = "utils.widget_config (accessed via 'utils' package)"

    if (
        hasattr(utils, "widget_config")
        and utils.widget_config
        and isinstance(utils.widget_config, dict)
    ):
        _ha_service_config_block = utils.widget_config.get("home_assistant")
        if _ha_service_config_block:
            print(
                f"HomeAssistantService INFO: Successfully retrieved 'home_assistant' section from '{_widget_config_source_info}'."
            )
        else:
            print(
                f"HomeAssistantService INFO: 'home_assistant' section not found within the configuration from '{_widget_config_source_info}'."
            )
    elif not hasattr(utils, "widget_config"):
        print(
            f"HomeAssistantService WARNING: 'widget_config' attribute not found in 'utils' package. Check utils/config.py and utils/__init__.py."
        )
    elif not utils.widget_config:
        print(
            f"HomeAssistantService WARNING: Configuration from '{_widget_config_source_info}' is None or empty."
        )
    else:
        print(
            f"HomeAssistantService WARNING: Configuration from '{_widget_config_source_info}' is of unexpected type: {type(utils.widget_config)}."
        )

except ImportError as e:
    print(
        f"HomeAssistantService ERROR: Could not import the 'utils' package. Ensure 'utils' is a package (has __init__.py) and project root is in sys.path. Details: {e}"
    )
    if "_project_root" in globals() and isinstance(_project_root, Path):
        print(f"Attempted to add project root to sys.path: {_project_root}")
except AttributeError as e:
    print(
        f"HomeAssistantService ERROR: AttributeError while accessing config from '{_widget_config_source_info}'. 'widget_config' might not be set correctly in utils.config. Details: {e}"
    )
except Exception as e:
    print(
        f"HomeAssistantService ERROR: An unexpected error occurred while trying to retrieve Home Assistant configuration via '{_widget_config_source_info}': {e}"
    )

home_assistant_service = HomeAssistantService(
    ha_specific_config=_ha_service_config_block
)
