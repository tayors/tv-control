"""Find the saved TV via ADB advertisements or its known LAN MAC, never by port alone."""
import ipaddress
import re
import subprocess
import time


def normalise_mac(value):
    parts = re.split('[:-]', value.lower())
    if len(parts) != 6 or any(not re.fullmatch('[0-9a-f]{1,2}', part) for part in parts):
        return None
    return ':'.join(part.zfill(2) for part in parts)


def local_command(args, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return ''
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=min(1.5, remaining))
        return result.stdout if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def local_network(deadline):
    route = local_command(['/sbin/route', '-n', 'get', 'default'], deadline)
    match = re.search(r'^\s*interface:\s*(\S+)', route, re.MULTILINE)
    if not match or not re.fullmatch(r'en\d+', match[1]):
        return None
    interface = match[1]
    details = local_command(['/sbin/ifconfig', interface], deadline)
    match = re.search(r'\binet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-f]+)', details)
    if not match:
        return None
    try:
        mask = str(ipaddress.IPv4Address(int(match[2], 16)))
        network = ipaddress.IPv4Network(f'{match[1]}/{mask}', strict=False)
        if not ipaddress.IPv4Address(match[1]).is_private:
            return None
        return interface, network
    except ValueError:
        return None


def discovery_candidates(tv, mac, serial, deadline):
    """Bound discovery to the current physical LAN and at most eight matching endpoints.

    mDNS instance names only select candidates; the caller checks the actual ADB
    serial before using them. Without a stored serial, require the known MAC.
    Pairing endpoints are intentionally excluded.
    """
    local = local_network(deadline)
    if local is None:
        return []
    interface, network = local
    target_mac = normalise_mac(mac)
    neighbours = {}
    arp = local_command(['/usr/sbin/arp', '-an'], deadline)
    for line in arp.splitlines():
        match = re.search(r'\(([^)]+)\) at (\S+) on (\S+)', line)
        if match and match[3] == interface:
            neighbours[match[1]] = normalise_mac(match[2])
    try:
        services = tv.run('mdns', 'services')
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        services = ''
    candidates = []

    def add(endpoint, instance=''):
        try:
            host, port = endpoint.rsplit(':', 1)
            address = ipaddress.IPv4Address(host)
            if address not in network or address in (network.network_address, network.broadcast_address) or not 1 <= int(port) <= 65535:
                return
        except (ValueError, TypeError):
            return
        mac_matches = target_mac is not None and neighbours.get(host) == target_mac
        prefix = 'adb-' + serial if serial else ''
        serial_advertised = bool(prefix and (instance == prefix or instance.startswith(prefix + '-')))
        if (mac_matches or serial_advertised) and endpoint not in candidates and endpoint != tv.endpoint:
            candidates.append(endpoint)

    for line in services.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1].rstrip('.') in ('_adb._tcp', '_adb-tls-connect._tcp'):
            add(fields[2], fields[0])
    # Legacy ADB TVs may not advertise. Use only the known MAC and saved port;
    # an arbitrary open ADB port is never enough to select a TV.
    saved_port = tv.endpoint.rsplit(':', 1)[-1]
    if target_mac:
        for host, found_mac in neighbours.items():
            if found_mac == target_mac:
                add(f'{host}:{saved_port}')
    return candidates[:8]
