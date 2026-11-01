import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.config import (
    BETA_QUERY_URL,
    BETA_SCHEMA,
    PROD_QUERY_URL,
    PROD_SCHEMA,
    Settings,
    adapt_settings_from_headers,
    configuration_origins,
    settings,
)

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

    def test_beta_and_prod_profiles_auto_align_across_dotenv_and_env(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / '.env'
            dotenv.write_text(
                f'BASE_QUERY_URL={BETA_QUERY_URL}\n'
                f'APP_SCHEMA={BETA_SCHEMA}\n'
                f'APP_UUID={BETA_SCHEMA}\n'
                'INJECT_IDENTITY_HEADERS=true\n'
                'BUSINESS_DATASOURCE_NAME=netcare-digital-human-readonly\n'
            )
            # 1) 本地开发无环境变量注入：保持 Beta 配置及手动身份头注入，且自动映射旧业务库别名
            with patch.dict(os.environ, {}, clear=True):
                local_cfg = Settings(_env_file=dotenv)
                self.assertEqual(local_cfg.BASE_QUERY_URL, BETA_QUERY_URL)
                self.assertEqual(local_cfg.APP_SCHEMA, BETA_SCHEMA)
                self.assertEqual(local_cfg.APP_UUID, BETA_SCHEMA)
                self.assertTrue(local_cfg.INJECT_IDENTITY_HEADERS)
                self.assertEqual(local_cfg.BUSINESS_DATASOURCE_NAME, 'netcareClaw-operate-digital-readonly')

            # 2) 生产基座仅注入 APP_SCHEMA：自动对齐生产 URL、同步 APP_UUID，并关闭手动身份头
            with patch.dict(os.environ, {'APP_SCHEMA': PROD_SCHEMA}, clear=True):
                prod_cfg = Settings(_env_file=dotenv)
                self.assertEqual(prod_cfg.BASE_QUERY_URL, PROD_QUERY_URL)
                self.assertEqual(prod_cfg.APP_SCHEMA, PROD_SCHEMA)
                self.assertEqual(prod_cfg.APP_UUID, PROD_SCHEMA)
                self.assertFalse(prod_cfg.INJECT_IDENTITY_HEADERS)

            # 3) 生产基座仅注入 BASE_QUERY_URL：自动对齐生产 APP_SCHEMA 与 APP_UUID
            with patch.dict(os.environ, {'BASE_QUERY_URL': PROD_QUERY_URL}, clear=True):
                prod_url_cfg = Settings(_env_file=dotenv)
                self.assertEqual(prod_url_cfg.BASE_QUERY_URL, PROD_QUERY_URL)
                self.assertEqual(prod_url_cfg.APP_SCHEMA, PROD_SCHEMA)
                self.assertEqual(prod_url_cfg.APP_UUID, PROD_SCHEMA)
                self.assertFalse(prod_url_cfg.INJECT_IDENTITY_HEADERS)

    def test_header_domain_adaptation_switches_between_beta_and_prod(self):
        orig = (settings.BASE_QUERY_URL, settings.APP_SCHEMA, settings.APP_UUID)
        try:
            with patch.dict(os.environ, {}, clear=True):
                settings.BASE_QUERY_URL = BETA_QUERY_URL
                settings.APP_SCHEMA = BETA_SCHEMA
                settings.APP_UUID = BETA_SCHEMA
                switched = adapt_settings_from_headers({'host': 'netcareclaw.gde.huawei.com'})
                self.assertEqual(switched, 'prod')
                self.assertEqual(settings.BASE_QUERY_URL, PROD_QUERY_URL)
                self.assertEqual(settings.APP_SCHEMA, PROD_SCHEMA)
                self.assertEqual(settings.APP_UUID, PROD_SCHEMA)

                switched_back = adapt_settings_from_headers({'referer': 'https://netcareclaw-beta.icta138.huawei.com/digital-human/'})
                self.assertEqual(switched_back, 'beta')
                self.assertEqual(settings.BASE_QUERY_URL, BETA_QUERY_URL)
                self.assertEqual(settings.APP_SCHEMA, BETA_SCHEMA)
                self.assertEqual(settings.APP_UUID, BETA_SCHEMA)
        finally:
            settings.BASE_QUERY_URL, settings.APP_SCHEMA, settings.APP_UUID = orig

    def test_actual_environment_host_wins_over_stale_referer(self):
        original = settings.BASE_QUERY_URL, settings.APP_SCHEMA, settings.APP_UUID
        try:
            with patch.dict(os.environ, {}, clear=True):
                settings.BASE_QUERY_URL = PROD_QUERY_URL
                settings.APP_SCHEMA = settings.APP_UUID = PROD_SCHEMA
                result = adapt_settings_from_headers({'host': 'netcareclaw-beta.icta138.huawei.com', 'referer': 'https://netcareclaw.gde.huawei.com/'})
                self.assertEqual(result, 'beta')
                self.assertEqual(settings.APP_SCHEMA, BETA_SCHEMA)
        finally:
            settings.BASE_QUERY_URL, settings.APP_SCHEMA, settings.APP_UUID = original

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
