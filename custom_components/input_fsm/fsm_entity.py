from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.template import Template
from homeassistant.helpers.event import async_call_later

from .const import (
    EVENT_TRANSITION_FAILED,
    EVENT_TRANSITION_STARTED,
    EVENT_TRANSITION_SUCCEEDED,
    WILDCARD,
)

_LOGGER = logging.getLogger(__name__)


class FSMEntity(RestoreEntity):
    _attr_icon = "mdi:state-machine"

    def __init__(
        self,
        hass: HomeAssistant,
        object_id: str,
        initial_state: Optional[str],
        states: List[Dict[str, Any]],
        transitions: List[Dict[str, Any]],
    ) -> None:
        self.hass = hass
        self._object_id = object_id
        self._attr_name = object_id.replace("_", " ").title()
        self._initial = initial_state
        self._state = initial_state
        self._transitions = transitions or []
        self._state_definitions = states or []
        self._state_lookup = {s.get("name"): s for s in self._state_definitions}

        self._lock = asyncio.Lock()
        self._timeout_unsub = None
        self._recent = []  # ring buffer of last transitions

    @property
    def unique_id(self) -> str:
        return f"input_fsm:{self._object_id}"

    @property
    def name(self) -> str:
        return self._attr_name

    @property
    def state(self) -> Optional[str]:
        return self._state

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        meta = self._state_lookup.get(self._state, {}) if self._state is not None else {}
        current_triggers = sorted(
            {
                t.get("trigger")
                for t in self._transitions
                if t.get("source") == self._state or t.get("source") == WILDCARD
            }
        )
        return {
            "current_state_description": meta.get("description", ""),
            "available_states": [s.get("name") for s in self._state_definitions],
            "available_triggers": current_triggers,
            "available_transitions": self._transitions,
            "recent_transitions": self._recent[-10:],
        }

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last and last.state and last.state in self._state_lookup:
            self._state = last.state
            _LOGGER.debug("%s restored state to %s", self.entity_id, self._state)
        self.async_write_ha_state()

    async def async_apply_config(self, cfg: Dict[str, Any]) -> None:
        async with self._lock:
            self._cancel_timeout()
            old_state = self._state

            self._initial = cfg.get("initial", self._initial)
            self._state_definitions = cfg.get("states", self._state_definitions) or []
            self._state_lookup = {s.get("name"): s for s in self._state_definitions}
            self._transitions = cfg.get("transitions", self._transitions) or []

            if old_state not in self._state_lookup:
                _LOGGER.warning("FSM %s: current state '%s' not in new config; resetting to initial '%s'",
                                self.entity_id, old_state, self._initial)
                self._state = self._initial

            self.async_write_ha_state()
            _LOGGER.info("FSM %s: config applied (states=%d, transitions=%d)",
                         self.entity_id, len(self._state_definitions), len(self._transitions))

    async def async_trigger(self, trigger: str) -> bool:
        async with self._lock:
            transition_id = str(uuid.uuid4())
            matching = None
            for t in self._transitions:
                src = t.get("source")
                if t.get("trigger") == trigger and (src == self._state or src == WILDCARD):
                    matching = t
                    break

            if not matching:
                self._fire_event(EVENT_TRANSITION_FAILED, {
                    "transition_id": transition_id,
                    "reason": "no_matching_transition",
                    "trigger": trigger,
                    "from": self._state,
                })
                _LOGGER.debug("FSM %s: no matching transition for trigger '%s' in state '%s'",
                              self.entity_id, trigger, self._state)
                return False

            guard_expr = matching.get("guard")
            guard_value = None
            if guard_expr is not None:
                guard_value = await self._eval_guard(guard_expr)
                if not guard_value:
                    self._fire_event(EVENT_TRANSITION_FAILED, {
                        "transition_id": transition_id,
                        "reason": "guard_false",
                        "trigger": trigger,
                        "from": self._state,
                        "guard_value": str(guard_value),
                    })
                    _LOGGER.debug("FSM %s: guard evaluated false; trigger=%s guard=%s",
                                  self.entity_id, trigger, guard_expr)
                    return False

            dest = matching.get("dest")
            timeout_cfg = matching.get("timeout")
            actions = matching.get("actions", [])

            self._fire_event(EVENT_TRANSITION_STARTED, {
                "transition_id": transition_id,
                "trigger": trigger,
                "from": self._state,
                "to": dest,
                "guard_value": str(guard_value) if guard_expr is not None else None,
            })

            prev = self._state
            self._state = dest
            self.async_write_ha_state()

            self._cancel_timeout()
            if isinstance(timeout_cfg, dict):
                seconds = float(timeout_cfg.get("seconds", 0))
                timeout_dest = timeout_cfg.get("dest")
                if seconds > 0 and timeout_dest in self._state_lookup:
                    self._schedule_timeout(seconds, timeout_dest)

            actions_status = await self._run_actions(actions)

            self._recent.append({"transition_id": transition_id, "trigger": trigger, "from": prev, "to": dest})

            self._fire_event(EVENT_TRANSITION_SUCCEEDED, {
                "transition_id": transition_id,
                "trigger": trigger,
                "from": prev,
                "to": dest,
                "actions_status": actions_status,
            })
            _LOGGER.debug("FSM %s: transition %s -> %s via '%s'", self.entity_id, prev, dest, trigger)
            return True

    async def async_set_state(self, state: str) -> bool:
        async with self._lock:
            if state not in self._state_lookup:
                _LOGGER.error("FSM %s: set_state invalid '%s'", self.entity_id, state)
                return False
            prev = self._state
            self._state = state
            self.async_write_ha_state()
            self._cancel_timeout()
            self._recent.append({"trigger": "set_state", "from": prev, "to": state})
            return True

    async def async_reset(self) -> None:
        await self.async_set_state(self._initial)

    async def _eval_guard(self, expr: str) -> bool:
        try:
            tpl = Template(expr, self.hass)
            rendered = tpl.async_render(parse_result=False)
            val = str(rendered).strip().lower()
            res = val in ("1", "true", "yes", "on")
            _LOGGER.debug("FSM %s: guard '%s' -> '%s' (%s)",
                          self.entity_id, expr, rendered, res)
            return res
        except Exception as e:
            _LOGGER.warning("FSM %s: guard error for '%s': %s", self.entity_id, expr, e)
            return False

    async def _run_actions(self, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for act in actions or []:
            svc = act.get("service")
            data = act.get("data", {})
            if not svc or "." not in svc:
                _LOGGER.error("FSM %s: bad action service '%s'", self.entity_id, svc)
                results.append({"service": svc, "ok": False, "error": "bad_service"})
                continue
            domain, service = svc.split(".", 1)
            try:
                await self.hass.services.async_call(domain, service, data, blocking=False)
                results.append({"service": svc, "ok": True})
            except Exception as e:
                _LOGGER.error("FSM %s: action %s failed: %s", self.entity_id, svc, e)
                results.append({"service": svc, "ok": False, "error": str(e)})
        return results

    def _schedule_timeout(self, seconds: float, dest: str) -> None:
        def _cb(_now):
            self.hass.async_create_task(self._timeout_transition(dest))

        self._timeout_unsub = async_call_later(self.hass, seconds, _cb)
        _LOGGER.debug("FSM %s: timeout scheduled in %.2fs to '%s'",
                      self.entity_id, seconds, dest)

    async def _timeout_transition(self, dest: str) -> None:
        async with self._lock:
            prev = self._state
            self._state = dest
            self.async_write_ha_state()
            self._recent.append({"trigger": "timeout", "from": prev, "to": dest})
            self._timeout_unsub = None
            _LOGGER.debug("FSM %s: timeout fired to '%s'", self.entity_id, dest)

    def _cancel_timeout(self) -> None:
        if self._timeout_unsub:
            self._timeout_unsub()
            self._timeout_unsub = None
            _LOGGER.debug("FSM %s: timeout cancelled", self.entity_id)

    def _fire_event(self, event_type: str, data: Dict[str, Any]) -> None:
        if not self.hass:
            return
        payload = {"entity_id": getattr(self, "entity_id", None)}
        payload.update({k: v for k, v in (data or {}).items() if v is not None})
        self.hass.bus.async_fire(event_type, payload)
