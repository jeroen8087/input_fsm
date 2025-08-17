from __future__ import annotations

import logging
from typing import Any, Dict, List

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.reload import async_integration_yaml_config

from .const import (
    DOMAIN,
    SERVICE_TRIGGER,
    SERVICE_SET_STATE,
    SERVICE_RESET,
    SERVICE_RELOAD,
    WILDCARD,
)
from .fsm_entity import FSMEntity

_LOGGER = logging.getLogger(__name__)

STATE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("description", default=""): cv.string,
    }
)

TIMEOUT_SCHEMA = vol.Schema(
    {
        vol.Required("seconds"): vol.Coerce(float),
        vol.Required("dest"): cv.string,
    }
)

ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("service"): cv.string,
        vol.Optional("data", default=dict): dict,
    }
)

TRANSITION_SCHEMA = vol.Schema(
    {
        vol.Required("trigger"): cv.string,
        vol.Required("source"): cv.string,  # may be WILDCARD "*"
        vol.Required("dest"): cv.string,
        vol.Optional("guard"): cv.string,
        vol.Optional("timeout"): TIMEOUT_SCHEMA,
        vol.Optional("actions", default=list): [ACTION_SCHEMA],
    }
)

FSM_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required("initial"): cv.string,
        vol.Required("states"): [STATE_SCHEMA],
        vol.Required("transitions"): [TRANSITION_SCHEMA],
    }
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: {cv.slug: FSM_CONFIG_SCHEMA}},
    extra=vol.ALLOW_EXTRA,
)


def _state_names(states: List[Dict[str, Any]]) -> set:
    return {s.get("name") for s in states}


def _log_transition_issues(object_id: str, states: List[Dict[str, Any]], transitions: List[Dict[str, Any]]) -> None:
    names = _state_names(states)
    seen = set()
    for t in transitions:
        pair = (t["source"], t["trigger"])
        if pair in seen:
            _LOGGER.warning("input_fsm: duplicate transition for (%s, %s) in %s", t["source"], t["trigger"], object_id)
        else:
            seen.add(pair)
        # Allow wildcard source; only validate dest
        if t["source"] != WILDCARD and t["source"] not in names:
            _LOGGER.error("input_fsm: transition %s has invalid source in %s", t, object_id)
        if t["dest"] not in names:
            _LOGGER.error("input_fsm: transition %s has invalid dest in %s", t, object_id)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    store = hass.data[DOMAIN]
    store.setdefault("entities_by_id", {})
    store.setdefault("entities_by_object_id", {})
    component = EntityComponent(_LOGGER, DOMAIN, hass)
    store["component"] = component

    # Validate initial config
    try:
        cfg = CONFIG_SCHEMA(config)
    except vol.Invalid as e:
        _LOGGER.error("input_fsm: configuration invalid: %s", e)
        return False

    fsm_configs: Dict[str, Dict[str, Any]] = cfg.get(DOMAIN, {}) or {}
    entities: List[FSMEntity] = []

    for object_id, c in fsm_configs.items():
        initial = c.get("initial")
        states = c.get("states", [])
        transitions = c.get("transitions", [])
        names = _state_names(states)
        if initial not in names:
            _LOGGER.warning("input_fsm: initial state '%s' for %s not in declared states %s", initial, object_id, names)
        _log_transition_issues(object_id, states, transitions)
        ent = FSMEntity(hass, object_id, initial, states, transitions)
        entities.append(ent)

    await component.async_add_entities(entities)

    for ent in entities:
        if hasattr(ent, "entity_id"):
            store["entities_by_id"][ent.entity_id] = ent
            store["entities_by_object_id"][ent._object_id] = ent
            _LOGGER.debug("input_fsm registered entity_id %s", ent.entity_id)

    # ----- Services -----
    async def svc_trigger(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        trigger = call.data.get("trigger")
        if not entity_id or not trigger:
            _LOGGER.error("input_fsm.trigger requires entity_id and trigger")
            return
        ent: FSMEntity | None = store["entities_by_id"].get(entity_id)
        if ent:
            await ent.async_trigger(trigger)
        else:
            _LOGGER.error("input_fsm: entity %s not found", entity_id)

    async def svc_set_state(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        state = call.data.get("state")
        if not entity_id or not state:
            _LOGGER.error("input_fsm.set_state requires entity_id and state")
            return
        ent: FSMEntity | None = store["entities_by_id"].get(entity_id)
        if ent:
            ok = await ent.async_set_state(state)
            if not ok:
                _LOGGER.error("input_fsm.set_state: invalid state '%s' for %s", state, entity_id)
        else:
            _LOGGER.error("input_fsm: entity %s not found", entity_id)

    async def svc_reset(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        ent: FSMEntity | None = store["entities_by_id"].get(entity_id)
        if ent:
            await ent.async_reset()
        else:
            _LOGGER.error("input_fsm: entity %s not found", entity_id)

    async def svc_reload(call: ServiceCall):
        raw_section = await async_integration_yaml_config(hass, DOMAIN) or {}
        try:
            validated = CONFIG_SCHEMA({DOMAIN: raw_section})
        except vol.Invalid as e:
            _LOGGER.error("input_fsm.reload: configuration invalid: %s", e)
            return

        new_cfg: Dict[str, Dict[str, Any]] = validated.get(DOMAIN, {}) or {}
        old_by_object = store["entities_by_object_id"]
        new_object_ids = set(new_cfg.keys())
        old_object_ids = set(old_by_object.keys())

        to_add = new_object_ids - old_object_ids
        to_update = new_object_ids & old_object_ids
        to_remove = old_object_ids - new_object_ids

        _LOGGER.info("input_fsm.reload: add=%s update=%s remove=%s", sorted(to_add), sorted(to_update), sorted(to_remove))

        # Remove
        for oid in to_remove:
            ent = old_by_object.get(oid)
            if ent:
                await ent.async_remove()
                store["entities_by_id"].pop(ent.entity_id, None)
                old_by_object.pop(oid, None)
                _LOGGER.info("input_fsm.reload: removed %s (%s)", oid, ent.entity_id)

        # Add
        new_entities: List[FSMEntity] = []
        for oid in to_add:
            c = new_cfg[oid]
            initial = c.get("initial")
            states = c.get("states", [])
            transitions = c.get("transitions", [])
            _log_transition_issues(oid, states, transitions)
            ent = FSMEntity(hass, oid, initial, states, transitions)
            new_entities.append(ent)

        if new_entities:
            await store["component"].async_add_entities(new_entities)
            for ent in new_entities:
                store["entities_by_id"][ent.entity_id] = ent
                store["entities_by_object_id"][ent._object_id] = ent
                _LOGGER.info("input_fsm.reload: added %s (%s)", ent._object_id, ent.entity_id)

        # Update
        for oid in to_update:
            ent = old_by_object.get(oid)
            if ent:
                await ent.async_apply_config(new_cfg[oid])
                _LOGGER.info("input_fsm.reload: updated %s (%s)", oid, ent.entity_id)

    hass.services.async_register(DOMAIN, SERVICE_TRIGGER, svc_trigger)
    hass.services.async_register(DOMAIN, SERVICE_SET_STATE, svc_set_state)
    hass.services.async_register(DOMAIN, SERVICE_RESET, svc_reset)
    hass.services.async_register(DOMAIN, SERVICE_RELOAD, svc_reload)

    _LOGGER.info("input_fsm setup complete with %d entity(ies)", len(entities))
    return True
