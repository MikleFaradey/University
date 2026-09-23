import platform
from pathlib import Path

from pcap_manager import PcapManager


def main():
    manager = PcapManager(
        Path.home() / ".interchange" / "pcap",
        interface="auto",
        http_port=8080,
        socket_port=8081
    )

    print("Operating system:", platform.system())
    print("Capture backend:", manager.backend() or "NOT FOUND")

    dumpcap = manager._find_program("dumpcap")
    tcpdump = manager._find_program("tcpdump")

    print("dumpcap:", dumpcap or "not found")
    print("tcpdump:", tcpdump or "not found")

    if dumpcap:
        interfaces = manager._dumpcap_interfaces()
        print()
        print("dumpcap interfaces:")
        if not interfaces:
            print("  none")
        else:
            for index, description in interfaces:
                print("  %s: %s" % (index, description))

    print()
    print(
        "If automatic interface selection fails, put the interface number "
        "shown above into Server settings -> Capture interface."
    )


if __name__ == "__main__":
    main()
