from typing import Dict

import gi
from fabric.widgets.box import Box
from fabric.widgets.button import Button as FabricButtonForListItem
from fabric.widgets.label import Label as FabricLabel

from services import HomeAssistantLight, home_assistant_service
from shared import HoverButton, QSChevronButton, QuickSubMenu
from utils.icons import icons

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402


class HALightItem(FabricButtonForListItem):
    """A clickable list item representing a single Home Assistant light."""

    def __init__(self, light_obj: HomeAssistantLight, **kwargs):
        self.light_obj = light_obj
        self.item_box = Box(orientation="h", spacing=10)
        self.icon_label = FabricLabel(
            label="",
            style_classes=["icon", "ha-light-item-icon-label"],
            v_align=Gtk.Align.CENTER,
        )
        self.name_label = FabricLabel(
            label=self.light_obj.name,
            hexpand=True,
            h_align=Gtk.Align.START,
            style_classes="submenu-item-label",
            v_align=Gtk.Align.CENTER,
        )
        self.item_box.add(self.icon_label)
        self.item_box.add(self.name_label)
        super().__init__(
            child=self.item_box,
            style_classes=["submenu-button", "ha-light-item-fabric-button"],
            can_focus=True,
            receives_default=False,
            **kwargs,
        )
        self._service_available = (
            home_assistant_service._service_available
            if home_assistant_service
            else False
        )
        self._availability_handler_id = None
        if home_assistant_service:
            self._availability_handler_id = home_assistant_service.connect(
                "service-availability-changed",
                self._on_ha_availability_changed_for_item,
            )
        self._update_visual_state()
        self.connect("clicked", self._on_item_clicked)
        self.light_state_change_handler_id = self.light_obj.connect(
            "state-changed", self._on_light_state_changed_externally
        )
        self.connect("destroy", self._on_item_destroy)

    def _on_ha_availability_changed_for_item(self, _, is_avail: bool):
        if self._service_available != is_avail:
            self._service_available = is_avail
            GLib.idle_add(self._update_visual_state)

    def _on_item_clicked(self, _):
        if self._service_available and home_assistant_service:
            home_assistant_service.toggle_light(self.light_obj.entity_id)

    def _on_light_state_changed_externally(self, _):
        GLib.idle_add(self._update_visual_state)

    def _update_visual_state(self):
        is_on = self.light_obj.is_on
        name = self.light_obj.name
        ctx = self.get_style_context()

        if not self._service_available:
            self.icon_label.set_label(icons["lights"]["unavailable_char"])
            self.name_label.set_label(f"{name} (Offline)")
            self.set_sensitive(False)
            if ctx.has_class("active"):
                self.remove_style_class("active")
        else:
            self.set_sensitive(True)
            self.icon_label.set_label(
                icons["lights"]["on_char"] if is_on else icons["lights"]["off_char"]
            )
            self.name_label.set_label(name)
            if is_on:
                if not ctx.has_class("active"):
                    self.add_style_class("active")
            else:
                if ctx.has_class("active"):
                    self.remove_style_class("active")
        return False

    def _on_item_destroy(self, _widget):
        if (
            hasattr(self, "light_state_change_handler_id")
            and self.light_state_change_handler_id
            and self.light_obj.handler_is_connected(self.light_state_change_handler_id)
        ):
            self.light_obj.disconnect(self.light_state_change_handler_id)

        if (
            hasattr(self, "_availability_handler_id")
            and self._availability_handler_id
            and home_assistant_service
            and home_assistant_service.handler_is_connected(
                self._availability_handler_id
            )
        ):
            home_assistant_service.disconnect(self._availability_handler_id)


class HALightsSubMenu(QuickSubMenu):
    """Submenu for controlling multiple Home Assistant lights."""

    def __init__(self, **kwargs):
        self.service = home_assistant_service
        self._light_widgets: Dict[str, HALightItem] = {}
        self.lights_box = Box(
            orientation="v",
            spacing=0,
            style_classes=["ha-lights-list", "no-spacing-list"],
        )
        self.scan_button_instance = HoverButton(name="ha-lights-dummy-scan-button")
        self.base_title = "Lights Control"
        self._service_available = (
            self.service._service_available if self.service else False
        )

        super().__init__(
            title=self.base_title,
            title_icon=icons["lights"]["generic_sym"],
            scan_button=self.scan_button_instance,
            child=self.lights_box,
            **kwargs,
        )

        scan_btn_container = getattr(
            self, "scan_button_widget", getattr(self, "scan_button_revealer", None)
        )
        if scan_btn_container:
            if hasattr(scan_btn_container, "set_reveal_child"):
                scan_btn_container.set_reveal_child(False)
            scan_btn_container.set_visible(False)

        self._sig_ids = {"avail": None, "lu": None, "ms": None}
        if self.service:
            self._sig_ids["avail"] = self.service.connect(
                "service-availability-changed",
                self._on_ha_availability_changed_for_submenu,
            )
            self._sig_ids["lu"] = self.service.connect(
                "lights-updated", self._update_submenu_title_and_repopulate
            )
            self._sig_ids["ms"] = self.service.connect(
                "master-state-changed", lambda *_: self._update_submenu_title()
            )
        self._update_submenu_title()
        self._populate_lights()

    def _on_ha_availability_changed_for_submenu(self, _service, is_avail: bool):
        if self._service_available != is_avail:
            self._service_available = is_avail
            GLib.idle_add(self._update_submenu_title)
            GLib.idle_add(self._populate_lights)

    def _update_submenu_title_and_repopulate(self, _service=None):
        self._update_submenu_title()
        self._on_service_lights_updated(_service)

    def _update_submenu_title(self, *_):
        new_title = self.base_title
        if not self._service_available:
            new_title = f"{self.base_title} (Offline)"
        elif self.service:
            on_count = sum(
                1 for light_obj in self.service.get_lights() if light_obj.is_on
            )
            num_lights = len(self.service.get_lights())
            if num_lights > 0:
                new_title = (
                    f"{self.base_title} - {on_count} On"
                    if on_count > 0
                    else f"{self.base_title} - All Off"
                )

        if hasattr(self, "set_title_text"):
            self.set_title_text(new_title)
        return False

    def _clear_lights(self):
        for child in list(self.lights_box.get_children()):
            self.lights_box.remove(child)
            child.destroy()
        self._light_widgets.clear()

    def _on_service_lights_updated(self, _service=None):
        GLib.idle_add(self._populate_lights)

    def _populate_lights(self):
        current_widget_ids = set(self._light_widgets.keys())
        service_lights = self.service.get_lights() if self.service else []
        service_light_ids = {light.entity_id for light in service_lights}
        new_ordered_widgets = []

        for child in list(self.lights_box.get_children()):
            child_name = getattr(child, "get_name", lambda: None)()
            if child_name in ["no-lights-label", "ha-service-unavailable-label"]:
                self.lights_box.remove(child)
                child.destroy()

        if not self._service_available:
            if not any(
                getattr(c, "get_name", lambda: None)() == "ha-service-unavailable-label"
                for c in self.lights_box.get_children()
            ):
                self._clear_lights()
                lbl = FabricLabel(
                    "Home Assistant unavailable.",
                    style_classes=["dim-label", "centered-text"],
                    name="ha-service-unavailable-label",
                )
                self.lights_box.add(lbl)
                lbl.show()
        elif not service_lights:
            if not any(
                getattr(c, "get_name", lambda: None)() == "no-lights-label"
                for c in self.lights_box.get_children()
            ):
                self._clear_lights()
                lbl = FabricLabel(
                    "No lights configured.",
                    style_classes=["dim-label", "centered-text"],
                    name="no-lights-label",
                )
                self.lights_box.add(lbl)
                lbl.show()
        else:
            for light_obj in service_lights:
                widget = self._light_widgets.get(light_obj.entity_id)
                if not widget:
                    widget = HALightItem(light_obj)
                    self._light_widgets[light_obj.entity_id] = widget
                else:
                    widget._service_available = self._service_available
                    widget._update_visual_state()
                new_ordered_widgets.append(widget)

            for entity_id in current_widget_ids - service_light_ids:
                widget_to_remove = self._light_widgets.pop(entity_id, None)
                if (
                    widget_to_remove
                    and widget_to_remove.get_parent() == self.lights_box
                ):
                    self.lights_box.remove(widget_to_remove)
                    widget_to_remove.destroy()

            current_box_children = list(self.lights_box.get_children())
            if current_box_children != new_ordered_widgets:
                for child in current_box_children:
                    self.lights_box.remove(child)
                for widget_to_add in new_ordered_widgets:
                    self.lights_box.add(widget_to_add)
                    widget_to_add.show_all()

        if self.lights_box.get_children():
            self.lights_box.show_all()
        return False

    def do_reveal(
        self, visible: bool
    ) -> bool:  # Parameter name 'visible' matches QuickSubMenu
        if visible and self.service and hasattr(self.service, "refresh_all_lights"):
            GLib.idle_add(self.service.refresh_all_lights)
        return super().do_reveal(visible)

    def destroy(self):
        if self.service:
            for _, sig_id in self._sig_ids.items():
                if sig_id and self.service.handler_is_connected(sig_id):
                    self.service.disconnect(sig_id)
        self._clear_lights()
        super().destroy()


class HALightsToggle(QSChevronButton):
    """Toggler button for Home Assistant lights with a submenu."""

    def __init__(self, submenu: HALightsSubMenu, **kwargs):
        super().__init__(
            action_label="Office Lights",
            action_icon=icons["lights"]["generic_char"],
            submenu=submenu,
            style_classes=["ha-lights-toggle"],
            **kwargs,
        )
        self.service = home_assistant_service
        self._service_available = (
            self.service._service_available if self.service else False
        )
        self._update_action_button_state()
        self._sig_ids = {"avail": None, "ms": None, "lu": None}

        if self.service:
            self._sig_ids["avail"] = self.service.connect(
                "service-availability-changed",
                self._on_ha_availability_changed_for_toggle,
            )
            self._sig_ids["ms"] = self.service.connect(
                "master-state-changed", self._on_master_state_changed
            )
            self._sig_ids["lu"] = self.service.connect(
                "lights-updated",
                lambda *_: GLib.idle_add(self._update_action_button_state),
            )
        if hasattr(self, "action_button") and self.action_button:
            self.action_button.connect("clicked", self._on_main_action_part_clicked)

    def _on_main_action_part_clicked(self, _):
        if (
            self.action_button.get_sensitive()
            and self._service_available
            and self.service
        ):
            self.service.toggle_all_lights()

    def _on_ha_availability_changed_for_toggle(self, _, is_avail: bool):
        if self._service_available != is_avail:
            self._service_available = is_avail
            GLib.idle_add(self._update_action_button_state)

    def _on_master_state_changed(self, *_):
        GLib.idle_add(self._update_action_button_state)

    def _update_action_button_state(self):
        fixed_label = "Office Lights"
        char_icon_to_use = icons["lights"]["unavailable_char"]

        if not self._service_available:
            self.set_action_label(f"{fixed_label} (Offline)")
            self.set_active_style(False)
            self.action_button.set_sensitive(False)
            if (
                hasattr(self.action_button, "get_active")
                and self.action_button.get_active()
            ):
                self.do_reveal_action(False)
        else:
            self.action_button.set_sensitive(True)
            any_on = self.service.get_master_state() if self.service else False
            char_icon_to_use = (
                icons["lights"]["on_char"] if any_on else icons["lights"]["off_char"]
            )
            self.set_action_label(fixed_label)
            self.set_active_style(any_on)

        self.set_action_icon(char_icon_to_use)
        return False

    def _sync_chevron_with_state(self, is_revealed: bool):
        if hasattr(self, "button_image") and self.button_image:
            self.button_image.set_from_icon_name(
                icons["ui"]["arrow"]["down"]
                if is_revealed
                else icons["ui"]["arrow"]["right"],
                20,
            )
            ctx = self.button_image.get_style_context()
            if is_revealed:
                ctx.add_class("green")
            else:
                ctx.remove_class("green")
        if (
            hasattr(self.action_button, "set_active")
            and hasattr(self.action_button, "get_active")
            and self.action_button.get_active() != is_revealed
        ):
            self.action_button.set_active(is_revealed)

    def do_reveal_action(self, reveal: bool) -> bool:
        if (
            not self._service_available or not self.action_button.get_sensitive()
        ) and reveal:
            return False

        final_reveal_state = reveal
        if self.submenu is not None:
            final_reveal_state = self.submenu.do_reveal(reveal)
        self._sync_chevron_with_state(final_reveal_state)
        return final_reveal_state

    def do_reveal_toggle(self, *_):
        if self.submenu and self.submenu.revealer:
            handler_attr = "_submenu_reveal_handler_id_for_toggle"
            if not (
                hasattr(self, handler_attr)
                and getattr(self, handler_attr)
                and self.submenu.revealer.handler_is_connected(
                    getattr(self, handler_attr)
                )
            ):
                setattr(
                    self,
                    handler_attr,
                    self.submenu.revealer.connect(
                        "notify::child-revealed",
                        self._on_submenu_revealed_externally_for_toggle,
                    ),
                )
        super().do_reveal_toggle(*_)

    def _on_submenu_revealed_externally_for_toggle(self, revealer_widget, _):
        is_revealed = revealer_widget.get_reveal_child()
        self._sync_chevron_with_state(is_revealed)
        handler_attr = "_submenu_reveal_handler_id_for_toggle"
        if (
            hasattr(self, handler_attr)
            and getattr(self, handler_attr)
            and revealer_widget.handler_is_connected(getattr(self, handler_attr))
        ):
            revealer_widget.disconnect(getattr(self, handler_attr))
            setattr(self, handler_attr, None)

    def destroy(self):
        handler_attr = "_submenu_reveal_handler_id_for_toggle"
        if (
            hasattr(self, handler_attr)
            and getattr(self, handler_attr)
            and self.submenu
            and self.submenu.revealer
            and self.submenu.revealer.handler_is_connected(getattr(self, handler_attr))
        ):
            self.submenu.revealer.disconnect(getattr(self, handler_attr))

        if self.service:
            for _, sig_id in self._sig_ids.items():
                if sig_id and self.service.handler_is_connected(sig_id):
                    self.service.disconnect(sig_id)
        super().destroy()
