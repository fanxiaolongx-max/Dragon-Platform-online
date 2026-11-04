import unittest
from app.services.air_service import resolve_sql
from app.core.exceptions import QueryValidationError


class MonthWindowTests(unittest.TestCase):
    def test_window_crosses_year_and_applies_source_offset(self):
        self.assertEqual(resolve_sql("SELECT '{{prev_5_month}}', '{{prev_5_month_start}}', '{{prev_5_yyyymm}}'", '2026-02'), "SELECT '2025-09', '2025-09-01', '202509'")
        self.assertEqual(resolve_sql("SELECT '{{prev_5_month}}'", '2026-02', -1), "SELECT '2025-08'")
        self.assertEqual(resolve_sql("SELECT '{{month_end}}', '{{prev_month}}'", '2024-02'), "SELECT '2024-02-29', '2024-01'")

    def test_out_of_range_and_unknown_placeholders_are_errors(self):
        for key in ('prev_0_month', 'prev_121_month', 'prev_9999_month', 'prev_5_day'):
            with self.subTest(key=key), self.assertRaises(QueryValidationError):
                resolve_sql('{{' + key + '}}', '2026-10')
