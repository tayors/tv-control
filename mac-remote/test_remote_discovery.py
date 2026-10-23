import ipaddress
import time
import unittest
from unittest.mock import Mock, patch

import remote_discovery as discovery


class DiscoveryTests(unittest.TestCase):
    def candidates(self, services='', arp='', serial='tv-serial', mac='3c:c5:dd:1f:c6:a6'):
        tv = Mock(endpoint='192.168.1.44:5555')
        tv.run.return_value = services
        with patch.object(discovery, 'local_network', return_value=('en0', ipaddress.IPv4Network('192.168.1.0/24'))), patch.object(discovery, 'local_command', return_value=arp):
            return discovery.discovery_candidates(tv, mac, serial, time.monotonic() + 10)

    def test_mdns_recovers_changed_ip_and_connection_port(self):
        self.assertEqual(self.candidates('adb-tv-serial-random _adb-tls-connect._tcp 192.168.1.70:38421'), ['192.168.1.70:38421'])

    def test_pairing_ports_and_other_devices_are_not_candidates(self):
        services = '\n'.join([
            'adb-tv-serial _adb-tls-pairing._tcp 192.168.1.70:43210',
            'adb-another-tv _adb._tcp 192.168.1.71:5555',
            'adb-tv-serial-extra-device _http._tcp 192.168.1.72:5555',
        ])
        self.assertEqual(self.candidates(services), [])

    def test_matching_advertisement_outside_local_network_is_ignored(self):
        self.assertEqual(self.candidates('adb-tv-serial _adb._tcp 10.0.0.4:5555'), [])

    def test_known_mac_can_bootstrap_discovery_without_serial(self):
        arp = '? (192.168.1.70) at 3c:c5:dd:1f:c6:a6 on en0 ifscope [ethernet]'
        self.assertEqual(self.candidates(arp=arp, serial=''), ['192.168.1.70:5555'])

    def test_without_saved_identity_does_not_choose_only_advertised_device(self):
        self.assertEqual(self.candidates('adb-unknown _adb._tcp 192.168.1.70:5555', serial='', mac=''), [])

    def test_mac_from_another_interface_is_ignored(self):
        arp = '? (192.168.1.70) at 3c:c5:dd:1f:c6:a6 on en1 ifscope [ethernet]'
        self.assertEqual(self.candidates(arp=arp, serial=''), [])

    def test_mac_zero_padding_is_normalised(self):
        arp = '? (192.168.1.70) at a:b:c:d:e:f on en0 ifscope [ethernet]'
        self.assertEqual(self.candidates(arp=arp, serial='', mac='0a:0b:0c:0d:0e:0f'), ['192.168.1.70:5555'])

    def test_duplicate_and_saved_endpoints_are_removed(self):
        services = '\n'.join([
            'adb-tv-serial _adb._tcp 192.168.1.44:5555',
            'adb-tv-serial _adb._tcp 192.168.1.70:5555',
            'adb-tv-serial-random _adb._tcp 192.168.1.70:5555',
        ])
        arp = '? (192.168.1.70) at 3c:c5:dd:1f:c6:a6 on en0 ifscope [ethernet]'
        self.assertEqual(self.candidates(services, arp), ['192.168.1.70:5555'])

    def test_invalid_addresses_ports_and_broadcast_are_ignored(self):
        services = '\n'.join(f'adb-tv-serial _adb._tcp {endpoint}' for endpoint in ['192.168.1.70:0', '192.168.1.70:65536', 'host:5555', '192.168.1.255:5555'])
        self.assertEqual(self.candidates(services), [])

    def test_discovery_is_bounded(self):
        services = '\n'.join(f'adb-tv-serial _adb._tcp 192.168.1.{n}:5555' for n in range(60, 80))
        self.assertEqual(len(self.candidates(services)), 8)

    def test_no_physical_lan_stops_discovery(self):
        tv = Mock()
        with patch.object(discovery, 'local_network', return_value=None):
            self.assertEqual(discovery.discovery_candidates(tv, '', 'tv-serial', time.monotonic()+10), [])
            tv.run.assert_not_called()

    def test_macos_default_interface_and_hex_netmask_are_read(self):
        with patch.object(discovery, 'local_command', side_effect=['interface: en0\n', 'inet 192.168.1.172 netmask 0xffffff00 broadcast 192.168.1.255']):
            self.assertEqual(discovery.local_network(time.monotonic()+10), ('en0', ipaddress.IPv4Network('192.168.1.0/24')))

    def test_vpn_default_route_is_not_scanned(self):
        with patch.object(discovery, 'local_command', return_value='interface: utun3\n'):
            self.assertIsNone(discovery.local_network(time.monotonic()+10))


if __name__ == '__main__':
    unittest.main()
