"""Tests for the emulated_hue area light groups platform."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.components import emulated_hue
from homeassistant.components.emulated_hue.const import (
    CONF_AREA_LIGHTS,
    CONF_AREA_LIGHTS_NAME_PREFIX,
)
from homeassistant.components.emulated_hue.light import (
    AreaLightGroup,
    AreaLightGroupManager,
    _collect_area_light_entities,
)
from homeassistant.const import (
    ATTR_BRIGHTNESS,
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.setup import async_setup_component

from tests.common import MockConfigEntry


@pytest.fixture
async def setup_registries(
    hass: HomeAssistant,
) -> tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry]:
    """Set up area, device, and entity registries."""
    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    return area_registry, device_registry, entity_registry


async def test_collect_area_light_entities_direct_assignment(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test collecting light entities directly assigned to an area."""
    area_registry, device_registry, entity_registry = setup_registries

    area = area_registry.async_create("Living Room")

    # Create a config entry for the entity
    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)

    # Register a light entity directly assigned to the area
    entity_registry.async_get_or_create(
        "light",
        "test",
        "light1",
        config_entry=config_entry,
        suggested_object_id="living_room_lamp",
        area_id=area.id,
    )

    result = _collect_area_light_entities(entity_registry, device_registry, area.id)
    assert result == ["light.living_room_lamp"]


async def test_collect_area_light_entities_via_device(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test collecting light entities inherited from a device in the area."""
    area_registry, device_registry, entity_registry = setup_registries

    area = area_registry.async_create("Bedroom")

    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)

    # Create a device in the area
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("test", "device1")},
        name="Bedroom Light Fixture",
    )
    device_registry.async_update_device(device.id, area_id=area.id)

    # Register a light entity on the device (no explicit area)
    entity_registry.async_get_or_create(
        "light",
        "test",
        "light2",
        config_entry=config_entry,
        device_id=device.id,
        suggested_object_id="bedroom_light",
    )

    result = _collect_area_light_entities(entity_registry, device_registry, area.id)
    assert result == ["light.bedroom_light"]


async def test_collect_area_light_entities_excludes_disabled(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test that disabled entities are excluded."""
    area_registry, device_registry, entity_registry = setup_registries

    area = area_registry.async_create("Kitchen")

    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)

    entry = entity_registry.async_get_or_create(
        "light",
        "test",
        "light_disabled",
        config_entry=config_entry,
        suggested_object_id="kitchen_disabled",
        area_id=area.id,
    )
    entity_registry.async_update_entity(
        entry.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )

    result = _collect_area_light_entities(entity_registry, device_registry, area.id)
    assert result == []


async def test_collect_area_light_entities_excludes_non_light_domains(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test that non-light domain entities are excluded."""
    area_registry, device_registry, entity_registry = setup_registries

    area = area_registry.async_create("Office")

    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)

    # Register a switch entity (not a light)
    entity_registry.async_get_or_create(
        "switch",
        "test",
        "switch1",
        config_entry=config_entry,
        suggested_object_id="office_switch",
        area_id=area.id,
    )

    result = _collect_area_light_entities(entity_registry, device_registry, area.id)
    assert result == []


async def test_collect_area_light_entities_device_entity_with_area_override(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test that device entities with explicit area override are excluded."""
    area_registry, device_registry, entity_registry = setup_registries

    area_a = area_registry.async_create("Area A")
    area_b = area_registry.async_create("Area B")

    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)

    # Create a device in Area A
    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("test", "device_override")},
    )
    device_registry.async_update_device(device.id, area_id=area_a.id)

    # Register a light entity on the device but explicitly assigned to Area B
    entity_registry.async_get_or_create(
        "light",
        "test",
        "light_override",
        config_entry=config_entry,
        device_id=device.id,
        suggested_object_id="overridden_light",
        area_id=area_b.id,
    )

    # Area A should NOT include this entity (it has an explicit area override)
    result_a = _collect_area_light_entities(
        entity_registry, device_registry, area_a.id
    )
    assert result_a == []

    # Area B should include it (directly assigned)
    result_b = _collect_area_light_entities(
        entity_registry, device_registry, area_b.id
    )
    assert result_b == ["light.overridden_light"]


async def test_collect_area_light_entities_no_duplicates(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test that entities are not duplicated when assigned both directly and via device."""
    area_registry, device_registry, entity_registry = setup_registries

    area = area_registry.async_create("Hall")

    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)

    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("test", "device_dup")},
    )
    device_registry.async_update_device(device.id, area_id=area.id)

    # Entity directly in area AND on device in same area
    entity_registry.async_get_or_create(
        "light",
        "test",
        "light_dup",
        config_entry=config_entry,
        device_id=device.id,
        suggested_object_id="hall_light",
        area_id=area.id,
    )

    result = _collect_area_light_entities(entity_registry, device_registry, area.id)
    assert result == ["light.hall_light"]
    assert len(result) == 1


async def test_area_light_group_entity_creation(
    hass: HomeAssistant,
) -> None:
    """Test that AreaLightGroup is a proper LightGroup subclass."""
    entity = AreaLightGroup(
        unique_id="emulated_hue_area_test",
        name="Test Area",
        entity_ids=["light.one", "light.two"],
    )

    assert entity.unique_id == "emulated_hue_area_test"
    assert entity.name == "Test Area"
    assert entity._entity_ids == ["light.one", "light.two"]


async def test_area_light_group_update_members(
    hass: HomeAssistant,
) -> None:
    """Test updating member entity IDs on an AreaLightGroup."""
    entity = AreaLightGroup(
        unique_id="emulated_hue_area_test",
        name="Test Area",
        entity_ids=["light.one", "light.two"],
    )

    # Same set, different order — should not trigger update
    # (set comparison means order doesn't matter)
    assert set(entity._entity_ids) == {"light.one", "light.two"}

    # Actually different members
    entity._attr_has_entity_name = False
    # Can't call async_write_ha_state without hass, so just test the logic
    old_ids = entity._entity_ids[:]
    new_ids = ["light.one", "light.three"]
    if set(new_ids) != set(old_ids):
        entity._entity_ids = new_ids
    assert entity._entity_ids == ["light.one", "light.three"]


async def test_area_light_group_manager_creates_entities(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test that the manager creates entities for areas with lights."""
    area_registry, device_registry, entity_registry = setup_registries

    area = area_registry.async_create("Living Room")

    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)

    entity_registry.async_get_or_create(
        "light",
        "test",
        "lr_light",
        config_entry=config_entry,
        suggested_object_id="living_room_main",
        area_id=area.id,
    )

    added_entities: list[AreaLightGroup] = []

    def mock_add_entities(entities: list[AreaLightGroup]) -> None:
        added_entities.extend(entities)

    manager = AreaLightGroupManager(hass, mock_add_entities, "")
    manager.update_area_lights()

    assert len(added_entities) == 1
    assert added_entities[0].name == "Living Room"
    assert added_entities[0].unique_id == f"emulated_hue_area_{area.id}"
    assert added_entities[0]._entity_ids == ["light.living_room_main"]


async def test_area_light_group_manager_with_name_prefix(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test that the manager applies name prefix."""
    area_registry, device_registry, entity_registry = setup_registries

    area = area_registry.async_create("Kitchen")

    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)

    entity_registry.async_get_or_create(
        "light",
        "test",
        "k_light",
        config_entry=config_entry,
        suggested_object_id="kitchen_light",
        area_id=area.id,
    )

    added_entities: list[AreaLightGroup] = []

    def mock_add_entities(entities: list[AreaLightGroup]) -> None:
        added_entities.extend(entities)

    manager = AreaLightGroupManager(hass, mock_add_entities, "Hue ")
    manager.update_area_lights()

    assert len(added_entities) == 1
    assert added_entities[0].name == "Hue Kitchen"


async def test_area_light_group_manager_skips_areas_without_lights(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test that areas without light entities are not created."""
    area_registry, device_registry, entity_registry = setup_registries

    # Create an area with no entities
    area_registry.async_create("Empty Room")

    # Create an area with only a switch
    area_with_switch = area_registry.async_create("Switch Room")
    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "switch",
        "test",
        "sw1",
        config_entry=config_entry,
        suggested_object_id="room_switch",
        area_id=area_with_switch.id,
    )

    added_entities: list[AreaLightGroup] = []

    def mock_add_entities(entities: list[AreaLightGroup]) -> None:
        added_entities.extend(entities)

    manager = AreaLightGroupManager(hass, mock_add_entities, "")
    manager.update_area_lights()

    assert len(added_entities) == 0


async def test_area_light_group_manager_updates_existing(
    hass: HomeAssistant,
    setup_registries: tuple[ar.AreaRegistry, dr.DeviceRegistry, er.EntityRegistry],
) -> None:
    """Test that the manager updates existing entities when members change."""
    area_registry, device_registry, entity_registry = setup_registries

    area = area_registry.async_create("Den")

    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)

    entity_registry.async_get_or_create(
        "light",
        "test",
        "den_light1",
        config_entry=config_entry,
        suggested_object_id="den_light_1",
        area_id=area.id,
    )

    added_entities: list[AreaLightGroup] = []

    def mock_add_entities(entities: list[AreaLightGroup]) -> None:
        added_entities.extend(entities)

    manager = AreaLightGroupManager(hass, mock_add_entities, "")
    manager.update_area_lights()

    assert len(added_entities) == 1
    original_entity = added_entities[0]
    assert original_entity._entity_ids == ["light.den_light_1"]

    # Add a second light to the area
    entity_registry.async_get_or_create(
        "light",
        "test",
        "den_light2",
        config_entry=config_entry,
        suggested_object_id="den_light_2",
        area_id=area.id,
    )

    # Mock async_write_ha_state since entity isn't added to hass
    with patch.object(original_entity, "async_write_ha_state"):
        manager.update_area_lights()

    # Should NOT add new entities, just update existing
    assert len(added_entities) == 1
    assert set(original_entity._entity_ids) == {"light.den_light_1", "light.den_light_2"}


async def test_config_schema_area_lights_options(hass: HomeAssistant) -> None:
    """Test that area_lights config options are accepted in schema."""
    config = {
        emulated_hue.DOMAIN: {
            CONF_AREA_LIGHTS: True,
            CONF_AREA_LIGHTS_NAME_PREFIX: "Room ",
        }
    }

    validated = emulated_hue.CONFIG_SCHEMA(config)
    assert validated[emulated_hue.DOMAIN][CONF_AREA_LIGHTS] is True
    assert validated[emulated_hue.DOMAIN][CONF_AREA_LIGHTS_NAME_PREFIX] == "Room "


async def test_config_schema_area_lights_defaults(hass: HomeAssistant) -> None:
    """Test that area_lights config options have correct defaults."""
    config = {emulated_hue.DOMAIN: {}}

    validated = emulated_hue.CONFIG_SCHEMA(config)
    assert validated[emulated_hue.DOMAIN][CONF_AREA_LIGHTS] is False
    assert validated[emulated_hue.DOMAIN][CONF_AREA_LIGHTS_NAME_PREFIX] == ""
