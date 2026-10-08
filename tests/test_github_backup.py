"""GitHub 私有备份定向验证, 只使用合成配置和接口响应."""
import io
import json
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import requests

import test_atomgit_backup as atomgit_tests
from test_atomgit_backup import load_module, response


def repository(**changes):
    data = {"name": "backup", "full_name": "owner/backup", "private": True,
            "visibility": "private", "archived": False, "disabled": False,
            "owner": {"login": "owner", "id": 42}, "clone_url": "https://github.com/owner/backup.git"}
    data.update(changes)
    return data


class GitHubClientTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module("github_client", types.SimpleNamespace(GITHUB_BACKUP_TOKEN="fake-github-pat"))
        self.session = Mock(headers={})
        self.session.get.return_value = response(data={"login": "owner", "id": 42})
        with patch.object(self.module.requests, "Session", return_value=self.session):
            self.client = self.module.GitHubClient()

    def test_authenticated_user_and_headers(self):
        self.assertEqual(self.client.username, "owner")
        self.assertEqual(self.client.user_id, 42)
        self.assertEqual(self.session.headers["Authorization"], "Bearer fake-github-pat")
        self.session.get.assert_called_once_with("https://api.github.com/user", timeout=30, allow_redirects=False)

    def test_create_explicit_private_empty_repository(self):
        self.session.post.return_value = response(201, repository())
        self.session.get.side_effect = [response(data=repository()), response(data={"enabled": False})]
        self.session.put.return_value = response(204)
        self.client.create_repo("Display Name", "backup")
        self.session.post.assert_called_once_with(
            "https://api.github.com/user/repos",
            json={"name": "backup", "description": "Backup from Aliyun Codeup", "private": True, "auto_init": False},
            timeout=30, allow_redirects=False,
        )
        self.session.put.assert_called_once_with(
            "https://api.github.com/repos/owner/backup/actions/permissions", json={"enabled": False},
            timeout=30, allow_redirects=False,
        )
        self.assertEqual(self.client.push_url("backup"), "https://github.com/owner/backup.git")

    def test_only_404_means_absent_and_redirect_rejected(self):
        self.session.get.return_value = response(404)
        self.assertFalse(self.client.repo_exists("backup"))
        for status in (301, 302, 401, 403, 429, 500):
            with self.subTest(status=status):
                self.session.get.return_value = response(status)
                with self.assertRaises((requests.HTTPError, RuntimeError)):
                    self.client.repo_exists("backup")

    def test_reject_unsafe_targets(self):
        cases = [repository(private=False), repository(private=1), repository(visibility="public"),
                 repository(archived=True), repository(archived=None), repository(disabled=True),
                 repository(owner={"login": "owner", "id": 9}), repository(full_name="other/backup"),
                 repository(clone_url="https://evil.example/owner/backup.git"),
                 repository(clone_url="https://user:secret@github.com/owner/backup.git"),
                 repository(clone_url="https://github.com/owner/other.git"),
                 repository(clone_url="http://github.com/owner/backup.git")]
        for data in cases:
            with self.subTest(data=data):
                self.session.get.return_value = response(data=data)
                with self.assertRaises(RuntimeError):
                    self.client.repo_exists("backup")

    def test_invalid_name_rejected_before_request(self):
        self.session.get.reset_mock()
        for path in ("space name", "../backup", "group/backup", ".", "..", "", "a" * 101):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.client.repo_exists(path)
        self.session.get.assert_not_called()

    def test_creation_rechecks_private_details(self):
        self.session.post.return_value = response(201, repository())
        self.session.put.return_value = response(204)
        self.session.get.return_value = response(data=repository(private=False))
        with self.assertRaises(RuntimeError):
            self.client.create_repo("Display", "backup")


    def test_existing_actions_enabled_rejected_without_changes(self):
        self.session.get.side_effect = [response(data=repository()), response(data={"enabled": True})]
        with self.assertRaises(RuntimeError):
            self.client.repo_exists("backup")
        self.session.put.assert_not_called()

    def test_actions_permission_failure_blocks_creation(self):
        self.session.post.return_value = response(201, repository())
        self.session.put.return_value = response(403)
        with self.assertRaises(requests.HTTPError):
            self.client.create_repo("Display", "backup")


    def test_failed_actions_check_does_not_cache_push_url(self):
        self.session.get.side_effect = [response(data=repository()), response(403)]
        with self.assertRaises(requests.HTTPError):
            self.client.repo_exists("backup")
        self.assertNotIn("backup", self.client._push_urls)


class GitHubDockerFlowTests(unittest.TestCase):
    def setUp(self):
        fixture = atomgit_tests.DockerFlowTests()
        fixture.setUp()
        self.fixture = fixture
        self.module = fixture.module
        fixture.configuration.ATOMGIT_TOKEN = ""
        fixture.configuration.GITHUB_BACKUP_TOKEN = "fake-github-pat"
        fixture.client.username = "owner"
        fixture.client.token = "fake-github-pat"
        fixture.client.user_id = 42
        fixture.client.api_base = "https://api.github.com"
        fixture.client.push_url.return_value = "https://github.com/owner/backup.git"
        self.module.GitHubClient.return_value = fixture.client

    def test_github_only_success_and_independent_state(self):
        self.assertEqual(self.module.backup(), 0)
        self.fixture.client.create_repo.assert_called_once_with(name="Display", path="backup", description="")
        self.fixture.states.get_store.assert_called_once_with(use_gitee=False, use_atomgit=False, use_github=True)
        self.fixture.sync.mirror_repo.assert_called_once_with(
            "https://source/repo.git", "https://github.com/owner/backup.git", "backup",
            target_username="owner", target_password="fake-github-pat",
        )
        self.fixture.store.save.assert_called_once_with({
            "target": {"api_base": "https://api.github.com", "login": "owner", "user_id": 42},
            "repositories": {"backup": "today"},
        })

    def test_account_id_change_triggers_full_backup(self):
        self.fixture.store.load.return_value = {
            "target": {"api_base": "https://api.github.com", "login": "owner", "user_id": 9},
            "repositories": {"backup": "today"},
        }
        self.assertEqual(self.module.backup(), 0)
        self.fixture.sync.mirror_repo.assert_called_once()

    def test_unchanged_target_is_skipped(self):
        self.fixture.store.load.return_value = {
            "target": {"api_base": "https://api.github.com", "login": "owner", "user_id": 42},
            "repositories": {"backup": "today"},
        }
        self.assertEqual(self.module.backup(), 0)
        self.fixture.sync.mirror_repo.assert_not_called()

    def test_auth_error_is_failure(self):
        self.module.GitHubClient.side_effect = RuntimeError("401 Unauthorized")
        self.assertEqual(self.module.backup(), 1)

    def test_case_conflicting_paths_rejected_before_push(self):
        self.fixture.codeup.list_repositories.return_value.append({
            "name": "Other", "path": "BACKUP", "httpUrlToRepo": "https://source/other.git",
        })
        self.assertEqual(self.module.backup(), 1)
        self.fixture.sync.mirror_repo.assert_not_called()

    def test_push_failure_does_not_update_state(self):
        self.fixture.sync.mirror_repo.side_effect = RuntimeError("push rejected")
        self.assertEqual(self.module.backup(), 1)
        self.fixture.store.save.assert_not_called()


class GitHubStateTests(unittest.TestCase):
    def test_local_github_state_and_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            configuration = types.SimpleNamespace(S3_ENABLED=False,
                LOCAL_STATE_FILE=f"{directory}/gitlab", LOCAL_STATE_FILE_GITEE=f"{directory}/gitee",
                LOCAL_STATE_FILE_ATOMGIT=f"{directory}/atomgit", LOCAL_STATE_FILE_GITHUB=f"{directory}/github")
            module = load_module("state_store", configuration)
            github = module.get_store(use_github=True)
            github.save({"test": "new"})
            self.assertEqual(module.get_store().load(), {})
            self.assertEqual(github.load(), {"test": "new"})
            for location in ("", configuration.LOCAL_STATE_FILE, configuration.LOCAL_STATE_FILE_ATOMGIT):
                configuration.LOCAL_STATE_FILE_GITHUB = location
                with self.assertRaises(ValueError):
                    module.get_store(use_github=True)
            with self.assertRaises(ValueError):
                module.get_store(use_atomgit=True, use_github=True)

    def test_s3_github_key_and_collisions(self):
        configuration = types.SimpleNamespace(S3_ENABLED=True, S3_STATE_KEY="gitlab", S3_STATE_KEY_GITEE="gitee",
            S3_STATE_KEY_ATOMGIT="atomgit", S3_STATE_KEY_GITHUB="github", S3_ENDPOINT="https://s3.example",
            S3_ACCESS_KEY_ID="fake", S3_SECRET_ACCESS_KEY="fake", S3_REGION="test", S3_SESSION_TOKEN="", S3_BUCKET="test")
        module = load_module("state_store", configuration)
        boto = types.ModuleType("boto3")
        boto.client = Mock()
        botoconfig = types.ModuleType("botocore.config")
        botoconfig.Config = Mock()
        with patch.dict("sys.modules", {"boto3": boto, "botocore.config": botoconfig}):
            module.get_store(use_github=True).save({"test": "new"})
            self.assertEqual(boto.client.return_value.put_object.call_args.kwargs["Key"], "github")
            for location in ("", "gitlab", "gitee", "atomgit"):
                configuration.S3_STATE_KEY_GITHUB = location
                with self.assertRaises(ValueError):
                    module.get_store(use_github=True)

    def test_status_does_not_use_actions_token_or_expose_backup_token(self):
        module = load_module("web_server", types.SimpleNamespace())
        handler = object.__new__(module.StatusHandler)
        handler.path = "/status"
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        with patch.dict("os.environ", {"GITHUB_TOKEN": "fake-actions-token"}, clear=True):
            handler.do_GET()
        self.assertEqual(json.loads(handler.wfile.getvalue())["platforms"]["github"], "not configured")
        handler.wfile = io.BytesIO()
        with patch.dict("os.environ", {"GITHUB_BACKUP_TOKEN": "fake-backup-secret"}, clear=True):
            handler.do_GET()
        self.assertEqual(json.loads(handler.wfile.getvalue())["platforms"]["github"], "configured")
        self.assertNotIn("fake-backup-secret", handler.wfile.getvalue().decode())


if __name__ == "__main__":
    unittest.main()
