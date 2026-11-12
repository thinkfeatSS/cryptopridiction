"""
QUANT EDGE V16: Network Socket Resilience & Offline Test Isolation Test Suite
Verifies that background threads and connection helpers gracefully handle offline
test runs (MySQL port 3306, Baileys WhatsApp port 8080, Redis port 6379, WebSocket feeds)
without unhandled WinError 10061 connection failures, thread thrashing, or diagnostic spam,
while preserving full production connectivity when deployed via Docker Compose.
"""

import os
import sys
import time
import socket
import unittest
from unittest.mock import patch, MagicMock

from app.database import is_test_environment, is_socket_reachable, get_engine
from app.services.whatsapp_service import WhatsAppService, is_test_environment as wa_is_test_env
from app.services.cache_service import CacheService


class TestNetworkSocketResilience(unittest.TestCase):
    """
    Forensic unit and integration tests for offline test isolation,
    socket resilience, and production parity.
    """

    def setUp(self):
        self.orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    # =========================================================================
    # 1. TEST ENVIRONMENT DETECTION VECTOR INTEGRITY
    # =========================================================================
    def test_01_is_test_environment_detects_all_test_runners(self):
        """Verifies is_test_environment correctly identifies testing across all vectors."""
        # Baseline in active test run
        self.assertTrue(is_test_environment())
        self.assertTrue(wa_is_test_env())

        # Vector A: TESTING env var
        with patch.dict(os.environ, {"TESTING": "1"}):
            self.assertTrue(is_test_environment())

        with patch.dict(os.environ, {"ENVIRONMENT": "testing"}):
            self.assertTrue(is_test_environment())

        with patch.dict(os.environ, {"CI": "true"}):
            self.assertTrue(is_test_environment())

    def test_02_is_test_environment_production_simulation(self):
        """Verifies is_test_environment safely returns False under production container flags."""
        # Mock sys.modules, sys.argv, and sys.orig_argv to simulate production daemon container
        mock_argv = ["run_scanner_daemon.py"]
        mock_orig_argv = ["/usr/local/bin/python", "run_scanner_daemon.py"]
        
        with patch.object(sys, "argv", mock_argv), \
             patch.object(sys, "orig_argv", mock_orig_argv, create=True), \
             patch.dict(os.environ, {"TESTING": "0", "ENVIRONMENT": "production", "CI": ""}, clear=True):
            
            # Temporarily hide test runners from sys.modules
            filtered_modules = {k: v for k, v in sys.modules.items() if not any(t in k for t in ("pytest", "unittest", "testclient"))}
            with patch.dict(sys.modules, filtered_modules, clear=True):
                self.assertFalse(is_test_environment())

    # =========================================================================
    # 2. DATABASE PORT 3306 ISOLATION & FALLBACK INTEGRITY
    # =========================================================================
    def test_03_database_offline_test_selects_sqlite_without_socket_probe(self):
        """Verifies database initialization uses SQLite fallback directly in tests without probing MySQL socket."""
        with patch("app.database.is_socket_reachable") as mock_probe:
            with patch.dict(os.environ, {"TESTING": "1", "MYSQL_TEST_CONNECT": "0"}):
                eng = get_engine()
                # When in test mode and MYSQL_TEST_CONNECT != 1, socket check must NOT be invoked
                mock_probe.assert_not_called()
                self.assertIn("sqlite", str(eng.url).lower())

    def test_04_database_honors_explicit_mysql_probe_when_requested(self):
        """Verifies database attempts MySQL socket check when MYSQL_TEST_CONNECT is explicitly set."""
        with patch("app.database.is_socket_reachable", return_value=False) as mock_probe:
            with patch.dict(os.environ, {"TESTING": "1", "MYSQL_TEST_CONNECT": "1"}):
                eng = get_engine()
                # With MYSQL_TEST_CONNECT == 1, socket check is explicitly engaged
                mock_probe.assert_called()
                self.assertIn("sqlite", str(eng.url).lower())

    def test_05_is_socket_reachable_handles_closed_port_safely(self):
        """Verifies is_socket_reachable catches connection exceptions gracefully without bubbling."""
        # Test connecting to an unused localhost port with very small timeout
        reachable = is_socket_reachable("127.0.0.1", 65534, timeout=0.05)
        self.assertFalse(reachable)

    # =========================================================================
    # 3. WHATSAPP GATEWAY PORT 8080 ISOLATION & BACKGROUND THREAD RESILIENCE
    # =========================================================================
    def test_06_whatsapp_gateway_offline_in_test_without_socket_probes(self):
        """Verifies WhatsAppService marks gateway offline in tests without opening sockets or error logs."""
        wa = WhatsAppService()
        self.assertTrue(wa.is_test_environment())
        
        # When WHATSAPP_TEST_CONNECT is not 1, gateway availability check is immediately False
        with patch("socket.socket") as mock_sock:
            self.assertFalse(wa.is_gateway_available())
            mock_sock.assert_not_called()

        health = wa.check_gateway_health()
        self.assertFalse(health["healthy"])
        self.assertEqual(health["state"], "test_offline")

    def test_07_whatsapp_spool_persists_without_queue_thrashing(self):
        """Verifies messages enqueued during offline tests are safely persisted without thrashing worker."""
        wa = WhatsAppService()
        test_jid = "120363431167900107@g.us"
        test_msg = f"Test offline resilience at {time.time()}"

        init_spool_count = len(wa._spool)
        wa._enqueue_message(test_jid, test_msg, priority=5)

        # Spool must have incremented by 1 and persisted to disk
        self.assertEqual(len(wa._spool), init_spool_count + 1)
        self.assertTrue(os.path.exists(wa._spool_file))

        # Check status reporting
        status = wa.get_status()
        self.assertTrue(status["is_test_environment"])
        self.assertFalse(status["gateway_connected"])
        self.assertGreaterEqual(status["pending_spool_count"], 1)

    # =========================================================================
    # 4. CACHE SERVICE PORT 6379 RESILIENCE
    # =========================================================================
    def test_08_cache_service_offline_test_skips_redis_probe(self):
        """Verifies CacheService skips Redis port 6379 socket probe in offline test mode."""
        with patch("socket.socket") as mock_sock:
            with patch.dict(os.environ, {"TESTING": "1", "REDIS_TEST_CONNECT": "0"}):
                cache = CacheService()
                self.assertFalse(cache.is_available)
                mock_sock.assert_not_called()

    def test_09_cache_service_honors_explicit_redis_test_probe(self):
        """Verifies CacheService engages socket probe when REDIS_TEST_CONNECT == 1."""
        with patch("socket.socket") as mock_sock:
            mock_sock.return_value.connect_ex.return_value = 1  # Connection refused
            with patch.dict(os.environ, {"TESTING": "1", "REDIS_TEST_CONNECT": "1"}):
                cache = CacheService()
                self.assertFalse(cache.is_available)
                mock_sock.assert_called()


if __name__ == "__main__":
    unittest.main()

