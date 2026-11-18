# Changelog

## 0.4.0

- Device type `pv`: measurements only for now (S2 "not controllable"); curtailment
  through PEBC follows.
- Per device `label` (for example the model) and `icon`, with illustrations for
  battery, inverter, charger, car, boiler, switch and pv on the web page.
- `plugged_state`: the state of `plugged_entity` that means plugged in (default `on`),
  for chargers that expose a "free" sensor instead.

## 0.3.0

- New device type `ev`: an electric vehicle at a charge point as S2 FRBC. Fill level
  is the car's state of charge; charging is only offered while the car is plugged in
  (new system description on plug and unplug); optional target ("80% at 07:30") as
  an S2 fill level target profile.
- Web page: car card with plugged in and target.

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
