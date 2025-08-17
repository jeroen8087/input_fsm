# input_fsm
A Home Assistant integration that brings finite-state machine (FSM) logic to your automations. Define states, triggers, and transitions in YAML to model complex behavior with ease. Add structure and clarity to your automations — powerful, flexible, and surprisingly simple to use.

## Why would I use this?
Home Assistant automations can become complex when you try to model behavior over time. For example, you might want lights to behave differently when you’re at home, away, or sleeping, with extra conditions layered on top.  
Instead of endless conditionals, you can express the same logic as a finite-state machine:

- **States** represent the current mode (e.g. light off, on, dimmed).  
- **Triggers** represent events that cause change (motion, button press, timeout).  
- **Transitions** describe how you move between states, optionally running actions.  

With `input_fsm`, you keep all of this in one clean definition.

---

## Features
- Define FSMs in YAML, using Home Assistant’s include system.  
- Trigger state transitions via service calls (`input_fsm.trigger`).  
- Run actions on transitions (call any HA service).  
- Guards: condition templates that must pass before a transition can fire.  
- Timeouts: automatically fire a trigger after a delay.  
- Wildcards: match a trigger from any state using `source: "*"`.  
- Events (`transition_started`, `transition_succeeded`, `transition_failed`) for debugging or advanced orchestration.  
- Reload service (`input_fsm.reload`) so you can iterate without restarting Home Assistant.  

---

## Installation

### HACS (recommended)
1. Add this repository as a **custom integration** in HACS (category: Integration).  
2. Search for **Input FSM** in HACS and install.  
3. Restart Home Assistant once to activate.  

### Manual
1. Copy the `custom_components/input_fsm/` folder into your Home Assistant `config/custom_components/` directory.  
2. Restart Home Assistant.  

---

## Getting started

The easiest way to structure your configuration is with **packages**. That way, your FSM definition, automations, and scripts live together in one file and are easy to reload.

### 1. Enable packages in `configuration.yaml`
```yaml
homeassistant:
  packages: !include_dir_named fsm_packages
```

### 2. Create a package: `fsm_packages/livingroom_light.yaml`
```yaml
input_fsm:
  livingroom_light:
    initial: "off"
    states:
      - name: off
        description: "Light is off"
      - name: on
        description: "Light is fully on"
      - name: dimmed
        description: "Light is dimmed after inactivity"
    transitions:
      - trigger: motion
        source: "*"
        dest: on
        actions:
          - service: light.turn_on
            target: { entity_id: light.living_room }

      - trigger: no_motion
        source: on
        dest: dimmed
        timeout: { seconds: 120, dest: off }
        actions:
          - service: light.turn_on
            target: { entity_id: light.living_room }
            data: { brightness_pct: 30 }

      - trigger: timeout
        source: dimmed
        dest: off
        actions:
          - service: light.turn_off
            target: { entity_id: light.living_room }

automation:
  - id: fsm_livingroom_motion
    alias: FSM Livingroom: Motion detected
    trigger:
      - platform: state
        entity_id: binary_sensor.livingroom_motion
        to: "on"
    action:
      - service: input_fsm.trigger
        data:
          entity_id: input_fsm.livingroom_light
          trigger: motion

  - id: fsm_livingroom_no_motion
    alias: FSM Livingroom: No motion
    trigger:
      - platform: state
        entity_id: binary_sensor.livingroom_motion
        to: "off"
        for: "00:01:00"
    action:
      - service: input_fsm.trigger
        data:
          entity_id: input_fsm.livingroom_light
          trigger: no_motion
```

### 3. Reload without restart
- Call service: `input_fsm.reload` (reload FSM definitions).  
- Call service: `automation.reload` (reload automations).  
This allows very fast iteration without restarting Home Assistant.

---

## Advanced options

### Guards
Require a condition to pass before a transition fires:
```yaml
- trigger: lock_request
  source: unlocked
  dest: locked
  guard: "{{ is_state('binary_sensor.door_closed', 'on') }}"
  actions:
    - service: lock.lock
      target: { entity_id: lock.frontdoor }
```

### Wildcard transitions
Make a trigger apply from any state:
```yaml
- trigger: panic
  source: "*"
  dest: off
  actions:
    - service: light.turn_off
      target: { entity_id: all }
```

### Events
Every transition fires events you can listen for:
- `input_fsm.transition_started`  
- `input_fsm.transition_succeeded`  
- `input_fsm.transition_failed`  

Example:
```yaml
automation:
  - alias: FSM Logger
    trigger:
      - platform: event
        event_type: input_fsm.transition_failed
    action:
      - service: logbook.log
        data:
          name: FSM
          message: "Transition failed: {{ trigger.event.data }}"
```

---

## Services
- `input_fsm.trigger`  
  Fire a trigger for a given FSM.  

- `input_fsm.set_state`  
  Force an FSM into a state (bypassing transitions).  

- `input_fsm.reset`  
  Reset an FSM back to its initial state.  

- `input_fsm.reload`  
  Reload FSM definitions from YAML without restarting HA.  

---

## Debugging
Enable debug logs in `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.input_fsm: debug
```
Then use the Events developer tool in HA to watch transition events in real time.

---

## Known limitations
- No UI editor yet (YAML only).  
- Transition priority is determined by order in YAML (specific before wildcard).  
- State attributes like `available_triggers` are exposed but not (yet) visualized in the UI.  

---

## Roadmap
- Lovelace card for FSM visualization.  
- Optional config-flow (UI setup).  
- Priority field for transitions.  

---

## Contributing
This is a private side project. Contributions, bug reports, and ideas are welcome via GitHub issues. Pull requests are encouraged if you want to scratch an itch.
