import os
import gi
from fabric.widgets.box import Box
from fabric.widgets.image import Image
from gi.repository import Gdk, GdkPixbuf, GLib, Gray, Gtk, GObject

from shared import ButtonWidget, Separator, HoverButton 
from utils import BarConfig
from utils.icons import icons

gi.require_version("Gray", "0.1")


def resolve_icon(item, icon_size: int = 16):
    pixmap = None
    try:
        raw_pixmaps = item.get_icon_pixmaps()
        if raw_pixmaps:
            pixmap = Gray.get_pixmap_for_pixmaps(raw_pixmaps, icon_size) 
            if pixmap:
                return pixmap.as_pixbuf(icon_size, GdkPixbuf.InterpType.HYPER)
    except Exception: # pylint: disable=broad-except
        pass 

    try:
        icon_name = item.get_icon_name()
        icon_theme_path = item.get_icon_theme_path()

        # Use custom theme path if available
        if icon_theme_path:
            custom_theme = Gtk.IconTheme.new()
            custom_theme.prepend_search_path(icon_theme_path)
            try:
                return custom_theme.load_icon(icon_name, icon_size, Gtk.IconLookupFlags.FORCE_SIZE)
            except GLib.Error:
                # Fallback to default theme if custom path fails
                return Gtk.IconTheme.get_default().load_icon(icon_name, icon_size, Gtk.IconLookupFlags.FORCE_SIZE)
        elif icon_name: 
            if os.path.exists(icon_name):  # for some apps, the icon_name is a path
                return GdkPixbuf.Pixbuf.new_from_file_at_size(icon_name, width=icon_size, height=icon_size)
            else:
                return Gtk.IconTheme.get_default().load_icon(icon_name, icon_size, Gtk.IconLookupFlags.FORCE_SIZE)
    except GLib.Error:
        pass 
    except Exception: # pylint: disable=broad-except
        pass
    # Fallback to 'image-missing' icon
    return Gtk.IconTheme.get_default().load_icon("image-missing", icon_size, Gtk.IconLookupFlags.FORCE_SIZE)


def _item_matches_keyword_list(item: Gray.Item, watcher_identifier: str, keyword_list: list[str], all_item_props: dict, tooltip_text_parts: list[str]) -> bool:
    if not keyword_list: 
        return False
        
    strings_to_check = set()
    for key, value in all_item_props.items():
        if isinstance(value, str) and value: 
            strings_to_check.add(value.strip().lower())

    if isinstance(watcher_identifier, str) and watcher_identifier:
        strings_to_check.add(watcher_identifier.strip().lower())
        if '/' in watcher_identifier:
            path_part = watcher_identifier.split('/')[-1]
            strings_to_check.add(path_part.strip().lower())
            if '.' in path_part: 
                strings_to_check.add(path_part.split('.')[-1].strip().lower())
                
    for tt_part in tooltip_text_parts:
        if isinstance(tt_part, str) and tt_part.strip(): 
            strings_to_check.add(tt_part.strip().lower())
    
    strings_to_check = {s for s in strings_to_check if s} 
    if not strings_to_check: 
        return False

    for s_to_check in strings_to_check:
        for keyword_item in keyword_list:
            if isinstance(keyword_item, str):
                keyword_lower = keyword_item.lower()
                if keyword_lower in s_to_check:
                    return True
    return False


class SystemTrayWidget(ButtonWidget):
    """A widget to display system tray items with an inline expansion for hidden items."""

    def __init__(self, widget_config: BarConfig, **kwargs):
        tray_specific_config = widget_config.get("system_tray", {}) 
        super().__init__(tray_specific_config, name="system_tray", **kwargs)

        self._icon_size = self.config.get("icon_size", 16)
        self._item_spacing = self.config.get("item_spacing", 3) 

        self.visible_items_box = Box(name="visible-tray-items-box", orientation="horizontal")
        self.hidden_items_box = Box(name="hidden-tray-items-box", orientation="horizontal")

        self.toggle_icon = Image(
            icon_name=icons["ui"]["arrow"]["left"], 
            icon_size=self._icon_size,
            style_classes=["panel-icon", "toggle-icon"],
            tooltip_text="Show/hide hidden tray items" 
        )
        self.separator = Separator(orientation="vertical")

        self.box.set_orientation(Gtk.Orientation.HORIZONTAL) 
        self.box.pack_start(self.visible_items_box, False, False, 0) 
        self.box.pack_start(self.separator, False, False, 0)
        self.box.pack_start(self.hidden_items_box, False, False, 0) 
        self.box.pack_end(self.toggle_icon, False, False, 0)

        self._hidden_buttons: list[HoverButton] = []
        self._processed_item_identifiers = set()
        self._is_expanded = False

        self.toggle_icon.set_visible(False)
        self.separator.set_visible(False)
        self.hidden_items_box.set_visible(False) 

        self.watcher = Gray.Watcher()
        self.watcher.connect("item-added", self._on_watcher_item_added)
        GLib.idle_add(self._process_existing_watcher_items) 

        self.connect("clicked", self.handle_toggle_click)

    def _process_existing_watcher_items(self):
        for item_id_str in self.watcher.get_items():
            self._on_watcher_item_added(self.watcher, item_id_str)
        self._update_toggle_button_visibility() 
        return GLib.SOURCE_REMOVE 

    def _on_watcher_item_added(self, watcher_obj: Gray.Watcher, identifier: str):
        if identifier in self._processed_item_identifiers:
            return 
        
        item = watcher_obj.get_item_for_identifier(identifier)
        if not item:
            return
        
        self._processed_item_identifiers.add(identifier)
        item.connect("removed", self._on_gray_item_removed, identifier) 
        
        self._add_or_update_tray_item(item, identifier)

    def _on_gray_item_removed(self, gray_item_instance: Gray.Item, identifier_from_closure: str):
        self._processed_item_identifiers.discard(identifier_from_closure)
        
        button_to_remove = None
        for btn_container in [self.visible_items_box, self.hidden_items_box]:
            for btn in btn_container.get_children():
                if isinstance(btn, HoverButton) and getattr(btn, 'tray_item_identifier', None) == identifier_from_closure:
                    button_to_remove = btn
                    break
            if button_to_remove: 
                break
        
        if button_to_remove:
            if button_to_remove in self._hidden_buttons:
                self._hidden_buttons.remove(button_to_remove)
            button_to_remove.destroy() 
        
        self._update_toggle_button_visibility() 

    def _add_or_update_tray_item(self, item: Gray.Item, identifier: str):
        all_item_props = {} 
        if isinstance(item, GObject.Object): 
            props = item.list_properties()
            if props:
                for prop in props:
                    try: all_item_props[prop.name] = item.get_property(prop.name)
                    except Exception: pass 
        
        tooltip_text_parts = [] 
        tooltip_obj = all_item_props.get("tooltip")
        if tooltip_obj and hasattr(tooltip_obj, 'text'): 
            try:
                value = getattr(tooltip_obj, 'text')
                if isinstance(value, str) and value.strip(): 
                    tooltip_text_parts.append(value.strip())
            except Exception: pass 
        
        try:
            direct_icon_name = item.get_icon_name()
            if direct_icon_name and isinstance(direct_icon_name, str) and direct_icon_name.strip():
                 all_item_props['icon-name-from-get-icon-name'] = direct_icon_name.strip()
        except Exception: pass
        tooltip_text_parts = list(dict.fromkeys(tooltip_text_parts)) 

        ignored_list = self.config.get("ignored", [])
        if _item_matches_keyword_list(item, identifier, ignored_list, all_item_props, tooltip_text_parts):
            self._processed_item_identifiers.discard(identifier) 
            return 

        primary_button_tooltip_text = " / ".join(filter(None, tooltip_text_parts))
        if not primary_button_tooltip_text: 
            item_title_prop = all_item_props.get("title", "")
            if isinstance(item_title_prop, str): 
                primary_button_tooltip_text = item_title_prop.strip()

        button = HoverButton(
            style_classes=["flat", "tray-icon-button"], 
            tooltip_text=primary_button_tooltip_text,
            margin_start=self._item_spacing, 
            margin_end=self._item_spacing  
        )
        button.tray_item_identifier = identifier 
        
        button.connect("button-press-event", self._on_item_button_click, item)
        
        self._update_button_icon(item, button) 
        item.connect("icon-changed", self._update_button_icon, button) 

        hidden_list = self.config.get("hidden", [])
        is_initially_hidden = _item_matches_keyword_list(item, identifier, hidden_list, all_item_props, tooltip_text_parts)

        if is_initially_hidden:
            button.get_style_context().add_class("hidden-tray-item-button") 
            self._hidden_buttons.append(button)
            self.hidden_items_box.pack_start(button, False, False, 0)
        else:
            self.visible_items_box.pack_start(button, False, False, 0)
            button.show() 
        
        self._update_toggle_button_visibility()
        if is_initially_hidden:
            if self._is_expanded: button.show()
            else: button.hide()

    def _update_button_icon(self, item: Gray.Item, button_to_update: HoverButton):
        pixbuf = resolve_icon(item=item, icon_size=self._icon_size)
        button_to_update.set_image(Image(pixbuf=pixbuf, pixel_size=self._icon_size))

    def _on_item_button_click(self, button: HoverButton, event: Gdk.EventButton, item: Gray.Item): 
        if event.button not in (1, 3): 
            return
        
        dbus_menu = None
        try: 
            dbus_menu = item.get_property("menu")
        except Exception: pass 

        if dbus_menu:
            dbus_menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, event)
        else: 
            try:
                root_x, root_y = event.get_root_coords() 
                item.context_menu(int(root_x), int(root_y))
            except Exception: # pylint: disable=broad-except
                try: 
                    item.activate() 
                except TypeError: 
                    try: 
                        item.activate(0) 
                    except Exception: # pylint: disable=broad-except
                        pass


    def handle_toggle_click(self, _widget): 
        if not self.toggle_icon.get_visible():
             return

        self._is_expanded = not self._is_expanded
        self._apply_hidden_items_visibility()
        self._update_toggle_icon_state()

    def _apply_hidden_items_visibility(self):
        self.hidden_items_box.set_visible(self._is_expanded)
        if self._is_expanded:
            for btn in self._hidden_buttons:
                if btn.get_parent(): 
                    btn.show() 

    def _update_toggle_icon_state(self):
        if self._is_expanded:
            self.toggle_icon.set_from_icon_name(icons["ui"]["arrow"]["right"], self._icon_size) 
            self.toggle_icon.get_style_context().add_class("active")
        else:
            self.toggle_icon.set_from_icon_name(icons["ui"]["arrow"]["left"], self._icon_size) 
            self.toggle_icon.get_style_context().remove_class("active")

    def _update_toggle_button_visibility(self):
        has_relevant_hidden_items = any(btn.get_parent() is not None for btn in self._hidden_buttons)

        if has_relevant_hidden_items:
            self.toggle_icon.set_visible(True)
            self.separator.set_visible(True)
        else:
            self.toggle_icon.set_visible(False)
            self.separator.set_visible(False)
            if self._is_expanded: 
                self._is_expanded = False
                self._apply_hidden_items_visibility() 
                self._update_toggle_icon_state()
