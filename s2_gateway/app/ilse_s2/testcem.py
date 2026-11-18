"""Minimal S2 test CEM (WebSocket server) for the self-test.

Not a real energy manager: it completes the handshake, selects the first
controllable control type, acknowledges every message, logs what each resource
manager describes and measures, and sends one test instruction per device after
its system description. The gateway rejects that instruction (shadow mode).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import uuid

from s2python.common import (
    ControlType,
    HandshakeResponse,
    ReceptionStatus,
    ReceptionStatusValues,
    SelectControlType,
)
from s2python.frbc import FRBCInstruction
from s2python.ombc import OMBCInstruction
from s2python.s2_parser import S2Parser
from websockets.asyncio.server import serve

log = logging.getLogger("ilse_s2.testcem")
PREFERENCE = [
    ControlType.FILL_RATE_BASED_CONTROL,
    ControlType.OPERATION_MODE_BASED_CONTROL,
    ControlType.POWER_ENVELOPE_BASED_CONTROL,
    ControlType.NOT_CONTROLABLE,
]


class Session:
    def __init__(self, ws, send_instruction: bool, events: list):
        self.ws = ws
        self.parser = S2Parser()
        self.send_instruction = send_instruction
        self.events = events
        self.rm = None
        self.instruction_sent = False

    async def send(self, msg) -> None:
        await self.ws.send(msg.to_json())

    def ev(self, kind: str, **kw) -> None:
        rec = {"t": dt.datetime.now(dt.UTC).isoformat(), "rm": self.rm, "type": kind, **kw}
        self.events.append(rec)
        del self.events[:-500]
        log.info("CEM %s", json.dumps(rec, default=str))

    async def handle(self, raw: str) -> None:
        msg = self.parser.parse_as_any_message(raw)
        t = msg.message_type
        if t == "ReceptionStatus":
            if msg.status != ReceptionStatusValues.OK:
                self.ev("reception", status=msg.status.value, label=msg.diagnostic_label)
            return
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await self.send(ReceptionStatus(subject_message_id=mid, status=ReceptionStatusValues.OK))
        if t == "Handshake":
            self.ev("handshake", role=msg.role.value, versions=msg.supported_protocol_versions)
            v = (msg.supported_protocol_versions or ["0.0.2-beta"])[0]
            await self.send(HandshakeResponse(message_id=uuid.uuid4(), selected_protocol_version=v))
        elif t == "ResourceManagerDetails":
            self.rm = msg.name or str(msg.resource_id)
            options = [c for c in PREFERENCE if c in msg.available_control_types]
            choice = options[0] if options else ControlType.NOT_CONTROLABLE
            self.ev(
                "rm-details",
                control_types=[c.value for c in msg.available_control_types],
                roles=[r.role.value for r in msg.roles],
                selected=choice.value,
            )
            await self.send(SelectControlType(message_id=uuid.uuid4(), control_type=choice))
        elif t == "FRBC.SystemDescription":
            act = msg.actuators[0]
            modes = {m.diagnostic_label: m for m in act.operation_modes}
            self.ev("frbc-description", modes=list(modes), storage=msg.storage.fill_level_label)
            if self.send_instruction and not self.instruction_sent and "discharge" in modes:
                self.instruction_sent = True
                await asyncio.sleep(2)
                self.ev("instruction-sent", mode="discharge", factor=0.6)
                await self.send(
                    FRBCInstruction(
                        message_id=uuid.uuid4(),
                        id=uuid.uuid4(),
                        actuator_id=act.id,
                        operation_mode=modes["discharge"].id,
                        operation_mode_factor=0.6,
                        execution_time=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30),
                        abnormal_condition=False,
                    )
                )
        elif t == "OMBC.SystemDescription":
            modes = {m.diagnostic_label: m for m in msg.operation_modes}
            self.ev("ombc-description", modes=list(modes))
            if self.send_instruction and not self.instruction_sent and "on" in modes:
                self.instruction_sent = True
                await asyncio.sleep(2)
                self.ev("instruction-sent", mode="on")
                await self.send(
                    OMBCInstruction(
                        message_id=uuid.uuid4(),
                        id=uuid.uuid4(),
                        operation_mode_id=modes["on"].id,
                        operation_mode_factor=1.0,
                        execution_time=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30),
                        abnormal_condition=False,
                    )
                )
        elif t == "PowerMeasurement":
            self.ev("measurement", w=[v.value for v in msg.values])
        elif t == "FRBC.StorageStatus":
            self.ev("soc", pct=msg.present_fill_level)
        elif t in ("FRBC.ActuatorStatus", "OMBC.Status"):
            self.ev("status", factor=msg.operation_mode_factor)
        elif t == "InstructionStatusUpdate":
            self.ev("instruction-status", status=msg.status_type.value)
        else:
            self.ev("message", message_type=t)


async def run(port: int, send_instruction: bool, events: list, stop: asyncio.Event | None = None):
    async def handler(ws):
        s = Session(ws, send_instruction, events)
        try:
            async for raw in ws:
                try:
                    await s.handle(raw)
                except Exception as e:  # noqa: BLE001 - test CEM: log and continue
                    s.ev("error", error=str(e)[:300])
        finally:
            s.ev("disconnected")

    async with serve(handler, "127.0.0.1", port):
        log.info("S2 test CEM listening on 127.0.0.1:%s", port)
        await (stop or asyncio.Event()).wait()
