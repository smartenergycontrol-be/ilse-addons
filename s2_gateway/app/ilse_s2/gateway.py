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
from s2python.connection.quickstarts import BlockingWebsocketClientRM
from s2python.connection.sync.control_type.class_based import (
    FRBCControlType,
    NoControlControlType,
    OMBCControlType,
)
from s2python.frbc import (
    FRBCActuatorDescription,
    FRBCActuatorStatus,
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
        self.stats = {
            "control_type": None,
            "connected": False,
            "instructions": 0,
            "last_instruction": None,
            "last_status": None,
        }

    def power_w(self) -> float | None:
        factor = float(self.conf.get("power_factor") or 1)
        return self.ha.number(self.conf.get("power_entity"), factor)

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

        pairs = [(a, b) for a in self.modes for b in self.modes if a != b]
        return FRBCSystemDescription(
            message_id=uuid.uuid4(),
            valid_from=utcnow(),
            actuators=[
                FRBCActuatorDescription(
                    id=self.actuator,
                    diagnostic_label=self.dev.name,
                    supported_commodities=[Commodity.ELECTRICITY],
                    operation_modes=[mode(k) for k in self.modes],
                    transitions=_transitions(self.dev.name, self.modes, pairs),
                    timers=[],
                )
            ],
            storage=FRBCStorageDescription(
                diagnostic_label=self.dev.name,
                fill_level_label="SoC %",
                provides_leakage_behaviour=False,
                provides_fill_level_target_profile=False,
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
        self.dev.send(connection, self.description())
        self.dev.start_loop(connection, self.tick)
        log.info("%s: FRBC active (state of charge, charge/idle/discharge)", self.dev.name)

    def deactivate(self, connection) -> None:
        self.dev.active = False


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
        self.dev.send(connection, self.description())
        self.dev.start_loop(connection, self.tick)
        log.info("%s: OMBC active (off/on %s W)", self.dev.name, self.w)

    def deactivate(self, connection) -> None:
        self.dev.active = False


class NoControl(NoControlControlType):
    def __init__(self, dev: Device):
        self.dev = dev

    def activate(self, connection) -> None:
        self.dev.stats["control_type"] = "NOT_CONTROLABLE"
        self.dev.start_loop(connection, lambda c: None)

    def deactivate(self, connection) -> None:
        self.dev.active = False


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
        elif typ == "switch":
            roles = [Role(role=RoleType.ENERGY_CONSUMER, commodity=Commodity.ELECTRICITY)]
            cts = [SwitchOMBC(dev), NoControl(dev)]
        else:
            raise ValueError(f"device {dev.name}: unknown type {typ} (battery, switch)")
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

    def run_device(self, dev: Device) -> None:
        url = self.conf["cem_url"].replace("{rm_id}", str(dev.rm_id))
        while not self._stop.is_set():
            try:
                details, cts = self.asset(dev)
                conn = BlockingWebsocketClientRM(url=url, asset_details=details, control_types=cts)
                dev.stats["connected"] = True
                log.info("%s: connecting to %s as RM %s", dev.name, url, dev.rm_id)
                conn.start()
                conn.wait_till_done()
            except Exception as e:  # noqa: BLE001 - retry
                log.warning("%s: connection lost: %s", dev.name, e)
            dev.stats["connected"] = False
            dev.active = False
            self._stop.wait(float(self.conf.get("reconnect_s", 30)))

    def start(self) -> None:
        for d in self.devices:
            threading.Thread(target=self.run_device, args=(d,), daemon=True, name=d.name).start()

    def stop(self) -> None:
        self._stop.set()

    def health(self) -> dict:
        return {
            "cem": self.conf.get("cem_url"),
            "mode": "shadow (read-only)",
            "devices": {d.name: {"rm_id": str(d.rm_id), **d.stats} for d in self.devices},
        }
