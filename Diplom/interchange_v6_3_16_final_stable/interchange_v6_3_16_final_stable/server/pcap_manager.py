import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path


class PcapCaptureError(RuntimeError):
    pass


class PcapManager(object):
    def __init__(self, output_dir, interface="auto", http_port=8080,
                 socket_port=8081):
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.interface = (interface or "auto").strip()
        self.http_port = int(http_port)
        self.socket_port = int(socket_port)
        self._captures = {}
        self._lock = threading.RLock()

    def _find_program(self, name):
        found = shutil.which(name)
        if found:
            return found

        system = platform.system().lower()

        if system == "linux":
            for candidate in (
                "/usr/sbin/" + name,
                "/usr/bin/" + name,
                "/sbin/" + name,
                "/bin/" + name,
            ):
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate

        if system == "windows":
            filename = name
            if not filename.lower().endswith(".exe"):
                filename += ".exe"

            bases = []
            for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
                value = os.environ.get(key)
                if value:
                    bases.append(Path(value))

            candidates = []
            for base in bases:
                candidates.extend([
                    base / "Wireshark" / filename,
                    base / "Programs" / "Wireshark" / filename,
                ])

            for candidate in candidates:
                if candidate.is_file():
                    return str(candidate)

        return None

    def backend(self):
        system = platform.system().lower()



        if system == "linux" and self._find_program("tcpdump"):
            return "tcpdump"

        if self._find_program("dumpcap"):
            return "dumpcap"

        if self._find_program("tcpdump"):
            return "tcpdump"

        return None

    def _dumpcap_interfaces(self):
        dumpcap_bin = self._find_program("dumpcap")
        if not dumpcap_bin:
            return []

        try:
            proc = subprocess.run(
                [dumpcap_bin, "-D"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=5
            )
        except Exception:
            return []

        if proc.returncode != 0:
            return []

        result = []
        for raw_line in proc.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            match = re.match(r"^(\d+)\.\s+(.*)$", line)
            if match:
                result.append((match.group(1), match.group(2).strip()))

        return result

    def _local_ipv4_for_target(self, target_ip):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:


            sock.connect((str(target_ip), 9))
            return sock.getsockname()[0]
        except Exception:
            return None
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _windows_interface_alias(self, local_ip):
        if not local_ip:
            return None

        powershell = (
            shutil.which("powershell")
            or shutil.which("powershell.exe")
            or shutil.which("pwsh")
            or shutil.which("pwsh.exe")
        )
        if not powershell:
            return None


        command = (
            "$x=Get-NetIPAddress -AddressFamily IPv4 "
            "| Where-Object {$_.IPAddress -eq '%s'} "
            "| Select-Object -First 1 -ExpandProperty InterfaceAlias; "
            "if ($x) { Write-Output $x }"
        ) % local_ip

        try:
            proc = subprocess.run(
                [powershell, "-NoProfile", "-Command", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=5
            )
        except Exception:
            return None

        if proc.returncode != 0:
            return None

        value = proc.stdout.strip()
        return value or None

    def _resolve_windows_dumpcap_interface(self, target_ip):
        interfaces = self._dumpcap_interfaces()
        if not interfaces:
            raise PcapCaptureError(
                "dumpcap was found, but no capture interfaces were returned. "
                "Install/repair Npcap or run server/run_capture_check.bat."
            )

        local_ip = self._local_ipv4_for_target(target_ip)
        alias = self._windows_interface_alias(local_ip)

        if alias:
            alias_lower = alias.lower()
            for index, description in interfaces:
                if alias_lower in description.lower():
                    return index


        excluded = (
            "loopback",
            "bluetooth",
            "etwdump",
            "sshdump",
            "randpkt",
            "udpdump",
            "wifidump",
        )
        candidates = []
        for index, description in interfaces:
            lower = description.lower()
            if not any(token in lower for token in excluded):
                candidates.append((index, description))

        if len(candidates) == 1:
            return candidates[0][0]

        lines = [
            "%s: %s" % (index, description)
            for index, description in interfaces
        ]
        raise PcapCaptureError(
            "Cannot choose the Windows capture interface automatically. "
            "Open Server settings and put the dumpcap interface number in "
            "Capture interface. Available interfaces:\n"
            + "\n".join(lines)
        )

    def resolve_interface(self, target_ip):
        configured = (self.interface or "auto").strip()
        if configured and configured.lower() != "auto":
            return configured

        system = platform.system().lower()
        if system == "linux":

            return "any"

        if system == "windows":
            return self._resolve_windows_dumpcap_interface(target_ip)

        if system == "darwin":

            try:
                proc = subprocess.run(
                    ["route", "-n", "get", str(target_ip)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    timeout=3
                )
                if proc.returncode == 0:
                    for line in proc.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("interface:"):
                            value = line.split(":", 1)[1].strip()
                            if value:
                                return value
            except Exception:
                pass

        raise PcapCaptureError(
            "Cannot determine capture interface automatically. "
            "Open Server settings and set Capture interface explicitly."
        )

    def _filter(self, target_ip):
        return (
            "host %s and (tcp port %d or tcp port %d)"
            % (target_ip, self.http_port, self.socket_port)
        )

    def start(self, run_id, target_user_id, target_ip, label):
        backend = self.backend()
        if not backend:
            system = platform.system().lower()
            if system == "windows":
                raise PcapCaptureError(
                    "Packet capture backend was not found. "
                    "Install Wireshark with Npcap (dumpcap.exe is required), "
                    "then restart Interchange Server."
                )
            raise PcapCaptureError(
                "Neither dumpcap nor tcpdump is installed on the server."
            )

        interface = self.resolve_interface(target_ip)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_user = re_safe(target_user_id)
        safe_label = re_safe(label)
        name = "run_%06d_%s_%s_%s.pcap" % (
            int(run_id), safe_user, safe_label, stamp
        )
        pcap_path = self.output_dir / name
        log_path = pcap_path.with_suffix(".capture.log")
        capture_filter = self._filter(target_ip)

        output_handle = None

        if backend == "dumpcap":
            dumpcap_bin = self._find_program("dumpcap")
            cmd = [
                dumpcap_bin,
                "-q",
                "-P",
                "-i", interface,
                "-f", capture_filter,
                "-w", str(pcap_path)
            ]
            stdout_target = subprocess.DEVNULL

        else:






            pcap_path.parent.mkdir(parents=True, exist_ok=True)
            output_handle = pcap_path.open("wb")

            tcpdump_bin = self._find_program("tcpdump")
            cmd = [
                tcpdump_bin,
                "-n",
                "-U",
                "-s", "0",
                "-i", interface,
                "-w", "-",
                capture_filter
            ]





            stdout_target = output_handle

        log_handle = log_path.open("wb")
        creationflags = 0
        if (
            os.name == "nt"
            and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
        ):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=stdout_target,
                stderr=log_handle,
                start_new_session=(os.name == "posix"),
                creationflags=creationflags
            )
        except Exception:
            log_handle.close()
            if output_handle is not None:
                output_handle.close()
            raise


        time.sleep(0.25)
        if proc.poll() is not None:
            log_handle.close()
            if output_handle is not None:
                output_handle.close()
            try:
                details = log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).strip()
            except Exception:
                details = ""
            if not details:
                details = "capture process exited immediately"

            lower_details = details.lower()
            if (
                backend == "tcpdump"
                and (
                    "permission denied" in lower_details
                    or "operation not permitted" in lower_details
                    or "you don't have permission" in lower_details
                )
            ):
                details = (
                    details
                    + "\n\nPacket capture permission is not configured. "
                    + "Close the server and run ./run_server.sh again. "
                    + "On Debian/Astra, libcap2-bin must be installed."
                )

            raise PcapCaptureError(details)

        with self._lock:
            self._captures[int(run_id)] = {
                "proc": proc,
                "log_handle": log_handle,
                "output_handle": output_handle,
                "pcap_path": str(pcap_path),
                "log_path": str(log_path),
                "backend": backend,
                "interface": interface,
                "filter": capture_filter,
            }

        return {
            "pcap_path": str(pcap_path),
            "backend": backend,
            "interface": interface,
            "filter": capture_filter,
        }

    def stop(self, run_id):
        with self._lock:
            info = self._captures.pop(int(run_id), None)

        if not info:
            return None

        proc = info["proc"]
        try:
            if proc.poll() is None:
                if os.name == "posix":
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
                    except Exception:
                        proc.send_signal(signal.SIGINT)
                elif (
                    os.name == "nt"
                    and info.get("backend") == "dumpcap"
                    and hasattr(signal, "CTRL_BREAK_EVENT")
                ):
                    try:
                        proc.send_signal(signal.CTRL_BREAK_EVENT)
                    except Exception:
                        proc.terminate()
                else:
                    proc.terminate()

                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                        except Exception:
                            proc.terminate()
                    else:
                        proc.terminate()

                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        if os.name == "posix":
                            try:
                                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                            except Exception:
                                proc.kill()
                        else:
                            proc.kill()
        finally:
            try:
                info["log_handle"].close()
            except Exception:
                pass
            try:
                if info.get("output_handle") is not None:
                    info["output_handle"].flush()
                    info["output_handle"].close()
            except Exception:
                pass

        return info

    def stop_all(self):
        with self._lock:
            ids = list(self._captures.keys())
        for run_id in ids:
            self.stop(run_id)

    def write_metadata(self, pcap_path, payload):
        if not pcap_path:
            return None
        path = Path(pcap_path)
        metadata_path = path.with_suffix(".json")
        temp_path = metadata_path.with_name(metadata_path.name + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        temp_path.replace(metadata_path)
        return str(metadata_path)


def re_safe(value):
    value = str(value or "")
    out = []
    for ch in value:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "unknown"
