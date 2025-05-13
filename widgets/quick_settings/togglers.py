# Quick Settings Togglers

from fabric.widgets.box import Box
from fabric.widgets.image import Image
from fabric.widgets.label import Label

# Import CommandSwitcher and HoverButton from shared as per your code
from shared import CommandSwitcher, HoverButton

from services import notification_service
from utils.icons import icons
# gi.repository is needed for signal connection types if not handled automatically by Fabric wrapper
# and for GLib.idle_add if needed, although not strictly needed for this specific fix.
# Keep it imported just in case it's needed elsewhere implicitly.
from gi.repository import Gtk, GLib


class QuickSettingToggler(CommandSwitcher):
    """A button widget to toggle a command."""

    def __init__(self, command, name, enabled_icon, disabled_icon, args="", **kwargs):
        super().__init__(
            command,
            enabled_icon,
            disabled_icon,
            name,
            args=args,
            label=True,
            tooltip=False,
            interval=1000, # The periodic polling interval
            style_classes="quicksettings-toggler",
            **kwargs, # Pass along any extra keyword arguments
        )


class HyprIdleQuickSetting(QuickSettingToggler):
    """A button to toggle the Hyprland idle mode.""" # Corrected comment

    def __init__(self, **kwargs):
        super().__init__(
            command="hypridle",
            enabled_icon="",
            disabled_icon="",
            name="quicksettings-togglebutton",
            **kwargs
        )
        # --- ADDITION START ---
        # Connect the realize signal to trigger an immediate state update
        # The 'realize' signal is emitted when the widget is fully ready to be displayed.
        self.connect("realize", self._on_realize)
        # --- ADDITION END ---

    # --- ADDITION START ---
    def _on_realize(self, widget):
        """
        Called when the widget becomes realized.
        Triggers an immediate state check and appearance update via CommandSwitcher.
        """
        # We assume CommandSwitcher has a method (like 'update')
        # that forces the command to be run and the widget's state refreshed.
        try:
            # Call the update method inherited from CommandSwitcher
            self.update_ui() # <--- This calls CommandSwitcher's update logic
        except AttributeError:
            print(f"WARNING: {self.__class__.__name__}'s base (CommandSwitcher) does not have an 'update()' method.")
            print("Cannot force immediate state check on realize.")
        except Exception as e:
            print(f"WARNING: Error calling CommandSwitcher update() in {self.__class__.__name__}: {e}")

        # Return False to disconnect the signal handler after it has run once,
        # as 'realize' is only emitted once per widget lifecycle.
        return False
    # --- ADDITION END ---


class HyprSunsetQuickSetting(QuickSettingToggler):
    """A button to toggle the Hyprland sunset mode.""" # Corrected comment

    def __init__(self, **kwargs):
        super().__init__(
            command="hyprsunset",
            args="-t 2800k", # Assuming this is the correct argument for toggling
            enabled_icon="󱩌",
            disabled_icon="󰛨",
            name="quicksettings-togglebutton",
            **kwargs
        )
        # --- ADDITION START ---
        # Connect the realize signal to trigger an immediate state update
        self.connect("realize", self._on_realize)
        # --- ADDITION END ---

    # --- ADDITION START ---
    def _on_realize(self, widget):
        """
        Called when the widget becomes realized.
        Triggers an immediate state check and appearance update via CommandSwitcher.
        """
        try:
            # Call the update method inherited from CommandSwitcher
            self.update_ui() # <--- This calls CommandSwitcher's update logic
        except AttributeError:
             print(f"WARNING: {self.__class__.__name__}'s base (CommandSwitcher) does not have an 'update()' method.")
             print("Cannot force immediate state check on realize.")
        except Exception as e:
            print(f"WARNING: Error calling CommandSwitcher update() in {self.__class__.__name__}: {e}")

        # Return False to disconnect the signal handler after it has run once.
        return False
    # --- ADDITION END ---


class NotificationQuickSetting(HoverButton):
    """A button to toggle the notification."""
    # This class already has logic to set the initial state
    # by calling self.toggle_notification at the end of __init__.

    def __init__(self):
        super().__init__(
            name="quicksettings-togglebutton",
            style_classes="quicksettings-toggler",
        )

        self.notification_label = Label(
            label="Noisy",
        )
        self.notification_icon = Image(
            icon_name=icons["notifications"]["noisy"],
            icon_size=16,
        )

        self.children = Box(
            orientation="h",
            spacing=10,
            style="padding: 5px;", # Inline style might be better moved to CSS
            children=(
                self.notification_icon,
                self.notification_label,
            ),
        )

        # --- Signal handler management for notification_service ---
        # Store handler ID for cleanup
        self._notification_service_handler_id = None

        # Ensure notification_service is available before connecting
        if notification_service:
            self._notification_service_handler_id = notification_service.connect("dnd", self.toggle_notification)
        else:
            print("WARNING: Notification service not available.")

        self.connect("clicked", self.on_click)

        # --- Initial state update ---
        # Call toggle_notification immediately to set the initial state
        # Ensure service is available before querying its state
        if notification_service:
            self.toggle_notification(None, notification_service.dont_disturb)
        else:
             # Set a default state if service is missing
             print("INFO: Setting default notification state (Noisy) as service is unavailable.")
             self.toggle_notification(None, False) # Assume noisy/off by default if service is unavailable

        # --- ADDITION START ---
        # Connect destroy signal for cleanup if notification_service was connected
        self.connect("destroy", self.on_destroy)
        # --- ADDITION END ---


    def on_click(self, *_):
        """Toggle the notification."""
        # Ensure service is available before using it
        if notification_service:
            notification_service.dont_disturb = not notification_service.dont_disturb
        else:
            print("WARNING: Cannot toggle notification, service not available.")


    def toggle_notification(self, _, value, *args):
        """Update icon and label based on notification DND state."""
        # Check value type as it comes from a signal, ensure it's a boolean
        is_dnd = bool(value)

        if is_dnd:
            self.notification_label.set_label("Quiet")
            self.notification_icon.set_from_icon_name(
                icons["notifications"]["silent"], 16
            )
            self.remove_style_class("active")
        else:
            self.notification_label.set_label("Noisy")
            self.notification_icon.set_from_icon_name(
                icons["notifications"]["noisy"], 16
            )
            self.add_style_class("active")

    # --- ADDITION START ---
    def on_destroy(self, *args):
        """Clean up signal handlers connected to notification_service."""
        if notification_service and self._notification_service_handler_id:
             try:
                 notification_service.disconnect(self._notification_service_handler_id)
             except Exception as e:
                 print(f"Error disconnecting notification service handler: {e}")
        self._notification_service_handler_id = None
    # --- ADDITION END ---
