#!/usr/bin/env python3
"""GTK3 UI for the audited DW5934e control-plane-only QMI voice utility."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Sequence

DEFAULT_BACKEND = "/usr/local/libexec/dw5934e-voice-control"
PKEXEC = "/usr/bin/pkexec"
COUNT_RE = re.compile(r"^CALL_COUNT=([0-9]+)$")
CALL_RE = re.compile(r"^CALL id=([1-9][0-9]{0,2}) state=([0-9]+) type=([0-9]+) direction=([0-9]+) mode=([0-9]+)$")
ACCEPT_RE = re.compile(r"^(DIAL|ANSWER|HANGUP)_ACCEPTED call_id=([1-9][0-9]{0,2})$")


@dataclass(frozen=True)
class Call:
    id: int
    state: int
    type: int
    direction: int
    mode: int


@dataclass(frozen=True)
class Result:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def parse_status(text: str) -> tuple[Call, ...]:
    """Strictly parse the published C-backend status records."""
    count = None
    calls = []
    for line in text.splitlines():
        line = line.strip()
        match = COUNT_RE.fullmatch(line)
        if match:
            if count is not None:
                raise ValueError("backend emitted duplicate CALL_COUNT")
            count = int(match.group(1))
            continue
        match = CALL_RE.fullmatch(line)
        if match:
            calls.append(Call(*(int(value) for value in match.groups())))
    if count is None:
        raise ValueError("backend did not emit CALL_COUNT")
    if count != len(calls):
        raise ValueError("CALL_COUNT does not match CALL records")
    if len({call.id for call in calls}) != len(calls):
        raise ValueError("backend emitted duplicate Call IDs")
    return tuple(calls)


def parse_accepted(action: str, text: str) -> int:
    for line in text.splitlines():
        match = ACCEPT_RE.fullmatch(line.strip())
        if match and match.group(1) == action.upper():
            return int(match.group(2))
    raise ValueError("backend did not confirm %s_ACCEPTED" % action.upper())


def validate_number(number: str) -> str:
    # Backend checks remain authoritative and include emergency-number rejection.
    if not re.fullmatch(r"[0-9]{3,32}", number):
        raise ValueError("号码必须是 3–32 位 ASCII 数字（没有 +、空格或分机）。")
    return number


def validate_id(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,2}", value) or int(value) > 255:
        raise ValueError("请选择有效 Call ID（1–255）。")
    return int(value)


def command_argv(backend: str, elevate: bool, command: Sequence[str]) -> list[str]:
    """No shell, and elevation may only execute the installed fixed backend."""
    if not os.path.isabs(backend) or not command:
        raise ValueError("后端路径必须为绝对路径且命令不能为空。")
    if elevate:
        if backend != DEFAULT_BACKEND:
            raise ValueError("pkexec 只允许固定的已部署后端路径。")
        return [PKEXEC, DEFAULT_BACKEND, *command]
    return [backend, *command]


class Runner:
    """Threaded single-operation process runner; callback runs on worker thread."""
    def __init__(self, backend=DEFAULT_BACKEND, elevate=True, popen=subprocess.Popen):
        self.backend, self.elevate, self.popen = backend, elevate, popen
        self.lock, self.busy = threading.Lock(), False

    def start(self, command: Sequence[str], callback: Callable[[Result | None, Exception | None], None]) -> bool:
        argv = tuple(command_argv(self.backend, self.elevate, command))
        with self.lock:
            if self.busy:
                return False
            self.busy = True
        threading.Thread(target=self._work, args=(argv, callback), daemon=True).start()
        return True

    def _work(self, argv, callback):
        result, error = None, None
        try:
            process = self.popen(list(argv), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
            stdout, stderr = process.communicate()
            result = Result(argv, process.returncode, stdout, stderr)
            if result.returncode:
                error = RuntimeError(stderr.strip() or stdout.strip() or "backend exited without diagnostics")
        except Exception as exc:
            error = exc
        finally:
            with self.lock:
                self.busy = False
        callback(result, error)


def load_gtk():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk
    return GLib, Gtk


class Window:
    def __init__(self, Gtk, GLib, runner):
        self.Gtk, self.GLib, self.runner, self.calls = Gtk, GLib, runner, {}
        self.window = Gtk.Window(title="DW5934e 拨号（仅控制）")
        self.window.set_default_size(470, 520); self.window.set_border_width(12)
        self.window.connect("destroy", Gtk.main_quit)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); self.window.add(box)
        for text in ("⚠ 仅呼叫控制：未实现 USB/主机麦克风、扬声器或通话音频。",
                     "拨号、接听、挂断均须明确确认；紧急号由后端再次拒绝。"):
            label = Gtk.Label(label=text); label.set_xalign(0); label.set_line_wrap(True); box.pack_start(label, False, False, 0)
        self.entry = Gtk.Entry(); self.entry.set_placeholder_text("号码（仅数字，3–32 位）")
        self.entry.connect("changed", self._digits); box.pack_start(self.entry, False, False, 0)
        pad = Gtk.Grid(column_spacing=4, row_spacing=4)
        for position, digit in enumerate("123456789*0#"):
            button = Gtk.Button(label=digit); button.connect("clicked", self._key, digit)
            pad.attach(button, position % 3, position // 3, 1, 1)
        box.pack_start(pad, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.dial = Gtk.Button(label="拨号…"); self.dial.connect("clicked", self._dial)
        self.refresh = Gtk.Button(label="手动刷新状态"); self.refresh.connect("clicked", lambda _: self.run(["status"], None))
        row.pack_start(self.dial, True, True, 0); row.pack_start(self.refresh, True, True, 0); box.pack_start(row, False, False, 0)
        self.combo = Gtk.ComboBoxText(); self.combo.append_text("无已知通话；请手动刷新"); self.combo.set_active(0); box.pack_start(self.combo, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.answer = Gtk.Button(label="接听…"); self.answer.connect("clicked", lambda _: self._call_action("answer"))
        self.hangup = Gtk.Button(label="挂断…"); self.hangup.connect("clicked", lambda _: self._call_action("hangup"))
        row.pack_start(self.answer, True, True, 0); row.pack_start(self.hangup, True, True, 0); box.pack_start(row, False, False, 0)
        self.status = Gtk.Label(label="尚未读取 modem 状态。不会自动轮询。"); self.status.set_xalign(0); self.status.set_line_wrap(True)
        box.pack_start(self.status, False, False, 0)
        self.set_busy(False)

    def show(self):
        self.window.show_all()

    def _digits(self, entry):
        old = entry.get_text(); new = "".join(c for c in old if "0" <= c <= "9")[:32]
        if old != new:
            entry.set_text(new); entry.set_position(-1)

    def _key(self, _button, digit):
        if digit in "*#":
            self.message("此控制后端仅接受数字；* 和 # 不会发送。"); return
        self.entry.insert_text(digit, -1); self.entry.set_position(-1)

    def message(self, text):
        self.status.set_text(text)

    def set_busy(self, busy):
        self.dial.set_sensitive(not busy); self.refresh.set_sensitive(not busy)
        valid = bool(self.calls) and not busy
        self.combo.set_sensitive(valid); self.answer.set_sensitive(valid); self.hangup.set_sensitive(valid)
        if busy: self.message("正在等待后端完成并清理 CID/关闭设备；请勿重复操作。")

    def confirm(self, title, text):
        dialog = self.Gtk.MessageDialog(transient_for=self.window, flags=0,
            message_type=self.Gtk.MessageType.WARNING, buttons=self.Gtk.ButtonsType.CANCEL, text=title)
        dialog.format_secondary_text(text); dialog.add_button("确认执行", self.Gtk.ResponseType.OK)
        response = dialog.run() == self.Gtk.ResponseType.OK; dialog.destroy(); return response

    def _dial(self, _button):
        try: number = validate_number(self.entry.get_text())
        except ValueError as exc: self.message(str(exc)); return
        if self.confirm("确认拨号", "将请求 modem 拨打该号码。不会提供主机通话音频。继续？"):
            self.run(["dial", number, "--confirm"], "DIAL")

    def selected(self):
        text = self.combo.get_active_text()
        try: return validate_id(text.split()[1]) if text and text.startswith("ID ") else None
        except (IndexError, ValueError): return None

    def _call_action(self, action):
        call_id = self.selected()
        if call_id is None: self.message("请先手动刷新并选择有效 Call ID。"); return
        if self.confirm("确认%s" % ("接听" if action == "answer" else "挂断"),
                "将%s Call ID %s。继续？" % ("接听" if action == "answer" else "挂断", call_id)):
            self.run([action, str(call_id), "--confirm"], action.upper())

    def run(self, command, action):
        self.set_busy(True)
        if not self.runner.start(command, lambda r, e: self.GLib.idle_add(self.finished, r, e, action)):
            self.message("已有操作在运行；请等待完成。"); self.set_busy(False)

    def finished(self, result, error, action):
        self.set_busy(False)
        if error:
            cleanup = "；清理失败，后端资源状态可能不确定" if result and ("CLEANUP_RELEASE_FAILED:" in result.stderr or "CLEANUP_CLOSE_FAILED:" in result.stderr) else ""
            self.message("操作失败：%s%s" % (error, cleanup)); return False
        try:
            if action:
                self.message("%s 请求已被 modem 接受（Call ID %s）。请手动刷新状态。" % (action, parse_accepted(action, result.stdout)))
            else:
                self.show_status(parse_status(result.stdout))
        except ValueError as exc:
            self.message("后端输出不符合预期：%s" % exc)
        return False

    def show_status(self, calls):
        self.calls = {call.id: call for call in calls}; self.combo.remove_all()
        if not calls:
            self.combo.append_text("无活动通话"); self.combo.set_active(0); self.message("CALL_COUNT=0：当前无活动通话。")
        else:
            for call in calls:
                self.combo.append_text("ID %s — state=%s, direction=%s, type=%s, mode=%s" % (call.id, call.state, call.direction, call.type, call.mode))
            self.combo.set_active(0); self.message("CALL_COUNT=%s。请选择 Call ID 后接听或挂断。" % len(calls))
        self.set_busy(False)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", help="测试/开发的绝对路径；必须配合 --no-pkexec")
    parser.add_argument("--no-pkexec", action="store_true", help="测试/开发：不提权直接运行 --backend")
    parser.add_argument("--self-test", action="store_true", help="不加载 GTK、不运行后端")
    args = parser.parse_args(argv)
    if bool(args.backend) != args.no_pkexec:
        parser.error("--backend 与 --no-pkexec 必须同时使用，不能把任意路径传给 pkexec。")
    if args.backend and not os.path.isabs(args.backend):
        parser.error("--backend 必须是绝对路径。")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.self_test:
        print("SELFTEST_OK"); return 0
    try: GLib, Gtk = load_gtk()
    except Exception as exc:
        print("GTK3/PyGObject unavailable: %s" % exc, file=sys.stderr); return 78
    Window(Gtk, GLib, Runner(args.backend or DEFAULT_BACKEND, not args.no_pkexec)).show()
    Gtk.main(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
