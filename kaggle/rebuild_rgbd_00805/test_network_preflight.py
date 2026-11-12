import importlib.util
import socket
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("network_preflight.py")
SPEC = importlib.util.spec_from_file_location("network_preflight", MODULE_PATH)
network_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(network_preflight)


class NetworkPreflightTests(unittest.TestCase):
    def test_dns_failure_is_reported_without_attempting_tcp(self):
        def resolve(*_args, **_kwargs):
            raise socket.gaierror(-3, "Temporary failure in name resolution")

        def connect(*_args, **_kwargs):
            self.fail("TCP must not be attempted after DNS resolution fails")

        result = network_preflight.probe_hosts(
            ["micro.mamba.pm"], resolver=resolve, connector=connect
        )[0]

        self.assertEqual(result["host"], "micro.mamba.pm")
        self.assertEqual(result["stage"], "dns")
        self.assertFalse(result["ok"])
        self.assertIn("Temporary failure", result["error"])

    def test_tcp_failure_is_distinguished_from_dns_failure(self):
        def resolve(*_args, **_kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.1", 443))]

        def connect(*_args, **_kwargs):
            raise TimeoutError("connect timed out")

        result = network_preflight.probe_hosts(
            ["pypi.org"], resolver=resolve, connector=connect
        )[0]

        self.assertEqual(result["stage"], "tcp")
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])

    def test_host_is_ready_only_after_dns_and_tcp_succeed(self):
        connected = []

        def resolve(*_args, **_kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.2", 443))]

        def connect(address, timeout):
            connected.append((address, timeout))
            return object()

        result = network_preflight.probe_hosts(
            ["conda.anaconda.org"], resolver=resolve, connector=connect
        )[0]

        self.assertTrue(result["ok"])
        self.assertEqual(result["stage"], "ready")
        self.assertEqual(result["host"], "conda.anaconda.org")
        self.assertEqual(len(connected), 1)


if __name__ == "__main__":
    unittest.main()
