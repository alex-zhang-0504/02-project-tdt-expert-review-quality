from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
from io import BytesIO
import json

from tdt_scoring.launcher import DEFAULT_PORTS, choose_service_port
from tdt_scoring.launcher import inspect_service, BUILD_ID, PROJECT_ID
from tdt_scoring.storage import workspace_id


class LauncherTests(unittest.TestCase):
    def test_same_build_in_different_workspace_is_not_reused(self):
        client = MagicMock()
        client.__enter__.return_value.connect_ex.return_value = 0
        health = {'project_id': PROJECT_ID, 'build_id': BUILD_ID, 'workspace_id': 'another-workspace'}
        with patch('tdt_scoring.launcher.socket.socket', return_value=client), patch('tdt_scoring.launcher.urlopen', return_value=BytesIO(json.dumps(health).encode())):
            self.assertEqual('occupied', inspect_service(8867))
        health['workspace_id'] = workspace_id()
        with patch('tdt_scoring.launcher.socket.socket', return_value=client), patch('tdt_scoring.launcher.urlopen', return_value=BytesIO(json.dumps(health).encode())):
            self.assertEqual('current', inspect_service(8867))

    def test_default_port_range_is_reserved_for_project_02(self) -> None:
        self.assertEqual(8865, DEFAULT_PORTS.start)
        self.assertEqual(8900, DEFAULT_PORTS.stop)

    def test_current_build_is_reused_even_when_an_earlier_port_is_free(self) -> None:
        states = {8765: "occupied", 8766: "free", 8767: "current"}

        action, port = choose_service_port(
            ports=range(8765, 8768),
            inspect=lambda candidate: states[candidate],
        )

        self.assertEqual(("reuse", 8767), (action, port))

    def test_first_free_port_is_selected_when_current_build_is_not_running(self) -> None:
        states = {8765: "occupied", 8766: "free", 8767: "free"}

        action, port = choose_service_port(
            ports=range(8765, 8768),
            inspect=lambda candidate: states[candidate],
        )

        self.assertEqual(("launch", 8766), (action, port))


if __name__ == "__main__":
    unittest.main()
