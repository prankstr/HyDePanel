import os

import pyjson5 as json
import pytomlpp
from fabric.utils import get_relative_path
from loguru import logger

from .constants import DEFAULT_CONFIG
from .functions import (
    exclude_keys,
    flatten_dict,
    merge_defaults,
    run_in_thread,
    ttl_lru_cache,
    validate_widgets,
)


class HydeConfig:
    "A class to read the configuration file and return the default configuration"

    instance = None

    @staticmethod
    def get_default():
        if HydeConfig.instance is None:
            logger.info("[Config] Creating new HydeConfig instance.")
            HydeConfig.instance = HydeConfig()
        else:
            logger.info("[Config] Returning existing HydeConfig instance.")
        return HydeConfig.instance

    def __init__(self):
        logger.info("[Config] Initializing HydeConfig...")

        self.json_config = get_relative_path("../config.json")
        self.toml_config = get_relative_path("../config.toml")

        logger.info(f"[Config] JSON config path target: {self.json_config}")
        logger.info(f"[Config] TOML config path target: {self.toml_config}")
        self.config = {}
        self.default_config()
        self.set_css_settings()

    @ttl_lru_cache(600, 10)
    def read_config_json(self) -> dict | None:
        logger.info(f"[Config] Reading json config from {self.json_config}")
        try:
            with open(self.json_config, "r", encoding="utf-8") as file:
                data = json.load(file)  # type: ignore[arg-type]
            return data
        except FileNotFoundError:
            logger.error(f"[Config] JSON config file not found: {self.json_config}")
            return None
        except Exception as e:
            logger.error(
                f"[Config] Error reading/parsing JSON config {self.json_config}: {e}"
            )
            return None

    @ttl_lru_cache(600, 10)
    def read_config_toml(self) -> dict | None:
        logger.info(f"[Config] Reading toml config from {self.toml_config}")
        try:
            with open(self.toml_config, "r", encoding="utf-8") as file:
                data = pytomlpp.load(file)  # type: ignore[arg-type]
            return data
        except FileNotFoundError:
            logger.error(f"[Config] TOML config file not found: {self.toml_config}")
            return None
        except Exception as e:
            logger.error(
                f"[Config] Error reading/parsing TOML config {self.toml_config}: {e}"
            )
            return None

    def default_config(self) -> None:
        logger.info("[Config] Processing default_config...")
        check_toml = os.path.exists(self.toml_config)
        check_json = os.path.exists(self.json_config)

        parsed_data = None
        if check_json:
            logger.info("[Config] Found JSON config, attempting to read.")
            parsed_data = self.read_config_json()
        elif check_toml:
            logger.info("[Config] Found TOML config, attempting to read.")
            parsed_data = self.read_config_toml()
        else:
            logger.error("[Config] CRITICAL: No config file (json or toml) found.")
            self.config = {}
            return

        if parsed_data is None:
            logger.error(
                "[Config] CRITICAL: Failed to read or parse any configuration file."
            )
            self.config = {}
            return

        if not isinstance(parsed_data, dict):
            logger.error(
                f"[Config] CRITICAL: Parsed configuration data is not a dictionary (type: {type(parsed_data)}). Aborting merge."
            )
            self.config = {}
            return

        try:
            validate_widgets(parsed_data, DEFAULT_CONFIG)
        except Exception as e:
            logger.error(f"[Config] Error during validate_widgets: {e}")

        merged_config = {}
        current_merging_key = "Unknown"
        try:
            for key in exclude_keys(DEFAULT_CONFIG, ["$schema"]):
                current_merging_key = key
                if key == "module_groups":
                    merged_config[key] = parsed_data.get(
                        key, DEFAULT_CONFIG.get(key, [])
                    )
                else:
                    user_section = parsed_data.get(key, {})
                    default_section = DEFAULT_CONFIG.get(key, {})
                    merged_config[key] = merge_defaults(user_section, default_section)

            for key, value in parsed_data.items():
                current_merging_key = f"extra_key_{key}"
                if key not in merged_config:
                    merged_config[key] = value

        except TypeError as te:
            logger.error(
                f"[Config] TypeError during config merging (processing key/section '{current_merging_key}'): {te}"
            )
            logger.exception(
                f"TRACEBACK for TypeError during merge (key/section: {current_merging_key}):"
            )
            return
        except Exception as e_merge:
            logger.error(
                f"[Config] Generic error during config merging (processing key/section '{current_merging_key}'): {e_merge}"
            )
            logger.exception(
                f"TRACEBACK for generic error during merge (key/section: {current_merging_key}):"
            )
            return

        self.config = merged_config
        logger.info("[Config] Finished processing default_config.")
        if not self.config:
            logger.warning(
                "[Config] self.config is empty after default_config processing."
            )

    @run_in_thread
    def set_css_settings(self):
        if not hasattr(self, "config") or not self.config or "theme" not in self.config:
            logger.warning(
                "[Config] CSS settings cannot be applied: config or theme not available."
            )
            return

        logger.info("[Config] Applying css settings...")
        try:
            if not isinstance(self.config.get("theme"), dict):
                logger.error(
                    f"[Config] CSS: 'theme' section is not a dictionary (type: {type(self.config.get('theme'))}). Cannot apply CSS."
                )
                return

            theme_settings_to_flatten = self.config["theme"]
            css_styles = flatten_dict(exclude_keys(theme_settings_to_flatten, ["name"]))
            settings_lines = []
            for setting_key, setting_value in css_styles.items():
                value_str = (
                    json.dumps(setting_value)
                    if isinstance(setting_value, bool)
                    else str(setting_value)
                )
                settings_lines.append(f"${setting_key}: {value_str};")

            settings = "\n".join(settings_lines)
            if settings:
                settings += "\n"

            scss_settings_file = get_relative_path("../styles/_settings.scss")
            with open(scss_settings_file, "w", encoding="utf-8") as f:
                f.write(settings)
            logger.info(f"[Config] CSS settings written to {scss_settings_file}")
        except Exception as e:
            logger.error(f"[Config] Error writing CSS settings: {e}")
            logger.exception("TRACEBACK for error in set_css_settings:")


configuration = None
widget_config = None
try:
    configuration = HydeConfig.get_default()
    if (
        configuration
        and hasattr(configuration, "config")
        and configuration.config is not None
    ):
        widget_config = configuration.config
        logger.info("[Config] 'widget_config' has been set from HydeConfig instance.")
        if not widget_config:
            logger.warning(
                "[Config] 'widget_config' is empty, though HydeConfig instance was valid."
            )
    else:
        widget_config = None
        if not configuration:
            logger.error(
                "[Config] HydeConfig.get_default() returned None. 'widget_config' set to None."
            )
        else:
            logger.error(
                "[Config] HydeConfig instance created, but 'configuration.config' is missing or None. 'widget_config' set to None."
            )
except Exception as e:
    logger.critical(
        f"[Config] CRITICAL error during module-level instantiation of HydeConfig: {e}"
    )
    logger.exception("TRACEBACK for HydeConfig instantiation error:")
    configuration = None
    widget_config = None
