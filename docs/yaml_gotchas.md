# YAML Gotchas: Reserved Boolean Values

When defining FSMs (or any other Home Assistant configuration) you may run into issues caused by how YAML interprets certain words.  
In YAML 1.1 (which is what Python parsers like `ruamel.yaml` still use), a set of keywords are automatically converted into booleans.  
This means that writing `on` or `off` without quotes does not produce the string `"on"` or `"off"`, but instead the boolean values `true` or `false`.

## Boolean keywords in YAML 1.1

The following values (case-insensitive) are treated as booleans if left unquoted:

| Keyword variants            | Interpreted as | Example without quotes     | Correct usage (string) |
|-----------------------------|----------------|----------------------------|-------------------------|
| `y`, `Y`, `yes`, `Yes`, `YES` | `true`         | `flag: yes` → `flag: true` | `flag: "yes"`          |
| `n`, `N`, `no`, `No`, `NO`   | `false`        | `flag: no` → `flag: false` | `flag: "no"`           |
| `true`, `True`, `TRUE`       | `true`         | `flag: true`               | `flag: "true"`         |
| `false`, `False`, `FALSE`    | `false`        | `flag: false`              | `flag: "false"`        |
| `on`, `On`, `ON`             | `true`         | `state: on` → `state: true`| `state: "on"`          |
| `off`, `Off`, `OFF`          | `false`        | `state: off` → `state: false` | `state: "off"`      |

## Best practices

1. Always use quotes when you intend `on` or `off` (or any of the other keywords) to be **strings**, not booleans.
   ```yaml
   - trigger: motion
     source: "on"
     dest: "off"
   ```

2. This applies to states, triggers, and transition definitions in your FSMs, as well as anywhere else in Home Assistant configuration where these words appear.

3. Remember that Home Assistant entity states like `on`/`off` are stored as strings in the backend, so quoting them is the safest way to avoid YAML parsing surprises.

## References

- [YAML 1.1 specification, booleans](https://yaml.org/type/bool.html)  
- [YAML 1.2 update (only `true`/`false` remain booleans)](https://yaml.org/spec/1.2/spec.html#id2803629)  

---

**Rule of thumb:** If a word looks like a Home Assistant state but could be mistaken for a boolean (`on`, `off`, `yes`, `no`), always quote it.
