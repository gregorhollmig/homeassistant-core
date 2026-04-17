"""Platform to create area-based light groups for the emulated Hue bridge."""

from __future__ import annotations

import logging

from homeassistant.components import light
from homeassistant.components.group.light import LightGroup
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import CONF_AREA_LIGHTS_NAME_PREFIX, DATA_AREA_LIGHT_IDS, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up area light groups for the emulated Hue bridge."""
    if discovery_info is None:
        return

    name_prefix: str = discovery_info.get(CONF_AREA_LIGHTS_NAME_PREFIX, "")

    # Initialize the shared set of area light entity IDs
    hass.data.setdefault(DATA_AREA_LIGHT_IDS, set())

    manager = AreaLightGroupManager(hass, async_add_entities, name_prefix)
    manager.update_area_lights()

    # Listen for registry changes to dynamically add/remove area light groups
    hass.bus.async_listen(
        ar.EVENT_AREA_REGISTRY_UPDATED, manager.on_registry_updated
    )
    hass.bus.async_listen(
        dr.EVENT_DEVICE_REGISTRY_UPDATED, manager.on_registry_updated
    )
    hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, manager.on_registry_updated
    )


class AreaLightGroupManager:
    """Manage area-based LightGroup entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        async_add_entities: AddEntitiesCallback,
        name_prefix: str,
    ) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.async_add_entities = async_add_entities
        self.name_prefix = name_prefix
        # Track which area IDs have entities created
        self._area_entities: dict[str, AreaLightGroup] = {}

    @callback
    def on_registry_updated(self, event: object) -> None:
        """Handle area/device/entity registry updates."""
        self.update_area_lights()

    @callback
    def update_area_lights(self) -> None:
        """Scan areas and create/remove light groups as needed."""
        area_registry = ar.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)

        current_areas: dict[str, list[str]] = {}

        for area in area_registry.async_list_areas():
            light_entity_ids = _collect_area_light_entities(
                entity_registry, device_registry, area.id
            )
            if light_entity_ids:
                current_areas[area.id] = light_entity_ids

        # Add new areas
        new_entities: list[AreaLightGroup] = []
        for area_id, entity_ids in current_areas.items():
            area_entry = area_registry.async_get_area(area_id)
            if area_entry is None:
                continue

            if area_id in self._area_entities:
                # Update existing entity's member list
                existing = self._area_entities[area_id]
                existing.update_member_entity_ids(entity_ids)
            else:
                name = f"{self.name_prefix}{area_entry.name}"
                entity = AreaLightGroup(
                    unique_id=f"emulated_hue_area_{area_id}",
                    name=name,
                    entity_ids=entity_ids,
                )
                self._area_entities[area_id] = entity
                new_entities.append(entity)

        # Remove areas that no longer have lights
        for area_id in list(self._area_entities):
            if area_id not in current_areas:
                entity = self._area_entities.pop(area_id)
                self.hass.async_create_task(entity.async_remove())

        if new_entities:
            self.async_add_entities(new_entities)


def _collect_area_light_entities(
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    area_id: str,
) -> list[str]:
    """Collect light entity IDs for an area from entity and device registries."""
    light_entity_ids: list[str] = []
    seen: set[str] = set()

    # 1. Entities directly assigned to this area
    for entry in er.async_entries_for_area(entity_registry, area_id):
        if (
            entry.domain == light.DOMAIN
            and not entry.disabled
            and entry.entity_category is None
            and entry.hidden_by is None
            and entry.entity_id not in seen
        ):
            light_entity_ids.append(entry.entity_id)
            seen.add(entry.entity_id)

    # 2. Entities inherited from devices assigned to this area
    for device_entry in dr.async_entries_for_area(device_registry, area_id):
        for entry in er.async_entries_for_device(entity_registry, device_entry.id):
            if (
                entry.domain == light.DOMAIN
                and not entry.disabled
                and entry.entity_category is None
                and entry.hidden_by is None
                and not entry.area_id  # no explicit area override
                and entry.entity_id not in seen
            ):
                light_entity_ids.append(entry.entity_id)
                seen.add(entry.entity_id)

    return light_entity_ids


class AreaLightGroup(LightGroup):
    """A LightGroup that represents all lights in a Home Assistant area."""

    def __init__(
        self,
        unique_id: str,
        name: str,
        entity_ids: list[str],
    ) -> None:
        """Initialize an area light group."""
        super().__init__(unique_id, name, entity_ids, mode=False)

    async def async_added_to_hass(self) -> None:
        """Register entity ID in shared data when added to hass."""
        await super().async_added_to_hass()
        self.hass.data.setdefault(DATA_AREA_LIGHT_IDS, set()).add(self.entity_id)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister entity ID from shared data when removed."""
        if DATA_AREA_LIGHT_IDS in self.hass.data:
            self.hass.data[DATA_AREA_LIGHT_IDS].discard(self.entity_id)

    @callback
    def update_member_entity_ids(self, entity_ids: list[str]) -> None:
        """Update the list of member entity IDs when area membership changes."""
        if set(entity_ids) != set(self._entity_ids):
            self._entity_ids = entity_ids
            self._attr_extra_state_attributes = {
                "entity_id": entity_ids,
            }
            self.async_write_ha_state()
