import os
import subprocess
import shutil
from gi.repository import Gtk, GLib

# Imports from your project structure
from fabric.widgets.image import Image
from shared import SettingSlider, HoverButton
# import utils.functions as helpers # Not needed in this version
# from utils.widget_utils import util_fabricator # No longer needed

class HyprSunsetIntensitySlider(SettingSlider):
    """
    A slider widget to control screen color temperature using hyprsunset.
    Maps a 0-100 visual scale (representing filter intensity) to an
    INVERTED 2000K-6500K range (0=Neutral, 100=Warmest).
    Uses subprocess to kill existing instances and start new ones.
    Updates UI optimistically based on user actions.
    """
    # Define Kelvin range constants
    KELVIN_MIN = 2000  # Warmest temperature (maps to visual scale 100)
    KELVIN_MAX = 6500  # Neutral temperature (maps to visual scale 0)
    KELVIN_DEFAULT = 6000 # Default Kelvin if hyprsunset isn't running
    KELVIN_NEUTRAL = 6500 # Explicit neutral value (visual scale 0)

    # Scale operates visually on 0-100 (representing intensity percentage)
    SCALE_MIN = 0
    SCALE_MAX = 100

    def __init__(self, **kwargs):
        icon_name = "weather-clear-night-symbolic" # Icon representing warmth/night

        # Calculate the initial 0-100 scale value corresponding to KELVIN_DEFAULT
        # using the INVERTED mapping.
        initial_scale_value = self._kelvin_to_scale(self.KELVIN_DEFAULT)

        super().__init__(
            min=self.SCALE_MIN,
            max=self.SCALE_MAX,
            start_value=initial_scale_value, # Initial slider position
            icon_name=icon_name,
            pixel_size=16,
            **kwargs
        )

        # Configure the scale provided by SettingSlider
        initial_tooltip_kelvin = self._scale_to_kelvin(initial_scale_value) # Get initial K for tooltip
        self.scale.set_tooltip_text(f"Screen Color Temperature ({initial_tooltip_kelvin}K)")
        self.scale.set_increments(1, 5) # Step/Page increments for the 0-100 visual scale

        # Add the "Neutral" button (sets intensity to 0%, Kelvin to KELVIN_NEUTRAL)
        self.neutral_button = HoverButton(
            child=Gtk.Label(label="Neutral"),
            name="neutral-button-qs",
            tooltip_text=f"Set screen to neutral ({self.KELVIN_NEUTRAL}K)"
        )
        self.add(self.neutral_button)

        # Internal state stores the target KELVIN value or "identity"
        self._current_known_state = {"type": "kelvin", "value": self.KELVIN_DEFAULT}
        self._is_updating_state_prevent_feedback = False
        self._debounce_timer_id = None
        self.DEBOUNCE_INTERVAL = 350 # Milliseconds

        # Connect signals
        self.scale.connect("value-changed", self._on_scale_value_changed_by_user_debounced)
        self.neutral_button.connect("clicked", self._on_set_identity_clicked)

        # Initial UI sync
        GLib.idle_add(self.update_state)
        print("DEBUG: HyprSunsetIntensitySlider (Cleaned, Subprocess, INVERTED) initialized.")

    # --- INVERTED MAPPING LOGIC ---
    def _scale_to_kelvin(self, scale_value):
        """Maps a 0-100 intensity scale value to the INVERTED KELVIN_MIN-KELVIN_MAX range."""
        if self.SCALE_MAX == self.SCALE_MIN: return self.KELVIN_MAX
        scale_value = max(self.SCALE_MIN, min(self.SCALE_MAX, scale_value))
        percentage = float(scale_value - self.SCALE_MIN) / (self.SCALE_MAX - self.SCALE_MIN)
        # Inverted mapping: 0% intensity -> KELVIN_MAX, 100% intensity -> KELVIN_MIN
        kelvin = self.KELVIN_MAX - percentage * (self.KELVIN_MAX - self.KELVIN_MIN)
        return int(kelvin)

    def _kelvin_to_scale(self, kelvin_value):
        """Maps a KELVIN_MIN-KELVIN_MAX value to the INVERTED 0-100 intensity scale range."""
        if self.KELVIN_MAX == self.KELVIN_MIN: return self.SCALE_MIN
        kelvin_value = max(self.KELVIN_MIN, min(self.KELVIN_MAX, kelvin_value))
        # Inverted mapping: KELVIN_MAX -> 0%, KELVIN_MIN -> 100%
        percentage_from_max = (float(self.KELVIN_MAX - kelvin_value)) / (self.KELVIN_MAX - self.KELVIN_MIN)
        scale_val = self.SCALE_MIN + percentage_from_max * (self.SCALE_MAX - self.SCALE_MIN)
        return int(scale_val)
    # --- END OF INVERTED MAPPING LOGIC ---

    def _execute_kill_then_hyprsunset_change(self, hyprsunset_args_list, command_desc: str,
                                             success_callback_optimistic=None):
        """Uses subprocess to run kill then start hyprsunset asynchronously."""
        pkill_path = shutil.which("pkill")
        hyprsunset_path = shutil.which("hyprsunset")

        if not pkill_path: print("ERROR: Cannot find 'pkill'."); return
        if not hyprsunset_path: print("ERROR: Cannot find 'hyprsunset'."); return

        print(f"Initiating sequence for '{command_desc}'...")
        try:
            kill_process = subprocess.run([pkill_path, "hyprsunset"], timeout=0.5, check=False)
        except Exception as e: print(f"ERROR running pkill: {e}")

        delay_ms = 200
        def start_hyprsunset_after_delay():
            try:
                process = subprocess.Popen(
                    [hyprsunset_path] + hyprsunset_args_list,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                if success_callback_optimistic: success_callback_optimistic()
            except Exception as e: print(f"ERROR launching hyprsunset: {e}")
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(delay_ms, start_hyprsunset_after_delay)

    def _on_scale_value_changed_by_user_debounced(self, scale_widget, new_scale_value=None):
        """Handles raw 'value-changed' from scale and debounces command execution."""
        if new_scale_value is None: new_scale_value = scale_widget.get_value()

        # Use the INVERTED mapping to get target Kelvin
        kelvin_value_to_set = self._scale_to_kelvin(new_scale_value)
        self.scale.set_tooltip_text(f"Screen Color Temperature ({kelvin_value_to_set}K)")

        if self._debounce_timer_id is not None: GLib.source_remove(self._debounce_timer_id)
        self._debounce_timer_id = GLib.timeout_add(
            self.DEBOUNCE_INTERVAL,
            self._actually_execute_hyprsunset_for_kelvin,
            kelvin_value_to_set
        )
        return True

    def _actually_execute_hyprsunset_for_kelvin(self, kelvin_value):
        """Called by debounce timer to run the command."""
        self._debounce_timer_id = None
        if self._current_known_state["type"] == "kelvin" and \
           self._current_known_state["value"] == kelvin_value:
            return GLib.SOURCE_REMOVE # Value already set

        command_desc = f"Set HyprSunset to {kelvin_value}K"
        def on_success_optimistic():
            self._current_known_state = {"type": "kelvin", "value": kelvin_value}
            print(f"State updated optimistically for {command_desc}")

        self._execute_kill_then_hyprsunset_change(
            ["-t", f"{kelvin_value}k"], # Send actual mapped Kelvin
            command_desc,
            on_success_optimistic
        )
        return GLib.SOURCE_REMOVE

    def _on_set_identity_clicked(self, *args):
        """Handles click on the 'Neutral' button."""
        command_desc = f"Set HyprSunset to identity (neutral)"
        def on_success_optimistic():
            self._current_known_state = {"type": "identity"}
            self.update_state() # Sync UI to neutral state
            print(f"State updated optimistically for {command_desc}")

        # Use the kill-then-start strategy with the '-i' flag
        self._execute_kill_then_hyprsunset_change(
            ["-i"],
            command_desc,
            on_success_optimistic
        )

    def update_state(self, *args):
        """Updates the slider's visual state based *only* on _current_known_state."""
        if self._is_updating_state_prevent_feedback: return GLib.SOURCE_REMOVE
        self._is_updating_state_prevent_feedback = True

        target_scale_value = 0; tooltip_text = ""; actual_kelvin = 0

        if self._current_known_state["type"] == "identity":
            actual_kelvin = self.KELVIN_NEUTRAL
            # Use INVERTED mapping to find scale position for neutral Kelvin
            target_scale_value = self._kelvin_to_scale(self.KELVIN_NEUTRAL) # Should be SCALE_MIN (0)
            tooltip_text = f"Screen Color Temperature (Neutral/{self.KELVIN_NEUTRAL}K)"
        elif self._current_known_state["type"] == "kelvin":
            actual_kelvin = self._current_known_state["value"]
            # Use INVERTED mapping to find scale position for current Kelvin
            target_scale_value = self._kelvin_to_scale(actual_kelvin)
            tooltip_text = f"Screen Color Temperature ({actual_kelvin}K)"
        else: # Fallback
            actual_kelvin = self.KELVIN_DEFAULT
            target_scale_value = self._kelvin_to_scale(self.KELVIN_DEFAULT)
            tooltip_text = f"Screen Color Temperature ({actual_kelvin}K)"

        current_visual_scale_val = None
        try: # Safely get current value
             adj = self.scale.get_adjustment()
             if adj and isinstance(adj, Gtk.Adjustment): current_visual_scale_val = int(adj.get_value())
        except Exception as e: print(f"ERROR getting scale value in update_state: {e}")

        if current_visual_scale_val is not None and current_visual_scale_val != target_scale_value:
            self.scale.set_value(target_scale_value)

        self.scale.set_tooltip_text(tooltip_text)
        # print(f"HyprSunsetSlider state synced: {self._current_known_state} (Visual Scale: {target_scale_value}%)")

        self._is_updating_state_prevent_feedback = False
        return GLib.SOURCE_REMOVE
