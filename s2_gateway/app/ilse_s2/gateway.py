"""S2 resource managers for Home Assistant devices (read-only shadow mode).

One resource manager (RM) per device, each with its own WebSocket connection to the
customer energy manager (CEM); in S2 over WebSocket the RM is the client. The
gateway only reads Home Assistant. Instructions from the CEM are acknowledged,
reported back as REJECTED (nothing is executed in this version) and logged.

Device types:
  battery -> FRBC: fill level = state of charge (%), one actuator with the
             operation modes charge, idle and discharge. Power in W, positive =
             consumption (charging), negative = production (discharging).
  switch  -> OMBC: operation modes off and on (fixed power).
"""

from __future__ import annotations

import asyncio
import collections
import datetime as dt
import json
import logging
import os
import threading
import urllib.request
import uuid

from s2python.common import (
    Commodity,
    CommodityQuantity,
    Currency,
    Duration,
    InstructionStatus,
    InstructionStatusUpdate,
    NumberRange,
    PowerMeasurement,
    PowerRange,
    PowerValue,
    Role,
    RoleType,
    Transition,
)
from s2python.connection import AssetDetails
from s2python.connection.async_.medium.websocket import WebsocketClientMedium
from s2python.connection.sync import S2SyncConnection
from s2python.connection.sync.control_type.class_based import (
    ResourceManagerHandler,
)
from s2python.connection.sync.control_type.class_based import (
    FRBCControlType,
    NoControlControlType,
    OMBCControlType,
)
from s2python.frbc import (
    FRBCActuatorDescription,
    FRBCActuatorStatus,
    FRBCFillLevelTargetProfile,
    FRBCFillLevelTargetProfileElement,
    FRBCOperationMode,
    FRBCOperationModeElement,
    FRBCStorageDescription,
    FRBCStorageStatus,
    FRBCSystemDescription,
)
from s2python.ombc import OMBCOperationMode, OMBCStatus, OMBCSystemDescription

log = logging.getLogger("ilse_s2.gateway")
NS = uuid.UUID("5ec0a0d2-11e5-4a2b-9a7e-1a5e00000000")
P3 = CommodityQuantity.ELECTRIC_POWER_3_PHASE_SYMMETRIC


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def stable_id(*parts: str) -> uuid.UUID:
    """Stable ids per installation and device, so a CEM recognises a device after a restart."""
    return uuid.uuid5(NS, "/".join(parts))


class HaReader:
    """Reads Home Assistant states (Supervisor API in an add-on, else HA_URL + HA_TOKEN)."""

    def __init__(self, base: str | None = None, token: str | None = None):
        sup = os.environ.get("SUPERVISOR_TOKEN")
        self.base = base or (
            "http://supervisor/core/api"
            if sup
            else os.environ.get("HA_URL", "http://localhost:8123") + "/api"
        )
        self.token = token or sup or os.environ.get("HA_TOKEN", "")

    def state(self, entity: str | None) -> dict | None:
        if not entity:
            return None
        req = urllib.request.Request(
            f"{self.base}/states/{entity}", headers={"Authorization": f"Bearer {self.token}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except Exception:  # noqa: BLE001 - a missing value is not a gateway error
            return None

    def number(self, entity: str | None, factor: float = 1.0) -> float | None:
        st = self.state(entity)
        try:
            v = float((st or {}).get("state"))
        except (TypeError, ValueError):
            return None
        unit = ((st or {}).get("attributes") or {}).get("unit_of_measurement")
        return v * factor * (1000.0 if unit == "kW" else 1.0)


class Device:
    """Shared device logic: measuring, logging instructions, periodic status."""

    def __init__(self, conf: dict, site: str, ha, gw: Gateway):
        self.conf = conf
        self.name = conf["name"]
        self.ha = ha
        self.gw = gw
        self.rm_id = stable_id(site, self.name)
        self.active = False
        self._stop = threading.Event()
        self.events: collections.deque = collections.deque(maxlen=60)
        self.stats = {
            "control_type": None,
            "connected": False,
            "connected_since": None,
            "instructions": 0,
            "last_instruction": None,
            "last_status": None,
            "soc": None,
            "power_w": None,
            "plugged_in": None,
            "target": None,
        }

    def event(self, kind: str, text: str, **kw) -> None:
        """Timeline entry for the web page (newest last)."""
        self.events.append({"t": utcnow().isoformat(), "kind": kind, "text": text, **kw})

    def power_w(self) -> float | None:
        factor = float(self.conf.get("power_factor") or 1)
        w = self.ha.number(self.conf.get("power_entity"), factor)
        self.stats["power_w"] = None if w is None else round(w, 1)
        return w

    def send(self, connection, msg) -> None:
        try:
            connection.send_msg_and_await_reception_status(msg, raise_on_error=False)
        except TypeError:  # older s2-python without raise_on_error
            connection.send_msg_and_await_reception_status(msg)

    def measurement(self, connection) -> None:
        w = self.power_w()
        if w is None:
            return
        self.send(
            connection,
            PowerMeasurement(
                message_id=uuid.uuid4(),
                measurement_timestamp=utcnow(),
                values=[PowerValue(commodity_quantity=P3, value=round(w, 1))],
            ),
        )

    def record_instruction(self, connection, msg, what: dict) -> None:
        self.stats["instructions"] += 1
        rec = {
            "type": "s2-instruction",
            "device": self.name,
            "control_type": self.stats["control_type"],
            "received": utcnow().isoformat(),
            "execution_time": str(getattr(msg, "execution_time", "")),
            "status": "REJECTED",
            "shadow": True,
            **what,
        }
        self.stats["last_instruction"] = rec
        self.gw.record(rec)
        desc = ", ".join(f"{k} {v}" for k, v in what.items())
        self.event("instruction", f"Instruction: {desc}. Rejected, shadow mode (not executed)", **what)
        log.info("%s: instruction %s -> REJECTED (shadow mode, not executed)", self.name, what)
        self.send(
            connection,
            InstructionStatusUpdate(
                message_id=uuid.uuid4(),
                instruction_id=msg.id,
                status_type=InstructionStatus.REJECTED,
                timestamp=utcnow(),
            ),
        )

    def loop(self, connection, tick) -> None:
        interval = float(self.gw.conf.get("interval_s", 30))
        while self.active and not self._stop.is_set():
            try:
                tick(connection)
                self.measurement(connection)
                self.stats["last_status"] = utcnow().isoformat()
            except Exception as e:  # noqa: BLE001
                log.warning("%s: status not sent: %s", self.name, e)
            self._stop.wait(interval)

    def start_loop(self, connection, tick) -> None:
        self.active = True
        threading.Thread(target=self.loop, args=(connection, tick), daemon=True).start()


def _transitions(name: str, modes: dict, pairs) -> list[Transition]:
    return [
        Transition(
            id=stable_id(name, "t", a, b),
            from_=modes[a],
            to=modes[b],
            start_timers=[],
            blocking_timers=[],
            abnormal_condition_only=False,
        )
        for a, b in pairs
    ]


class BatteryFRBC(FRBCControlType):
    def __init__(self, dev: Device):
        self.dev = dev
        c = dev.conf
        self.cap_kwh = float(c.get("capacity_kwh") or 10)
        self.max_in = float(c.get("max_charge_w") or 2500)
        self.max_out = float(c.get("max_discharge_w") or 2500)
        self.actuator = stable_id(dev.name, "actuator")
        self.modes = {k: stable_id(dev.name, "mode", k) for k in ("charge", "idle", "discharge")}
        self.ranges = {
            "charge": (0.0, self.max_in),
            "idle": (0.0, 0.0),
            "discharge": (-self.max_out, 0.0),
        }
        self.provides_target = False

    def offered(self) -> list[str]:
        """Operation modes offered to the CEM right now."""
        return list(self.modes)

    def rate(self, w: float) -> float:
        """Fill rate in %/s at w watt (positive = charging)."""
        return w / (self.cap_kwh * 36000.0)

    def description(self) -> FRBCSystemDescription:
        def mode(key):
            lo, hi = self.ranges[key]
            return FRBCOperationMode(
                id=self.modes[key],
                diagnostic_label=key,
                abnormal_condition_only=False,
                elements=[
                    FRBCOperationModeElement(
                        fill_level_range=NumberRange(start_of_range=0, end_of_range=100),
                        fill_rate=NumberRange(
                            start_of_range=self.rate(lo), end_of_range=self.rate(hi)
                        ),
                        power_ranges=[
                            PowerRange(start_of_range=lo, end_of_range=hi, commodity_quantity=P3)
                        ],
                    )
                ],
            )

        keys = self.offered()
        pairs = [(a, b) for a in keys for b in keys if a != b]
        return FRBCSystemDescription(
            message_id=uuid.uuid4(),
            valid_from=utcnow(),
            actuators=[
                FRBCActuatorDescription(
                    id=self.actuator,
                    diagnostic_label=self.dev.name,
                    supported_commodities=[Commodity.ELECTRICITY],
                    operation_modes=[mode(k) for k in keys],
                    transitions=_transitions(self.dev.name, self.modes, pairs),
                    timers=[],
                )
            ],
            storage=FRBCStorageDescription(
                diagnostic_label=self.dev.name,
                fill_level_label="SoC %",
                provides_leakage_behaviour=False,
                provides_fill_level_target_profile=self.provides_target,
                provides_usage_forecast=False,
                fill_level_range=NumberRange(start_of_range=0, end_of_range=100),
            ),
        )

    def current_mode(self) -> tuple[uuid.UUID, float]:
        w = self.dev.power_w() or 0.0
        if w > 50:
            return self.modes["charge"], min(1.0, w / self.max_in)
        if w < -50:  # range -max..0: factor 0 = full discharge
            return self.modes["discharge"], max(0.0, 1.0 + w / self.max_out)
        return self.modes["idle"], 0.0

    def tick(self, connection) -> None:
        soc = self.dev.ha.number(self.dev.conf.get("soc_entity"))
        self.dev.stats["soc"] = soc
        if soc is not None:
            self.dev.send(
                connection, FRBCStorageStatus(message_id=uuid.uuid4(), present_fill_level=soc)
            )
        mode, factor = self.current_mode()
        self.dev.send(
            connection,
            FRBCActuatorStatus(
                message_id=uuid.uuid4(),
                actuator_id=self.actuator,
                active_operation_mode_id=mode,
                operation_mode_factor=factor,
            ),
        )

    def handle_instruction(self, connection, msg, send_okay) -> None:
        send_okay()
        key = next((k for k, v in self.modes.items() if v == msg.operation_mode), "?")
        lo, hi = self.ranges.get(key, (0.0, 0.0))
        w = lo + (hi - lo) * float(msg.operation_mode_factor)  # factor 0 = start, 1 = end
        what = {"mode": key, "factor": msg.operation_mode_factor, "power_w": round(w)}
        self.dev.record_instruction(connection, msg, what)

    def activate(self, connection) -> None:
        self.dev.stats["control_type"] = "FRBC"
        self.dev.event("control", "Energy manager selected fill rate based (FRBC): it may now send instructions")
        self.dev.send(connection, self.description())
        self.dev.start_loop(connection, self.tick)
        log.info("%s: FRBC active (state of charge, charge/idle/discharge)", self.dev.name)

    def deactivate(self, connection) -> None:
        self.dev.active = False
        self.dev.event("control", "Control type deactivated")


class EvFRBC(BatteryFRBC):
    """Electric vehicle at a charge point as FRBC.

    Fill level = the car's state of charge. Charging is only offered while the car
    is plugged in; on plug or unplug the gateway sends a new system description.
    With `target_soc` and `departure` (HH:MM, local time) it also sends a fill level
    target profile: "at least target_soc % at the next departure".
    """

    def __init__(self, dev: Device):
        super().__init__(dev)
        c = dev.conf
        self.cap_kwh = float(c.get("capacity_kwh") or 75)
        self.max_in = float(c.get("max_charge_w") or 11000)
        self.min_in = float(c.get("min_charge_w") or 1400)
        self.modes = {k: stable_id(dev.name, "mode", k) for k in ("idle", "charge")}
        self.ranges = {"idle": (0.0, 0.0), "charge": (self.min_in, self.max_in)}
        self.target_soc = c.get("target_soc")
        self.departure = c.get("departure")
        self.provides_target = bool(self.target_soc and self.departure)
        self.was_plugged: bool | None = None

    def plugged(self) -> bool:
        ent = self.dev.conf.get("plugged_entity")
        if not ent:
            return True
        want = str(self.dev.conf.get("plugged_state") or "on")
        return (self.dev.ha.state(ent) or {}).get("state") == want

    def offered(self) -> list[str]:
        return ["idle", "charge"] if self.plugged() else ["idle"]

    def next_departure(self) -> dt.datetime | None:
        try:
            h, m = (int(x) for x in str(self.departure).split(":")[:2])
        except (TypeError, ValueError):
            return None
        now_local = dt.datetime.now().astimezone()
        dep = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        if dep <= now_local:
            dep += dt.timedelta(days=1)
        return dep.astimezone(dt.UTC)

    def target_profile(self) -> FRBCFillLevelTargetProfile | None:
        dep = self.next_departure() if self.provides_target else None
        if not dep:
            return None
        now = utcnow()
        to_dep = max(60, int((dep - now).total_seconds()))
        return FRBCFillLevelTargetProfile(
            message_id=uuid.uuid4(),
            start_time=now,
            elements=[
                FRBCFillLevelTargetProfileElement(
                    duration=Duration.from_milliseconds(to_dep * 1000),
                    fill_level_range=NumberRange(start_of_range=0, end_of_range=100),
                ),
                FRBCFillLevelTargetProfileElement(
                    duration=Duration.from_milliseconds(3600 * 1000),
                    fill_level_range=NumberRange(
                        start_of_range=float(self.target_soc), end_of_range=100
                    ),
                ),
            ],
        )

    def current_mode(self) -> tuple[uuid.UUID, float]:
        w = self.dev.power_w() or 0.0
        if w > 200 and self.plugged():
            span = max(1.0, self.max_in - self.min_in)
            return self.modes["charge"], max(0.0, min(1.0, (w - self.min_in) / span))
        return self.modes["idle"], 0.0

    def describe(self, connection) -> None:
        self.dev.send(connection, self.description())
        prof = self.target_profile()
        if prof is not None:
            self.dev.send(connection, prof)
            self.dev.stats["target"] = f"{self.target_soc}% at {self.departure}"

    def tick(self, connection) -> None:
        plugged = self.plugged()
        self.dev.stats["plugged_in"] = plugged
        if self.was_plugged is not None and plugged != self.was_plugged:
            self.dev.event(
                "connect" if plugged else "disconnect",
                "Car plugged in: charging offered to the energy manager"
                if plugged
                else "Car unplugged: only idle offered",
            )
            self.describe(connection)
        self.was_plugged = plugged
        super().tick(connection)

    def activate(self, connection) -> None:
        self.dev.stats["control_type"] = "FRBC"
        self.dev.event(
            "control", "Energy manager selected fill rate based (FRBC): it may now send instructions"
        )
        self.was_plugged = self.plugged()
        self.dev.stats["plugged_in"] = self.was_plugged
        self.describe(connection)
        self.dev.start_loop(connection, self.tick)
        log.info("%s: FRBC active (EV, plugged in: %s)", self.dev.name, self.was_plugged)


class SwitchOMBC(OMBCControlType):
    def __init__(self, dev: Device):
        self.dev = dev
        self.w = float(dev.conf.get("power_w") or 2000)
        self.modes = {k: stable_id(dev.name, "mode", k) for k in ("off", "on")}

    def description(self) -> OMBCSystemDescription:
        def mode(key, w):
            return OMBCOperationMode(
                id=self.modes[key],
                diagnostic_label=key,
                abnormal_condition_only=False,
                power_ranges=[PowerRange(start_of_range=w, end_of_range=w, commodity_quantity=P3)],
            )

        return OMBCSystemDescription(
            message_id=uuid.uuid4(),
            valid_from=utcnow(),
            operation_modes=[mode("off", 0.0), mode("on", self.w)],
            transitions=_transitions(
                self.dev.name, self.modes, [("off", "on"), ("on", "off")]
            ),
            timers=[],
        )

    def tick(self, connection) -> None:
        st = self.dev.ha.state(self.dev.conf.get("state_entity"))
        on = (st or {}).get("state") == "on" or (self.dev.power_w() or 0) > 0.3 * self.w
        self.dev.send(
            connection,
            OMBCStatus(
                message_id=uuid.uuid4(),
                # s2-python types this field as a string id, not a UUID
                active_operation_mode_id=str(self.modes["on" if on else "off"]),
                operation_mode_factor=1.0,
            ),
        )

    def handle_instruction(self, connection, msg, send_okay) -> None:
        send_okay()
        key = next((k for k, v in self.modes.items() if v == msg.operation_mode_id), "?")
        what = {"mode": key, "power_w": self.w if key == "on" else 0}
        self.dev.record_instruction(connection, msg, what)

    def activate(self, connection) -> None:
        self.dev.stats["control_type"] = "OMBC"
        self.dev.event("control", "Energy manager selected operation mode based (OMBC): it may now send instructions")
        self.dev.send(connection, self.description())
        self.dev.start_loop(connection, self.tick)
        log.info("%s: OMBC active (off/on %s W)", self.dev.name, self.w)

    def deactivate(self, connection) -> None:
        self.dev.active = False
        self.dev.event("control", "Control type deactivated")


class NoControl(NoControlControlType):
    def __init__(self, dev: Device):
        self.dev = dev

    def activate(self, connection) -> None:
        self.dev.stats["control_type"] = "NOT_CONTROLABLE"
        self.dev.event("control", "Energy manager selected not controllable: measurements only")
        self.dev.start_loop(connection, lambda c: None)

    def deactivate(self, connection) -> None:
        self.dev.active = False
        self.dev.event("control", "Control type deactivated")


class Gateway:
    def __init__(self, conf: dict, site: str, ha=None, record=None):
        self.conf = conf
        self.site = site
        self.ha = ha or HaReader()
        self.record = record or (lambda rec: None)
        self.devices = [Device(d, site, self.ha, self) for d in conf.get("devices") or []]
        self._stop = threading.Event()

    def asset(self, dev: Device) -> tuple[AssetDetails, list]:
        typ = dev.conf.get("type")
        if typ == "battery":
            roles = [Role(role=RoleType.ENERGY_STORAGE, commodity=Commodity.ELECTRICITY)]
            cts = [BatteryFRBC(dev), NoControl(dev)]
        elif typ == "ev":
            roles = [Role(role=RoleType.ENERGY_STORAGE, commodity=Commodity.ELECTRICITY)]
            cts = [EvFRBC(dev), NoControl(dev)]
        elif typ == "switch":
            roles = [Role(role=RoleType.ENERGY_CONSUMER, commodity=Commodity.ELECTRICITY)]
            cts = [SwitchOMBC(dev), NoControl(dev)]
        elif typ == "pv":  # measurements only for now; curtailment (PEBC) follows
            roles = [Role(role=RoleType.ENERGY_PRODUCER, commodity=Commodity.ELECTRICITY)]
            cts = [NoControl(dev)]
        else:
            raise ValueError(f"device {dev.name}: unknown type {typ} (battery, ev, switch, pv)")
        details = AssetDetails(
            resource_id=dev.rm_id,
            name=f"{self.site}/{dev.name}",
            instruction_processing_delay=Duration.from_milliseconds(30000),
            roles=roles,
            currency=Currency.EUR,
            provides_forecast=False,
            provides_power_measurements=[P3],
        )
        return details, cts

    def connect_once(self, dev: Device, url: str) -> None:
        """One S2 session over WebSocket, in this thread.

        Unlike the library quickstart (which disables certificate checks), wss:// is
        verified against the system trust store unless verify_certificate is false,
        and an optional bearer token is sent as in S2 Connect.
        """
        details, cts = self.asset(dev)
        loop = asyncio.new_event_loop()
        try:
            medium = WebsocketClientMedium(
                url=url,
                verify_certificate=bool(self.conf.get("verify_certificate", True)),
                bearer_token=self.conf.get("cem_token") or None,
            )
            loop.run_until_complete(medium.connect())
            conn = S2SyncConnection(medium=medium, eventloop=loop)
            ResourceManagerHandler(asset_details=details, control_types=cts).register_handlers(conn)
            dev.stats["connected"] = True
            dev.stats["connected_since"] = utcnow().isoformat()
            dev.event("connect", f"Connected to energy manager as S2 resource manager {dev.rm_id}")
            log.info("%s: connected to %s as RM %s", dev.name, url, dev.rm_id)
            conn.run()
        finally:
            loop.close()

    def run_device(self, dev: Device) -> None:
        url = self.conf["cem_url"].replace("{rm_id}", str(dev.rm_id))
        while not self._stop.is_set():
            try:
                self.connect_once(dev, url)
                dev.event("disconnect", "Connection closed")
            except Exception as e:  # noqa: BLE001 - retry
                log.warning("%s: connection lost: %s", dev.name, e)
                dev.event("disconnect", f"Connection failed: {str(e)[:120]}")
            dev.stats["connected"] = False
            dev.stats["connected_since"] = None
            dev.stats["control_type"] = None
            dev.active = False
            self._stop.wait(float(self.conf.get("reconnect_s", 30)))

    def start(self) -> None:
        for d in self.devices:
            threading.Thread(target=self.run_device, args=(d,), daemon=True, name=d.name).start()

    def stop(self) -> None:
        self._stop.set()

    def view(self) -> dict:
        """Everything the web page shows, including who is in control per device."""
        self_test = bool(self.conf.get("self_test_cem"))
        cem = "built-in test energy manager" if self_test else self.conf.get("cem_url", "")
        out = []
        for d in self.devices:
            st = dict(d.stats)
            ct = st["control_type"]
            last = st["last_instruction"]
            recent = False
            if last:
                age = utcnow() - dt.datetime.fromisoformat(last["received"])
                recent = age.total_seconds() < 15 * 60
            if not st["connected"]:
                state, label = "ilse", "ILSE in control"
            elif ct in (None, "NOT_CONTROLABLE"):
                state, label = "watching", "Energy manager connected, watching only"
            elif recent:
                state, label = "taken", "Taken over by external energy manager"
            else:
                state, label = "ready", "External energy manager may steer"
            out.append(
                {
                    "name": d.name,
                    "type": d.conf.get("type"),
                    "model": d.conf.get("label"),
                    "icon": d.conf.get("icon") or d.conf.get("type"),
                    "rm_id": str(d.rm_id),
                    "state": state,
                    "label": label,
                    "rating_w": d.conf.get("power_w")
                    or d.conf.get("max_discharge_w")
                    or d.conf.get("max_charge_w"),
                    "capacity_kwh": d.conf.get("capacity_kwh"),
                    **st,
                    "events": list(d.events),
                }
            )
        return {
            "site": self.site,
            "cem": cem,
            "self_test": self_test,
            "shadow": True,
            "now": utcnow().isoformat(),
            "devices": out,
        }

    def health(self) -> dict:
        return {
            "cem": self.conf.get("cem_url"),
            "mode": "shadow (read-only)",
            "devices": {d.name: {"rm_id": str(d.rm_id), **d.stats} for d in self.devices},
        }
