# Changelog

## 0.2.0

- Web page in the Home Assistant sidebar (ingress): per device who is in control
  (ILSE, an energy manager that only watches, one that may steer, or one that has
  taken over), live state of charge and power, the last instruction and a timeline.
  A banner shows at once when an external energy manager has taken control.
- Option `self_test_every_min`: the self-test energy manager repeats its test
  instruction at this interval (0 = once), handy for a demo.

## 0.1.1

- Start through a with-contenv script so the add-on can read Home Assistant
  (the base image scrubbed SUPERVISOR_TOKEN; state of charge and power were missing).

## 0.1.0

- First version, read-only shadow mode: batteries as S2 FRBC, switches as S2 OMBC,
  instructions are acknowledged, reported as `REJECTED` and logged.
- Built-in self-test CEM.
- Based on [s2-python](https://github.com/flexiblepower/s2-python) 0.11.
