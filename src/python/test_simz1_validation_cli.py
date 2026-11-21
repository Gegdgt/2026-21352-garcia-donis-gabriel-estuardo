"""CLI destination regression checks; all exports are mocked, no filesystem cleanup."""
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import simz1_osm_turn_audit as turns
import simz1_priority_classification as priority
import test_simz1_visual_motion_integration as visual_fixture


class ValidationCliTests(unittest.TestCase):
    def test_static_audits_default_to_separate_runtime_destinations(self):
        for module, operation, expected, position in (
                (priority, 'export', 'runtime/validation/priority-classification', 1),
                (turns, 'audit', 'runtime/validation/osm-turns', 3)):
            with self.subTest(module=module.__name__), \
                    patch.object(module, operation, return_value={}) as export, \
                    patch('sys.stdout', new_callable=io.StringIO):
                module.main([])
                self.assertEqual(export.call_args.args[position], Path(expected))
                self.assertEqual(export.call_count, 1)

    def test_static_audits_preserve_explicit_destination_with_spaces(self):
        destination=Path('runtime/validation/review with spaces')
        for module, operation, position in ((priority, 'export', 1), (turns, 'audit', 3)):
            with self.subTest(module=module.__name__), \
                    patch.object(module, operation, return_value={}) as export, \
                    patch('sys.stdout', new_callable=io.StringIO):
                module.main(['--output-dir', str(destination)])
                self.assertEqual(export.call_args.args[position], destination)

    def test_visual_export_default_and_explicit_destination_do_not_run_tests(self):
        for arguments, expected in (([], Path('runtime/validation/visual-motion-fixture')),
                (['--output-dir', 'runtime/validation/fixture with spaces'],
                 Path('runtime/validation/fixture with spaces'))):
            with self.subTest(arguments=arguments), \
                    patch.object(visual_fixture, 'export_fixture') as export, \
                    patch.object(visual_fixture.unittest, 'main') as tests:
                visual_fixture.fixture_main(arguments)
                export.assert_called_once_with(expected)
                tests.assert_not_called()


if __name__ == '__main__':
    unittest.main()
