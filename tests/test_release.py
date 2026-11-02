import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


spec = importlib.util.spec_from_file_location("build_release", Path(__file__).resolve().parents[1] / "scripts/build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.output = Path(self.temp.name) / "out"
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        for name in release.REQUIRED:
            self.put(name, "1.4.0\n" if name.endswith(".version") else "BUSINESS_DATASOURCE_NAME=fixture-business\n" if name == ".env" else "fixture\n")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "core.hooksPath=/dev/null",
                        "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "fixture"], check=True)

    def put(self, name, content):
        file = self.root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)

    def track(self):
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)

    def test_upload_layout_manifest_and_checksum(self):
        metadata = release.build(self.root, self.output)
        self.assertEqual(metadata["version"], "1.4.0")
        base_pkg = metadata.get("basePackage", "AiOps-Report-v1.4.0-base.zip")
        platform_pkg = metadata.get("platformPackage", "AiOps-Report-v1.4.0-platform.zip")
        with zipfile.ZipFile(self.output / base_pkg) as base:
            self.assertTrue(release.REQUIRED <= set(base.namelist()))
            self.assertNotIn("platform-app.json", base.namelist())
        with zipfile.ZipFile(self.output / platform_pkg) as platform:
            manifest = json.loads(platform.read("platform-app.json"))
            self.assertEqual(manifest["entry"], "app.main:create_app")
            self.assertTrue(manifest["factory"])
            self.assertEqual(manifest["healthPath"], "/health")
            self.assertEqual(manifest["databaseContract"], "digital-human")
            self.assertIn("db/init.sqlite.sql", platform.namelist())
            self.assertIn("db/upgrade.sql", platform.namelist())
            self.assertIn("db/upgrade.sqlite.sql", platform.namelist())
        for line in (self.output / "SHA256SUMS").read_text().splitlines():
            expected, name = line.split("  ")
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), expected)
        before = (self.output / platform_pkg).read_bytes()
        release.build(self.root, self.output)
        self.assertEqual(before, (self.output / platform_pkg).read_bytes())

    def test_tracked_runtime_secrets_excluded_and_static_data_preserved(self):
        rejected = [".env.local", "app/.env.production", "app/private.key", "static/token.json",
                    "db/app.db", "app/__pycache__/a.pyc", "static/logs/a.log",
                    "_platform_host.py", ".github/workflows/release.yml", "dist/old.zip"]
        for name in rejected + [".env", "static/data/table_map.json", "app/services/new.py"]:
            self.put(name, "BUSINESS_DATASOURCE_NAME=fixture-business\n" if name == ".env" else "fixture")
        self.track()
        self.put("app/untracked.py", "local only")
        metadata = release.build(self.root, self.output)
        platform_pkg = metadata.get("platformPackage", f"AiOps-Report-v{metadata['version']}-platform.zip")
        with zipfile.ZipFile(self.output / platform_pkg) as archive:
            self.assertFalse(set(rejected) & set(archive.namelist()))
            self.assertNotIn("app/untracked.py", archive.namelist())
            self.assertIn(".env", archive.namelist())
            self.assertIn("static/data/table_map.json", archive.namelist())
            self.assertIn("app/services/new.py", archive.namelist())

    def test_packaged_env_keeps_reviewed_defaults_and_rejects_credentials(self):
        self.put('.env', '# private note excluded from package\nBUSINESS_DATASOURCE_NAME=assigned-business\nAPP_SCHEMA=eca61f00-e292-48ae-8767-c57826706e6a\nBASE_QUERY_URL=https://base.fixture/query\n')
        metadata = release.build(self.root, self.output)
        for key in ('basePackage', 'platformPackage'):
            with zipfile.ZipFile(self.output / metadata[key]) as archive:
                value = archive.read('.env').decode()
                self.assertIn('BUSINESS_DATASOURCE_NAME=assigned-business', value)
                self.assertNotIn('private note', value)
        for unsafe in ('AI_MODEL_ENCRYPTION_KEY=fixture-secret', 'AI_MODEL_KEY_FILE=/private/key', 'API_KEY=fixture-secret', 'BASE_QUERY_URL=https://user:fixture-secret@base.fixture/query', 'BASE_QUERY_URL=https://base.fixture/query?token=fixture-secret', 'UNKNOWN_SETTING=fixture-secret'):
            self.put('.env', 'BUSINESS_DATASOURCE_NAME=assigned-business\n' + unsafe + '\n')
            with self.assertRaises(ValueError) as caught:
                release.build(self.root, self.output)
            self.assertNotIn('fixture-secret', str(caught.exception))

    def test_missing_source_rejected(self):
        (self.root / "run.py").unlink()
        self.track()
        with self.assertRaisesRegex(ValueError, "Missing required source"):
            release.build(self.root, self.output)

    def test_invalid_version_rejected(self):
        self.put("AiOps-Report.version", "../../invalid")
        with self.assertRaisesRegex(ValueError, "release version"):
            release.build(self.root, self.output)

    def test_symlink_rejected(self):
        (self.root / "app/link.py").symlink_to(self.root / "run.py")
        self.track()
        with self.assertRaisesRegex(ValueError, "Symbolic links"):
            release.build(self.root, self.output)


if __name__ == "__main__":
    unittest.main()
