import configparser
import os
from pathlib import Path


APP_DIR_NAME = "interchange"
CONFIG_FILE_NAME = "server.ini"


def default_config_path():
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / APP_DIR_NAME / CONFIG_FILE_NAME
    return Path.home() / ".config" / APP_DIR_NAME / CONFIG_FILE_NAME


def default_values():
    return {
        "destination_dir": str(Path.home() / "InterchangeServerReceived"),
        "db_file": str(Path.home() / ".interchange" / "lan_exchange.db"),
        "spool_dir": str(Path.home() / ".interchange" / "server_spool"),
        "http_port": 8080,
        "socket_port": 8081,
        "show_gui": True,
        "pcap_dir": str(Path.home() / ".interchange" / "pcap"),
        "capture_interface": "auto",
    }


def load_server_config(path=None):
    path = Path(path or default_config_path()).expanduser()
    values = default_values()
    if not path.exists():
        return values

    parser = configparser.ConfigParser()
    parser.read(str(path), encoding="utf-8")
    section = parser["server"] if parser.has_section("server") else {}

    values["destination_dir"] = section.get(
        "destination_dir", values["destination_dir"]
    ).strip()
    values["db_file"] = section.get("db_file", values["db_file"]).strip()
    values["spool_dir"] = section.get("spool_dir", values["spool_dir"]).strip()
    try:
        values["http_port"] = int(section.get("http_port", values["http_port"]))
    except Exception:
        pass
    try:
        values["socket_port"] = int(section.get("socket_port", values["socket_port"]))
    except Exception:
        pass
    raw_gui = str(section.get("show_gui", "true")).strip().lower()
    values["show_gui"] = raw_gui in ("1", "true", "yes", "on")
    values["pcap_dir"] = section.get(
        "pcap_dir", values["pcap_dir"]
    ).strip()
    values["capture_interface"] = section.get(
        "capture_interface", values["capture_interface"]
    ).strip() or "auto"
    return values


def save_server_config(values, path=None):
    path = Path(path or default_config_path()).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    parser = configparser.ConfigParser()
    parser["server"] = {
        "destination_dir": str(values["destination_dir"]).strip(),
        "db_file": str(values["db_file"]).strip(),
        "spool_dir": str(values["spool_dir"]).strip(),
        "http_port": str(int(values["http_port"])),
        "socket_port": str(int(values["socket_port"])),
        "show_gui": "true" if values.get("show_gui", True) else "false",
        "pcap_dir": str(values.get("pcap_dir", "")).strip(),
        "capture_interface": str(
            values.get("capture_interface", "auto")
        ).strip() or "auto",
    }

    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        parser.write(handle)
    temp_path.replace(path)
    return path


def is_server_config_complete(values):
    return bool(
        str(values.get("destination_dir", "")).strip()
        and str(values.get("db_file", "")).strip()
        and str(values.get("spool_dir", "")).strip()
        and str(values.get("pcap_dir", "")).strip()
    )
