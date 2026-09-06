import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "deploy" / "m7-rds-sync.sh"
OVERNIGHT = ROOT / "deploy" / "run-m7-wiki-overnight.sh"
INCREMENTAL = ROOT / "deploy" / "run-m7-incremental.sh"


class M7DeploymentScriptTests(unittest.TestCase):
    def run_bash(self, script):
        return subprocess.run(
            ["bash", "-c", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_rds_operation_retries_until_success(self):
        result = self.run_bash(
            f'. "{HELPER}"; '
            'sleep() { :; }; calls=0; '
            'flaky() { calls=$((calls + 1)); test "$calls" -ge 3; }; '
            'retry_with_backoff 3 0 flaky; printf "%s" "$calls"'
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "3")
        self.assertIn("attempt 1/3 failed", result.stderr)
        self.assertIn("attempt 2/3 failed", result.stderr)

    def test_exhausted_periodic_sync_is_nonfatal(self):
        result = self.run_bash(
            f'set -e; . "{HELPER}"; '
            'failed_sync() { return 17; }; '
            'run_nonfatal "periodic RDS sync" failed_sync; echo continued'
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "continued")
        self.assertIn("non-fatal periodic RDS sync failure (status 17)", result.stderr)

    def test_periodic_sync_is_nonfatal_but_final_sync_is_strict(self):
        script = OVERNIGHT.read_text(encoding="utf-8")

        self.assertIn(
            'run_nonfatal "periodic RDS sync" sync_rds "$cycle" "$stamp"',
            script,
        )
        self.assertIn('sync_rds "final" "$final_stamp"', script)
        self.assertNotIn(
            'run_nonfatal "final RDS sync" sync_rds "final"',
            script,
        )

    def test_rds_import_uses_bounded_commit_intervals(self):
        script = OVERNIGHT.read_text(encoding="utf-8")

        self.assertIn("HKSR_M7_RDS_COMMIT_INTERVAL:-500", script)
        self.assertIn('--commit-interval "$rds_commit_interval"', script)

    def test_incremental_rebuilds_index_only_after_new_parse_results(self):
        script = INCREMENTAL.read_text(encoding="utf-8")

        self.assertIn('parse > "$parse_report"', script)
        self.assertIn('if test "$parsed_count" -gt 0; then', script)
        self.assertIn('no_newly_parsed_sources', script)

    def test_deployment_scripts_have_valid_bash_syntax(self):
        for path in (HELPER, OVERNIGHT, INCREMENTAL):
            result = subprocess.run(
                ["bash", "-n", str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
