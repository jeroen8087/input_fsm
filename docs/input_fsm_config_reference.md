# Input FSM – YAML Configuration Reference

This document describes the full YAML configuration schema supported by the **input_fsm** integration (v0.3.x). Use it as a quick reference for defining one or more finite‑state machines in Home Assistant.

> Tip: Place your FSM definitions inside a package (e.g., `fsm_packages/your_fsm.yaml`) so you can keep the FSM, its automations, and scripts together.

---

## 1) Top‑level schema

You define one or more FSMs under the `input_fsm:` key. Each key under `input_fsm:` is an **object_id** for the FSM entity (the entity id will become `input_fsm.<object_id>`).

```yaml
input_fsm:
  <object_id>:
    initial: <state_name>
    states: [<state_object>, ...]
    transitions: [<transition_object>, ...]
```

| Key           | Type                | Required | Default | Description |
|---------------|---------------------|----------|---------|-------------|
| `initial`     | string              | yes      | –       | Name of the state the FSM starts in. Must be listed in `states`.|
| `states`      | list of objects     | yes      | –       | Declares the available states and optional descriptions.|
| `transitions` | list of objects     | yes      | –       | Declares allowed transitions between states, with optional guards, timeouts, and actions.|

---

## 2) State objects

Each state is defined as an object with a name and an optional description.

```yaml
states:
  - name: off
    description: "Light is off"
  - name: on
    description: "Light is on"
```

| Field            | Type   | Required | Default | Notes |
|------------------|--------|----------|---------|-------|
| `name`           | string | yes      | –       | Must be unique within the FSM.|
| `description`    | string | no       | `""`    | Shown as `current_state_description` attribute when the FSM is in this state.|

---

## 3) Transition objects

A transition allows you to move from one state to another when a **trigger** is fired. Transitions can be protected by a **guard** (template), can schedule a **timeout**, and can execute **actions** (service calls).

```yaml
transitions:
  - trigger: motion
    source: "*"
    dest: on
    guard: "{{ is_state('binary_sensor.motion_living', 'on') }}"
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
```

| Field        | Type               | Required | Default | Notes |
|--------------|--------------------|----------|---------|-------|
| `trigger`    | string             | yes      | –       | Name of the trigger you will fire via the service `input_fsm.trigger`.|
| `source`     | string             | yes      | –       | Source state this transition applies to. Use `*` to match **any** current state (wildcard).|
| `dest`       | string             | yes      | –       | Destination state. Must exist in `states`.|
| `guard`      | Jinja2 template    | no       | –       | Evaluated at trigger time. Transition proceeds only if it renders “true-ish” (`true`, `on`, `1`, `yes`). On template error, the transition fails.|
| `timeout`    | object             | no       | –       | Schedules an **automatic transition** after N seconds (see timeout object). Canceled if state changes before it fires.|
| `actions`    | list of objects    | no       | `[]`    | List of service calls executed after the state has changed to `dest`.|

**Matching precedence:** if multiple transitions share the same `trigger`, the **first matching entry** in your YAML wins. Put specific `source` rows before a wildcard row.

---

### 3.1) Timeout object

Schedules an automatic transition after a delay. This is evaluated after the FSM has entered the `dest` of the current transition. If the FSM leaves that state before the delay elapses, the timeout is canceled.

```yaml
timeout:
  seconds: 120
  dest: off
```

| Field     | Type    | Required | Notes |
|-----------|---------|----------|-------|
| `seconds` | number  | yes      | Delay (float or int).|
| `dest`    | string  | yes      | Destination state to jump to when the timeout fires. Must exist in `states`.|

The timeout internally generates a `"timeout"` trigger, allowing you to create explicit transitions with `trigger: timeout` if you want to attach actions to the timeout hop.

---

### 3.2) Action objects

Each action calls a Home Assistant service. You can call automations (`automation.trigger`), scripts (`script.turn_on` with variables), lights, etc.

```yaml
actions:
  - service: script.turn_on
    target:
      entity_id: script.my_complex_action
    data:
      variables:
        reason: "dimmed"
        level: 30
```

| Field     | Type   | Required | Default | Notes |
|-----------|--------|----------|---------|-------|
| `service` | string | yes      | –       | Must be `<domain>.<service>` (e.g. `light.turn_on`).|
| `data`    | map    | no       | `{}`    | Payload for the service call (free-form).|
| `target`  | map    | no       | –       | Optional target; same semantics as standard HA service targets.|

> Execution order: state changes first, then actions run (non‑blocking). Any errors are logged and exposed in the `transition_succeeded` event payload as `actions_status`.

---

## 4) Includes and packages

You can keep your FSMs in a dedicated file or directory, or bundle them together with automations and scripts using **packages** (recommended).

**Option A: packages**
```yaml
# configuration.yaml
homeassistant:
  packages: !include_dir_named fsm_packages
```
```yaml
# fsm_packages/livingroom.yaml
input_fsm:  # FSMs
  livingroom_light: ...
automation:  # triggers to call input_fsm.trigger
  - ...
script:      # reusable actions
  my_complex_action: ...
```

**Option B: domain includes**
```yaml
# configuration.yaml
input_fsm: !include_dir_merge_named fsm/
automation: !include_dir_merge_list automations/
script: !include scripts.yaml
```

---

## 5) Services (for reference)

Although not part of the YAML schema, you will use these services to drive and manage your FSMs:

| Service                | Data example |
|------------------------|--------------|
| `input_fsm.trigger`    | `{ "entity_id": "input_fsm.livingroom_light", "trigger": "motion" }` |
| `input_fsm.set_state`  | `{ "entity_id": "input_fsm.livingroom_light", "state": "off" }` |
| `input_fsm.reset`      | `{ "entity_id": "input_fsm.livingroom_light" }` |
| `input_fsm.reload`     | `{}` (reloads YAML without restarting Home Assistant) |

---

## 6) Entity attributes (read-only)

These attributes are useful in dashboards and for debugging:

| Attribute                  | Type  | Description |
|---------------------------|-------|-------------|
| `current_state_description` | string | Description of the current state (from `states[].description`). |
| `available_states`        | list  | All declared state names. |
| `available_triggers`      | list  | Triggers valid from the current `source` (including wildcard transitions). |
| `available_transitions`   | list  | Raw transition objects as configured. |
| `recent_transitions`      | list  | Last few transitions with `from`, `to`, and `trigger`. |

---

## 7) Events (for reference)

The integration fires events on the HA event bus during transitions. These are helpful for logging, metrics, and advanced orchestration.

| Event name                        | When |
|----------------------------------|------|
| `input_fsm.transition_started`   | Right before changing state. |
| `input_fsm.transition_succeeded` | After state change and actions dispatch. |
| `input_fsm.transition_failed`    | When no transition matched or a guard evaluated to false.|

Each event contains at least: `entity_id`, `trigger`, `from`, and `to` (except failures without a `to`). It also includes a `transition_id` and diagnostic fields such as `guard_value` or `actions_status`.

---

## 8) Validation and common pitfalls

- `initial` must be present in `states[].name` (a warning is logged if not).  
- `dest` in each transition must be a valid state.  
- `source` may be a valid state **or** the wildcard `*`.  
- If multiple rows could match a trigger, the **first matching row** in your YAML is used. Put specific cases before wildcard rows.  
- Guards render as text and are evaluated as true/false using “true‑ish” parsing (`true`, `on`, `yes`, `1`). Template errors make the guard false.  
- Timeouts are canceled whenever the FSM state changes before the timeout fires.  

---

## 9) Minimal example

```yaml
input_fsm:
  hallway_light:
    initial: "off"
    states:
      - name: off
      - name: on
    transitions:
      - trigger: motion
        source: "*"
        dest: on
        actions:
          - service: light.turn_on
            target: { entity_id: light.hallway }
      - trigger: timeout
        source: on
        dest: off
        actions:
          - service: light.turn_off
            target: { entity_id: light.hallway }
```

Combine with automations to feed triggers:
```yaml
automation:
  - alias: Hallway: motion → trigger
    trigger:
      - platform: state
        entity_id: binary_sensor.hallway_motion
        to: "on"
    action:
      - service: input_fsm.trigger
        data:
          entity_id: input_fsm.hallway_light
          trigger: motion

  - alias: Hallway: inactivity → timeout
    trigger:
      - platform: state
        entity_id: binary_sensor.hallway_motion
        to: "off"
        for: "00:02:00"
    action:
      - service: input_fsm.trigger
        data:
          entity_id: input_fsm.hallway_light
          trigger: timeout
```

---

## 10) Reload during development

After editing YAML, call:
- `input_fsm.reload` to reload FSMs, and
- `automation.reload` for automations (if you changed them).

No Home Assistant restart required.
