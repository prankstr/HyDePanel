import threading
import time 
from datetime import datetime, time as dt_time 

from fabric.utils import get_relative_path
from fabric.widgets.box import Box
from fabric.widgets.label import Label
from fabric.widgets.svg import Svg
from gi.repository import GLib, Gtk
from loguru import logger

from services import WeatherService 
from shared import ButtonWidget, Grid, Popover, ScanButton
from utils import BarConfig
from utils.icons import weather_icons
from utils.widget_utils import (
    text_icon,
    util_fabricator,
)

weather_service = WeatherService()


class BaseWeatherWidget:
    """Base class for weather widgets."""

    def sunrise_sunset_time(self) -> str:
        return f" {self.sunrise_time}  {self.sunset_time}"

    def update_sunrise_sunset(self, data):
        raw_sunrise_str_in = data["astronomy"]["sunrise"]
        raw_sunset_str_in = data["astronomy"]["sunset"]

        logger.debug(f"[Weather] Raw sunrise from data: '{raw_sunrise_str_in}' (repr: {repr(raw_sunrise_str_in)})")
        logger.debug(f"[Weather] Raw sunset from data: '{raw_sunset_str_in}' (repr: {repr(raw_sunset_str_in)})")

        sunrise_input_str = str(raw_sunrise_str_in).strip()
        sunset_input_str = str(raw_sunset_str_in).strip()
        
        def parse_12h_to_24h_object(time_str_12h: str) -> datetime | None:
            try:
                cleaned_str = time_str_12h.strip().upper() 
                
                time_part_end_idx = cleaned_str.rfind(" ")
                if time_part_end_idx == -1:
                    logger.error(f"Manual parse: Cannot find space to separate time and AM/PM in '{time_str_12h}'.")
                    return None
                
                time_part = cleaned_str[:time_part_end_idx].strip()
                period_part = cleaned_str[time_part_end_idx + 1:].strip()

                if period_part not in ("AM", "PM"):
                    logger.error(f"Manual parse: Invalid period '{period_part}' in '{time_str_12h}'. Expected AM or PM.")
                    return None
                try:
                    dt_obj_hm = datetime.strptime(time_part, "%I:%M")
                except ValueError as e_hm:
                    logger.error(f"Manual parse: strptime failed for time part '{time_part}' with %I:%M. Error: {e_hm}")
                    return None
                    
                hour = dt_obj_hm.hour 
                minute = dt_obj_hm.minute

                if period_part == "AM":
                    if hour == 12: 
                        hour = 0
                elif period_part == "PM":
                    if hour != 12: 
                        hour += 12
                return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            except Exception as ex_manual_detail: 
                logger.error(f"Manual parse: Unexpected error processing '{time_str_12h}': {ex_manual_detail}")
                return None

        sunrise_obj = parse_12h_to_24h_object(sunrise_input_str)
        sunset_obj = parse_12h_to_24h_object(sunset_input_str)

        if sunrise_obj and sunset_obj:
            self.sunrise_time = sunrise_obj.strftime("%H:%M")
            self.sunset_time = sunset_obj.strftime("%H:%M")
            logger.debug(f"[Weather] Stored 24h sunrise_time (manual): '{self.sunrise_time}'")
            logger.debug(f"[Weather] Stored 24h sunset_time (manual): '{self.sunset_time}'")
        else:
            logger.error(
                f"[Weather] Manual AM/PM parsing failed for '{sunrise_input_str}' or '{sunset_input_str}'. "
                "Setting sunrise/sunset to 00:00 as a fallback."
            )
            self.sunrise_time = "00:00" 
            self.sunset_time = "00:00"
        return True

    def temperature(self, value) -> str:
        celsius = self.config["temperature_unit"] == "celsius"
        if celsius:
            return f"{value}°C"
        else:
            return f"{int(int(value) * 9 / 5 + 32)}°F"

    def check_if_day(self, current_time_str_24h: str | None = None) -> bool:
        time_format_24h = "%H:%M" 

        current_dt_str: str
        if current_time_str_24h is None:
            current_dt_str = datetime.now().strftime(time_format_24h)
        else:
            current_dt_str = str(current_time_str_24h).strip()

        sunrise_dt_str = str(self.sunrise_time).strip() 
        sunset_dt_str = str(self.sunset_time).strip()
        
        logger.debug(
            f"[Weather] check_if_day (24h): Current='{current_dt_str}', "
            f"Sunrise='{sunrise_dt_str}', Sunset='{sunset_dt_str}' with format='{time_format_24h}'"
        )

        try:
            current_time_obj = datetime.strptime(current_dt_str, time_format_24h).time()
            sunrise_time_obj = datetime.strptime(sunrise_dt_str, time_format_24h).time()
            sunset_time_obj = datetime.strptime(sunset_dt_str, time_format_24h).time()
        except ValueError as e:
            logger.error(
                f"[Weather] Error during strptime in check_if_day (24h). "
                f"Inputs: Current='{current_dt_str}', Sunrise='{sunrise_dt_str}', Sunset='{sunset_dt_str}'. Error: {e}"
            )
            return True 
        return sunrise_time_obj <= current_time_obj < sunset_time_obj

    def convert_wttr_time_to_24hr_format(self, wttr_time_str: str) -> str:
        """Converts wttr.in time (e.g., '300', '1200', '2100') to 'HH:MM' 24-hour format."""
        try:
            time_val = int(wttr_time_str)
            hour = time_val // 100
            minute = time_val % 100
            return f"{hour:02d}:{minute:02d}"
        except ValueError:
            logger.error(f"[Weather] Invalid wttr_time_str for 24hr conversion: {wttr_time_str}")
            return "00:00" 

class WeatherMenu(Box, BaseWeatherWidget):
    """A menu to display the weather information."""

    def __init__(
        self,
        config,
        data,
        **kwargs,
    ):
        super().__init__(
            style_classes="weather-box",
            orientation="v",
            h_expand=True,
            spacing=5,
            **kwargs,
        )
        self.scan_btn = ScanButton(h_align="start", visible=False)
        self.config = config
        self.update_time = datetime.now()
        self.update_sunrise_sunset(data)

        self.current_weather = data["current"]
        self.hourly_forecast = data["hourly"]
        self.weather_icons_dir = get_relative_path("../assets/icons/svg/weather")

        self.current_weather_image = Svg(
            svg_file=self.get_weather_asset(self.current_weather["weatherCode"]),
            size=100,
            v_align="start",
            h_align="start",
        )

        self.title_box = Grid(name="weather-header-grid")
        self.title_box.attach(self.current_weather_image, 0, 0, 2, 3)
        self.title_box.attach(
            Label(style_classes="header-label", h_align="start", label=f"{data['location']}"),
            2, 0, 1, 1,
        )
        self.title_box.attach(
            Label(name="condition", h_align="start", label=f"{self.current_weather['weatherDesc'][0]['value']}"),
            2, 1, 1, 1,
        )
        self.title_box.attach(
            Label(style_classes="header-label", name="sunrise-sunset", h_align="start",
                  label=self.sunrise_sunset_time()),
            2, 2, 1, 1,
        )
        self.title_box.attach(
            Label(style_classes="stats", h_align="center",
                  label=f" {self.temperature(value=self.current_weather['temp_C'])}"),
            3, 0, 1, 1,
        )
        self.title_box.attach(
            Label(style_classes="stats", h_align="center", label=f"󰖎 {self.current_weather['humidity']}%"),
            3, 1, 1, 1,
        )

        try:
            windspeed_kmph = float(self.current_weather['windspeedKmph'])
            windspeed_mps = windspeed_kmph / 3.6
            wind_label_text = f" {windspeed_mps:.1f} m/s" 
        except (ValueError, KeyError) as e:
            logger.warning(f"[WeatherMenu] Could not parse or find windspeedKmph: {e}. Defaulting wind display.")
            wind_label_text = " N/A"

        self.title_box.attach(
            Label(
                style_classes="stats",
                h_align="center",
                label=wind_label_text, 
            ),
            3, 
            2, 
            1, 
            1, 
        )

        self.forecast_box = Grid(row_spacing=10, column_spacing=20, name="weather-grid")
        expander = Gtk.Expander(name="weather-expander", visible=True, child=self.forecast_box,
                                expanded=self.config["expanded"])
        self.children = (self.scan_btn, self.title_box, expander)
        self.update_widget(initial=True)
        util_fabricator.connect("changed", lambda *_: self.update_widget())

    def update_widget(self, initial=False):
        if not initial and (datetime.now() - self.update_time).total_seconds() < 60:
            return
        logger.debug("[WeatherMenu] Updating weather widget")
        self.update_time = datetime.now()

        current_hour_marker = int(datetime.now().strftime("%H")) * 100
        forecast_start_index = 0
        for i, forecast_item in enumerate(self.hourly_forecast):
            if int(forecast_item['time']) >= current_hour_marker:
                forecast_start_index = i
                break
        
        next_values = self.hourly_forecast[forecast_start_index : forecast_start_index + 4]

        for col_idx, column_data in enumerate(next_values):
            if col_idx >= 4: break

            hour_label_text_24h = self.convert_wttr_time_to_24hr_format(column_data['time'])
            
            hour = Label(
                style_classes="weather-forecast-time",
                label=hour_label_text_24h, 
                h_align="center",
            )
            icon = Svg(
                svg_file=self.get_weather_asset(
                    column_data["weatherCode"],
                    time_str_24h=hour_label_text_24h, 
                ),
                size=65, h_align="center", h_expand=True, style_classes="weather-forecast-icon",
            )
            temp = Label(
                style_classes="weather-forecast-temp",
                label=self.temperature(column_data["tempC"]),
                h_align="center",
            )
            self.forecast_box.attach(hour, col_idx, 0, 1, 1)
            self.forecast_box.attach(icon, col_idx, 1, 1, 1)
            self.forecast_box.attach(temp, col_idx, 2, 1, 1)

    def get_weather_asset(self, code: int, time_str_24h: str | None = None) -> str:
        is_day = self.check_if_day(
            current_time_str_24h=time_str_24h, 
        )
        image_name = "image" if is_day else "image-night"
        return f"{self.weather_icons_dir}/{weather_icons[str(code)][image_name]}.svg"


class WeatherWidget(ButtonWidget, BaseWeatherWidget):
    """A widget to display the current weather."""

    def __init__(
        self,
        widget_config: BarConfig,
        **kwargs,
    ):
        super().__init__(widget_config["weather"], name="weather", **kwargs)

        self.weather_icon = text_icon(icon="", props={"style_classes": "panel-icon"})
        self.popover = None
        self.update_time = datetime.now()
        self.current_weather = None 

        self.weather_label = Label(label="Fetching weather...", style_classes="panel-text")
        self.box.children = (self.weather_icon, self.weather_label)
        self.update_ui(initial=True)
        util_fabricator.connect("changed", lambda *_: self.update_ui())

    def fetch_data_from_url(self):
        logger.debug("[WeatherWidget] Fetching data from URL.")
        data = weather_service.get_weather(
            location=self.config["location"], ttl=self.config["interval"]
        )
        GLib.idle_add(self.update_data, data)

    def update_data(self, data):
        self.update_time = datetime.now()
        if data is None:
            logger.error("[WeatherWidget] Error fetching weather data or data is None.")
            self.weather_label.set_label("")
            self.weather_icon.set_label("")
            if self.config.get("tooltip", False):
                self.set_tooltip_text("Error fetching weather data")
            return False

        self.current_weather = data["current"]
        self.update_sunrise_sunset(data) 

        weather_code_str = str(self.current_weather["weatherCode"])
        icon_key = "icon" if self.check_if_day() else "icon-night"
        
        selected_text_icon = weather_icons.get(weather_code_str, {}).get(icon_key, "")
        if selected_text_icon == "":
            logger.warning(f"[WeatherWidget] Weather icon not found for code {weather_code_str}, key {icon_key}.")

        self.weather_icon.set_label(selected_text_icon)
        self.weather_label.set_label(self.temperature(value=self.current_weather["temp_C"]))

        if self.config.get("tooltip", False):
            self.set_tooltip_text(
                f"{data['location']}, {self.current_weather['weatherDesc'][0]['value']}"
            )

        if self.popover is None:
            self.popover = Popover(
                content_factory=lambda: WeatherMenu(data=data, config=self.config),
                point_to=self,
            )
            self._clicked_signal_id = self.connect("clicked", self.popover.open)
        else:
            self.popover.set_content_factory(
                lambda: WeatherMenu(data=data, config=self.config)
            )
        return False

    def update_ui(self, initial=False):
        if self.current_weather and (datetime.now() - self.update_time).total_seconds() > 300:
            logger.debug("[WeatherWidget] Refreshing icon due to time passing (5 min threshold).")
            weather_code_str = str(self.current_weather["weatherCode"])
            icon_key = "icon" if self.check_if_day() else "icon-night"
            selected_text_icon = weather_icons.get(weather_code_str, {}).get(icon_key, "")
            self.weather_icon.set_label(selected_text_icon)

        if not initial and (datetime.now() - self.update_time).total_seconds() < self.config["interval"]:
            return

        logger.debug(f"[WeatherWidget] Interval passed or initial update. Triggering data fetch. Initial: {initial}")
        threading.Thread(target=self.fetch_data_from_url, daemon=True).start()
