# Changelog

## 0.1.1

- Start through a with-contenv script so the add-on can read Home Assistant
  (the base image scrubbed SUPERVISOR_TOKEN; state of charge and power were missing).

## 0.1.0

- First version, read-only shadow mode: batteries as S2 FRBC, switches as S2 OMBC,
  instructions are acknowledged, reported as `REJECTED` and logged.
- Built-in self-test CEM.
- Based on [s2-python](https://github.com/flexiblepower/s2-python) 0.11.
