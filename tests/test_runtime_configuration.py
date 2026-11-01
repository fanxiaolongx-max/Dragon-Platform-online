import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.config import Settings, configuration_origins

ROOT = Path(__file__).resolve().parents[1]

class RuntimeConfigurationTests(unittest.TestCase):
    def test_injected_group_wins_over_old_dotenv_in_both_environments(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / '.env'
            dotenv.write_text('BUSINESS_DATASOURCE_NAME=old-group\nRELOAD=true\n')
            for group in ('environment-A', 'environment-B'):
                with patch.dict(os.environ, {'BUSINESS_DATASOURCE_NAME': group, 'RELOAD': 'false'}):
                    config = Settings(_env_file=dotenv)
                    self.assertEqual(config.BUSINESS_DATASOURCE_NAME, group)
                    self.assertFalse(config.RELOAD)
        origins = configuration_origins()
        self.assertEqual(set(origins), {'BASE_QUERY_URL','APP_DATASOURCE_ID','APP_SCHEMA','BUSINESS_DATASOURCE_NAME','PORT','WORKERS','RELOAD'})
        self.assertTrue(all(set(value) == {'source','environmentPresentAtLoad','dotenvContainsField','environmentChangedSinceLoad','environmentMatchesLoaded','dotenvMatchesLoaded'} for value in origins.values()))

    def test_production_server_has_no_reloader_and_development_watch_excludes_venv(self):
        spec = importlib.util.spec_from_file_location('runtime_entry_test', ROOT / 'run.py')
        entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)
        config = Settings(_env_file=None, RELOAD=False, PORT=20455, WORKERS=1)
        with patch.object(entry, 'settings', config):
            options = entry.server_options()
            self.assertFalse(options['reload']); self.assertNotIn('reload_dirs', options)
            self.assertEqual(options['workers'], 1); self.assertEqual(options['port'], 20455)
            config.RELOAD = True
            options = entry.server_options()
            self.assertEqual(options['reload_dirs'], [str(ROOT / 'app')])
            self.assertIn('venv/*', options['reload_excludes'])
            config.APP_SCHEMA = 'assigned-app'
            self.assertFalse(entry.server_options()['reload'], 'Managed deployments must ignore stale RELOAD=true')
        with patch.object(entry.uvicorn, 'run', side_effect=SystemExit(3)):
            with self.assertRaises(SystemExit) as caught:
                entry.main()
            self.assertEqual(caught.exception.code, 3, 'A port/startup failure must remain a failed process exit')
