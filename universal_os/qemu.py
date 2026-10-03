"""QEMU headless backend: QMP control, guest-agent exec, VM lifecycle.

Everything runs in a throwaway VM — RULES.md forbids analyzing untrusted OS media
on the host. QEMU is the only external dependency. Layout per VM under
$UOS_HOME/vms/<name>/: disk.qcow2, qmp.sock, ga.sock, serial.log, shots/, boot.log.

If QEMU or the in-guest agent is missing, tools say so and print exact install steps
instead of failing mysteriously.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

from . import config
from .util import run, which

QEMU = "qemu-system-x86_64"
QEMU_IMG = "qemu-img"


class VmError(RuntimeError):
    pass


def qemu_available() -> str | None:
    return which(QEMU)


def qemu_img_available() -> str | None:
    return which(QEMU_IMG)


def qemu_install_hint() -> str:
    return (
        "QEMU is required. Install it and retry:\n"
        "  Debian/Ubuntu: sudo apt-get install -y qemu-system-x86 qemu-utils\n"
        "  Fedora:        sudo dnf install -y qemu-kvm qemu-img\n"
        "  macOS:         brew install qemu\n"
        "  Windows:       winget install SoftwareFreedomConservancy.QEMU"
    )


class QmpClient:
    """Tiny QMP client over a unix socket. Skips async events while waiting for replies."""

    def __init__(self, sock_path: str | Path, timeout: float = 120.0):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(str(sock_path))
        self._dec = json.JSONDecoder()
        self._buf = b""
        self.greeting = self._read_msg()  # {"QMP": {...}}

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_msg(self) -> dict:
        while True:
            while b"\n" not in self._buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise VmError("QMP socket closed")
                self._buf += chunk
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            obj, _ = self._dec.raw_decode(line.decode("utf-8", "replace"))
            if "event" in obj:
                continue  # skip events
            return obj

    def cmd(self, execute: str, arguments: dict | None = None) -> dict:
        m = {"execute": execute}
        if arguments:
            m["arguments"] = arguments
        self.sock.sendall(json.dumps(m).encode() + b"\n")
        reply = self._read_msg()
        if "error" in reply:
            raise VmError(f"QMP {execute} failed: {reply['error'].get('desc', reply['error'])}")
        return reply.get("return", {})

    def hmp(self, command_line: str) -> dict:
        return self.cmd("human-monitor-command", {"command-line": command_line})


class GuestAgentClient:
    """qemu-ga protocol over a virtio-serial unix socket (guest agent must be installed)."""

    def __init__(self, sock_path: str | Path, timeout: float = 60.0):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(str(sock_path))
        self._dec = json.JSONDecoder()
        self._buf = b""

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_msg(self) -> dict:
        while True:
            while b"\n" not in self._buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise VmError("guest-agent socket closed")
                self._buf += chunk
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            obj, _ = self._dec.raw_decode(line.decode("utf-8", "replace"))
            if "event" in obj:
                continue
            return obj

    def cmd(self, execute: str, arguments: dict | None = None, timeout: float = 60.0) -> dict:
        m = {"execute": execute}
        if arguments:
            m["arguments"] = arguments
        self.sock.settimeout(timeout)
        self.sock.sendall(json.dumps(m).encode() + b"\n")
        reply = self._read_msg()
        if "error" in reply:
            raise VmError(f"qga {execute} failed: {reply['error'].get('desc', reply['error'])}")
        return reply.get("return") or {}

    def ping(self) -> bool:
        try:
            self.cmd("guest-ping", timeout=10)
            return True
        except Exception:
            return False

    # ---- file transfer -------------------------------------------------
    def put_file(self, local_path: str | Path, guest_path: str, chunk: int = 256 * 1024) -> dict:
        import base64
        data = Path(local_path).read_bytes()
        h = self.cmd("guest-file-open", {"filepath": guest_path, "mode": "wb"}, timeout=30)
        handle = h["handle"] if isinstance(h, dict) else int(h)
        try:
            for off in range(0, len(data), chunk):
                self.cmd("guest-file-write", {
                    "handle": handle,
                    "buf-b64": base64.b64encode(data[off:off + chunk]).decode(),
                }, timeout=60)
        finally:
            try:
                self.cmd("guest-file-close", {"handle": handle}, timeout=30)
            except VmError:
                pass
        return {"guest_path": guest_path, "bytes": len(data)}

    def get_file(self, guest_path: str, local_path: str | Path, max_bytes: int = 64 * 1024 * 1024) -> dict:
        import base64
        h = self.cmd("guest-file-open", {"filepath": guest_path, "mode": "rb"}, timeout=30)
        handle = h["handle"] if isinstance(h, dict) else int(h)
        out = bytearray()
        try:
            while len(out) < max_bytes:
                r = self.cmd("guest-file-read", {"handle": handle, "count": 262144}, timeout=60)
                blob = base64.b64decode(r.get("buf-b64", ""))
                out += blob
                if r.get("eof") or not blob:
                    break
        finally:
            try:
                self.cmd("guest-file-close", {"handle": handle}, timeout=30)
            except VmError:
                pass
        Path(local_path).write_bytes(bytes(out))
        return {"local_path": str(local_path), "bytes": len(out)}

    # ---- exec ----------------------------------------------------------
    def exec_wait(self, path: str, args: list[str] | None = None, timeout: int = 120,
                  capture: bool = True) -> dict:
        """Run a command in the guest and wait for it. Returns exitcode/stdout/stderr."""
        started = time.time()
        r = self.cmd("guest-exec", {
            "path": path, "arg": args or [], "capture-output": capture,
        }, timeout=30)
        pid = r["pid"]
        import base64
        while time.time() - started < timeout:
            st = self.cmd("guest-exec-status", {"pid": pid}, timeout=30)
            if st.get("exited"):
                return {
                    "exitcode": st.get("exitcode"),
                    "stdout": base64.b64decode(st.get("out-b64", "")).decode("utf-8", "replace"),
                    "stderr": base64.b64decode(st.get("err-b64", "")).decode("utf-8", "replace"),
                }
            time.sleep(1.0)
        raise VmError(f"guest command timed out after {timeout}s: {path} {' '.join(args or [])}")


# --------------------------------------------------------------------------
# VM lifecycle
# --------------------------------------------------------------------------

def _has_kvm() -> bool:
    return os.path.exists("/dev/kvm") and os.access("/dev/kvm", os.R_OK | os.W_OK)


def vm_create(name: str, iso_path: str, disk_gb: int = 30, ram_mb: int = 2048,
              cpus: int = 2, workspace: str | None = None, network: bool = False,
              force: bool = False) -> dict:
    qemu_img = qemu_img_available()
    if not qemu_img:
        raise VmError(qemu_install_hint())
    iso = Path(iso_path).expanduser().resolve()
    if not iso.exists():
        raise VmError(f"ISO not found: {iso}")
    d = config.vm_dir(name)
    disk = d / "disk.qcow2"
    if disk.exists() and not force:
        raise VmError(f"disk already exists for VM '{name}' ({disk}); pass force=true to overwrite")
    if disk.exists():
        disk.unlink()
    rc, out, err = run([qemu_img, "create", "-f", "qcow2", str(disk), f"{disk_gb}G"], timeout=120)
    if rc != 0:
        raise VmError(f"qemu-img failed: {err or out}")
    meta = config.vm_set(name, {
        "name": name, "dir": str(d), "disk": str(disk), "iso": str(iso),
        "ram_mb": ram_mb, "cpus": cpus, "network": bool(network),
        "workspace": workspace, "snapshots": [], "pid": None,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return {"vm": name, "dir": str(d), "disk": str(disk), "ram_mb": ram_mb,
            "cpus": cpus, "network": network, "iso": str(iso)}


def _qemu_cmdline(meta: dict, boot: str, extra_iso: str | None = None) -> list[str]:
    d = Path(meta["dir"])
    qemu = qemu_available() or QEMU
    kvm = _has_kvm()
    args = [
        qemu,
        "-machine", "pc,accel=" + ("kvm" if kvm else "tcg"),
        "-m", str(meta.get("ram_mb", 2048)),
        "-smp", str(meta.get("cpus", 2)),
        "-cpu", "host" if kvm else "qemu64",
        "-rtc", "base=localtime",
        "-drive", f"file={meta['disk']},if=virtio,format=qcow2,cache=writeback,node-name=main",
        "-device", "ide-cd,id=cd0,drive=cd0drv",
        "-drive", f"file={extra_iso or meta['iso']},if=none,id=cd0drv,media=cdrom,format=raw,read-only=on",
        "-boot", boot,
        "-display", "none",
        "-vga", "std",
        "-serial", f"file:{d / 'serial.log'}",
        "-qmp", f"unix:{d / 'qmp.sock'},server=on,wait=off",
        "-chardev", f"socket,path={d / 'ga.sock'},server=on,wait=off,id=ga0",
        "-device", "virtserialport,chardev=ga0,name=org.qemu.guest_agent.0",
        "-pidfile", str(d / "qemu.pid"),
    ]
    if os.name != "nt":
        args.append("-daemonize")  # -daemonize is unsupported on Windows hosts
    if meta.get("network"):
        args += ["-netdev", "user,id=n0", "-device", "e1000,netdev=n0"]
    else:
        args += ["-nic", "none"]
    return args


def vm_boot(name: str, wait_seconds: int = 45, boot: str = "d", extra_iso: str | None = None) -> dict:
    qemu = qemu_available()
    if not qemu:
        raise VmError(qemu_install_hint())
    meta = config.vm_get(name)
    if not meta:
        raise VmError(f"unknown VM '{name}'; create it first with vm_create")
    if vm_running(name):
        raise VmError(f"VM '{name}' is already running")
    d = Path(meta["dir"])
    (d / "shots").mkdir(exist_ok=True)
    for f in ("qmp.sock", "ga.sock", "qemu.pid"):
        p = d / f
        if p.exists():
            p.unlink()
    (d / "boot.log").write_text(f"# boot {time.strftime('%F %T')}\n" +
                                " ".join(_qemu_cmdline(meta, boot, extra_iso)) + "\n")
    # -daemonize detaches on POSIX; on Windows we detach the process instead
    errlog = open(d / "boot.err.log", "ab", buffering=0)
    popen_kw = {}
    if os.name == "nt":
        popen_kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | \
                                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        _qemu_cmdline(meta, boot, extra_iso),
        stdout=subprocess.DEVNULL, stderr=errlog,
        start_new_session=(os.name != "nt"), **popen_kw,
    )
    time.sleep(2.0)
    if proc.poll() is not None:
        errlog.flush()
        err = Path(d / "boot.err.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        raise VmError(f"qemu exited immediately ({proc.returncode}): {err.strip()}")
    # wait for QMP
    deadline = time.time() + 30
    qmp: QmpClient | None = None
    while time.time() < deadline:
        try:
            qmp = QmpClient(d / "qmp.sock", timeout=10)
            break
        except (OSError, VmError):
            time.sleep(0.5)
    if qmp is None:
        raise VmError(f"qemu started but QMP never appeared for VM '{name}'")
    try:
        status = qmp.cmd("query-status")
    finally:
        qmp.close()
    meta = config.vm_set(name, {**meta, "pid": _read_pid(d), "boot": boot,
                                "last_boot": time.strftime("%Y-%m-%d %H:%M:%S")})
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    return {"vm": name, "qemu_status": status.get("status"), "accel": "kvm" if _has_kvm() else "tcg (slow)",
            "waited_s": wait_seconds, "note": "screenshot with vm_screenshot to see the display"}


def _read_pid(d: Path) -> int | None:
    try:
        return int((d / "qemu.pid").read_text().strip())
    except Exception:
        return None


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def vm_running(name: str) -> bool:
    meta = config.vm_get(name) or {}
    d = Path(meta.get("dir", ""))
    if not (d / "qmp.sock").exists():
        return False
    return _pid_alive(meta.get("pid") or _read_pid(d))


def vm_qmp(name: str) -> QmpClient:
    meta = config.vm_get(name)
    if not meta:
        raise VmError(f"unknown VM '{name}'")
    d = Path(meta["dir"])
    if not (d / "qmp.sock").exists():
        raise VmError(f"VM '{name}' is not running (no QMP socket)")
    return QmpClient(d / "qmp.sock")


def vm_status(name: str) -> dict:
    meta = config.vm_get(name)
    if not meta:
        return {"vm": name, "exists": False}
    info = {k: meta.get(k) for k in ("name", "iso", "disk", "ram_mb", "cpus",
                                     "network", "workspace", "snapshots", "created", "last_boot")}
    info["exists"] = True
    info["running"] = vm_running(name)
    if info["running"]:
        try:
            qmp = vm_qmp(name)
            try:
                st = qmp.cmd("query-status")
                info["qemu_status"] = st.get("status")
            finally:
                qmp.close()
        except Exception as e:
            info["qemu_status"] = f"error: {e}"
    return info


def vm_list() -> list[dict]:
    return [vm_status(n) for n in config.vm_all()]


def vm_screenshot(name: str, out: str | None = None) -> dict:
    if not vm_running(name):
        raise VmError(f"VM '{name}' is not running")
    from .ppm import ppm_file_to_png
    d = Path(config.vm_get(name)["dir"])
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ppm = d / "shots" / f"{stamp}.ppm"
    png = Path(out) if out else d / "shots" / f"{stamp}.png"
    qmp = vm_qmp(name)
    try:
        qmp.cmd("screendump", {"filename": str(ppm)})
    finally:
        qmp.close()
    deadline = time.time() + 10
    while not ppm.exists() and time.time() < deadline:
        time.sleep(0.2)
    if not ppm.exists():
        raise VmError("screendump never produced a file")
    w, h = ppm_file_to_png(ppm, png)
    return {"png": str(png.resolve()), "width": w, "height": h,
            "hint": "open the PNG or send it to the model's vision if it supports images"}


def vm_snapshot(name: str, tag: str) -> dict:
    if not vm_running(name):
        raise VmError(f"VM '{name}' must be running to snapshot (internal snapshots)")
    qmp = vm_qmp(name)
    try:
        qmp.hmp(f"savevm {tag}")
    finally:
        qmp.close()
    meta = config.vm_get(name)
    snaps = meta.setdefault("snapshots", [])
    if tag not in snaps:
        snaps.append(tag)
        config.vm_set(name, meta)
    return {"vm": name, "snapshot": tag, "all": snaps}


def vm_restore(name: str, tag: str) -> dict:
    if not vm_running(name):
        raise VmError(f"VM '{name}' must be running to loadvm")
    qmp = vm_qmp(name)
    try:
        qmp.hmp(f"loadvm {tag}")
    finally:
        qmp.close()
    return {"vm": name, "restored": tag}


def vm_snapshots(name: str) -> list[str]:
    meta = config.vm_get(name) or {}
    return meta.get("snapshots", [])


def vm_pause(name: str, pause: bool = True) -> dict:
    qmp = vm_qmp(name)
    try:
        qmp.cmd("stop" if pause else "cont")
    finally:
        qmp.close()
    return {"vm": name, "state": "paused" if pause else "running"}


def vm_mount_iso(name: str, iso_path: str) -> dict:
    if not vm_running(name):
        raise VmError(f"VM '{name}' is not running")
    iso = Path(iso_path).expanduser().resolve()
    if not iso.exists():
        raise VmError(f"ISO not found: {iso}")
    qmp = vm_qmp(name)
    try:
        qmp.cmd("blockdev-change-medium",
                {"device": "cd0", "filename": str(iso), "format": "raw"})
    finally:
        qmp.close()
    return {"vm": name, "mounted": str(iso)}


# QEMU sendkey names for the common keys an agent needs to drive an installer
# (full set: `qemu-system-x86_64 -sendkey help` in a shell, or QEMU docs).
SENDKEY_HELP = (
    "Combo string with QEMU key names joined by '-': 'ret', 'spc', 'esc', 'tab', 'bksp', "
    "'f1'..'f12', 'up'/'down'/'left'/'right', 'kp_enter', 'a'..'z', '0'..'9', "
    "modifiers 'shift'/'ctrl'/'alt' (e.g. 'ctrl-alt-delete', 'shift-f8'). "
    "One combo per call; call repeatedly with pauses to walk an installer."
)


def vm_sendkey(name: str, keys: str, hold_ms: int = 100) -> dict:
    """Send a key combo to the VM's display via QMP human-monitor-command.

    This is how the agent drives text-mode installers (press Enter, F8, F6 ...)
    before the guest agent exists — the pre-agent phase of vm_boot that
    WORKFLOW.md Phase 2 describes. Uses QEMU's 'sendkey' HMP command."""
    if not vm_running(name):
        raise VmError(f"VM '{name}' is not running")
    combo = keys.strip().lower().replace(" ", "-")
    if not combo or combo == "-":
        raise VmError(f"empty key combo; {SENDKEY_HELP}")
    for part in combo.split("-"):
        if not part:
            raise VmError(f"bad key combo '{keys}'; {SENDKEY_HELP}")
    qmp = vm_qmp(name)
    try:
        qmp.hmp(f"sendkey {combo}")
    finally:
        qmp.close()
    time.sleep(max(0.0, hold_ms / 1000.0))
    return {"vm": name, "sent": combo,
            "hint": "vm_screenshot to see the effect; one combo per call"}


def vm_exec(name: str, path: str, args: list[str] | None = None, timeout: int = 120) -> dict:
    """Run a command inside the guest. Requires qemu-ga installed in the guest."""
    meta = config.vm_get(name)
    if not meta:
        raise VmError(f"unknown VM '{name}'")
    if not vm_running(name):
        raise VmError(f"VM '{name}' is not running")
    ga_sock = Path(meta["dir"]) / "ga.sock"
    if not ga_sock.exists():
        raise VmError(
            "guest-agent socket missing — the VM must be launched by universal-os\n"
            "(it always exposes org.qemu.guest_agent.0 on virtio-serial)"
        )
    ga = GuestAgentClient(ga_sock)
    try:
        if not ga.ping():
            raise VmError(
                "qemu-ga is not responding inside the guest.\n"
                "Install the QEMU guest agent inside the guest OS and retry:\n"
                "  Windows: install qemu-wa64 from https://pve.proxmox.com/wiki/Qemu-guest-agent\n"
                "           (qemu-ga-x86_64.msi), or point vm_mount_iso at virtio-win and install it\n"
                "  Linux:   sudo apt-get install -y qemu-guest-agent && sudo systemctl enable --now qemu-guest-agent"
            )
        return ga.exec_wait(path, args, timeout=timeout)
    finally:
        ga.close()


def vm_put_file(name: str, local_path: str, guest_path: str) -> dict:
    meta = config.vm_get(name)
    if not meta or not vm_running(name):
        raise VmError(f"VM '{name}' is not running")
    ga_sock = Path(meta["dir"]) / "ga.sock"
    ga = GuestAgentClient(ga_sock)
    try:
        if not ga.ping():
            raise VmError("qemu-ga not responding in guest; install the guest agent first")
        return ga.put_file(local_path, guest_path)
    finally:
        ga.close()


def vm_get_file(name: str, guest_path: str, local_path: str) -> dict:
    meta = config.vm_get(name)
    if not meta or not vm_running(name):
        raise VmError(f"VM '{name}' is not running")
    ga_sock = Path(meta["dir"]) / "ga.sock"
    ga = GuestAgentClient(ga_sock)
    try:
        if not ga.ping():
            raise VmError("qemu-ga not responding in guest; install the guest agent first")
        return ga.get_file(guest_path, local_path)
    finally:
        ga.close()


def vm_shutdown(name: str, force: bool = False, timeout: int = 60) -> dict:
    meta = config.vm_get(name)
    if not meta or not vm_running(name):
        return {"vm": name, "running": False}
    qmp = vm_qmp(name)
    try:
        if not force:
            qmp.cmd("system_powerdown")
            qmp.close()
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not vm_running(name):
                    return {"vm": name, "shutdown": "acpi"}
                time.sleep(1.0)
            qmp = vm_qmp(name)
        qmp.cmd("quit")
    finally:
        try:
            qmp.close()
        except Exception:
            pass
    time.sleep(1.0)
    if vm_running(name) and meta.get("pid"):
        try:
            os.kill(meta["pid"], signal.SIGKILL)
        except OSError:
            pass
    return {"vm": name, "shutdown": "forced" if force else "acpi-timeout-fallback"}


def vm_log(name: str, tail: int = 80) -> dict:
    meta = config.vm_get(name)
    if not meta:
        raise VmError(f"unknown VM '{name}'")
    d = Path(meta["dir"])
    out = {}
    for f, key in (("serial.log", "serial_tail"), ("boot.log", "boot_cmdline")):
        p = d / f
        if p.exists():
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            out[key] = "\n".join(lines[-tail:])
    return out


def vm_destroy(name: str) -> dict:
    meta = config.vm_get(name)
    if meta and vm_running(name):
        vm_shutdown(name, force=True)
    config.vm_del(name)
    return {"vm": name, "destroyed": True}
