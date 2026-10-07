"""AtomGit Docker 接入的定向验证, 不加载真实配置或访问线上仓库."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_module(name, configuration, dependencies=None):
    modules = {"config": configuration, **(dependencies or {})}
    spec = importlib.util.spec_from_file_location(name, PROJECT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


def response(status=200, data=None):
    result = requests.Response()
    result.status_code = status
    result.url = "https://api.atomgit.com/api/v5/test"
    result._content = json.dumps(data or {}).encode()
    return result


def repository(**changes):
    result = {
        "path": "backup",
        "private": True,
        "visibility": "private",
        "http_url_to_repo": "https://atomgit.com/owner/backup.git",
    }
    result.update(changes)
    return result


class DockerConfigTests(unittest.TestCase):
    def setUp(self):
        self.loader = types.ModuleType("s3_config_loader")
        self.loader.load_env_from_s3 = Mock()
        self.dotenv = types.ModuleType("dotenv")
        self.dotenv.load_dotenv = Mock(side_effect=AssertionError("不应加载本地 .env"))
        self.dependencies = {"s3_config_loader": self.loader, "dotenv": self.dotenv}

    def test_missing_s3_settings_fail_before_loading_config(self):
        cases = (
            ({}, ("S3_ENDPOINT", "S3_BUCKET")),
            ({"S3_ENDPOINT": "https://s3.example"}, ("S3_BUCKET",)),
            ({"S3_BUCKET": "test"}, ("S3_ENDPOINT",)),
            ({"S3_ENDPOINT": "  ", "S3_BUCKET": "\t"}, ("S3_ENDPOINT", "S3_BUCKET")),
        )
        for environment, missing in cases:
            with self.subTest(environment=environment):
                stderr = io.StringIO()
                with patch.dict("os.environ", environment, clear=True), patch("sys.stderr", stderr):
                    with patch("builtins.open", side_effect=AssertionError("不应读取本地文件")):
                        with self.assertRaises(SystemExit) as error:
                            load_module("config", types.SimpleNamespace(), self.dependencies)
                self.assertEqual(error.exception.code, 1)
                self.assertIn("Docker", stderr.getvalue())
                for key in missing:
                    self.assertIn(key, stderr.getvalue())
        self.loader.load_env_from_s3.assert_not_called()
        self.dotenv.load_dotenv.assert_not_called()

    def test_valid_s3_settings_load_remote_config_only(self):
        # 模拟远程配置注入必需凭据, 不读取真实 .env 或访问 S3.
        def load_remote_config():
            import os

            os.environ.update(CODEUP_TOKEN="fake", CODEUP_ORG_ID="test-org")

        self.loader.load_env_from_s3.side_effect = load_remote_config
        environment = {"S3_ENDPOINT": "https://s3.example", "S3_BUCKET": "test"}
        with patch.dict("os.environ", environment, clear=True):
            with patch("builtins.open", side_effect=AssertionError("不应读取本地文件")):
                configuration = load_module("config", types.SimpleNamespace(), self.dependencies)
        self.loader.load_env_from_s3.assert_called_once_with()
        self.dotenv.load_dotenv.assert_not_called()
        self.assertEqual(configuration.CODEUP_TOKEN, "fake")
        self.assertEqual(configuration.CODEUP_ORG_ID, "test-org")
        self.assertEqual(configuration.S3_ENDPOINT, "https://s3.example")
        self.assertEqual(configuration.S3_BUCKET, "test")


class AtomGitClientTests(unittest.TestCase):
    def setUp(self):
        self.configuration = types.SimpleNamespace(
            ATOMGIT_TOKEN="test-pat", ATOMGIT_API_BASE="https://api.atomgit.com/api/v5"
        )
        self.module = load_module("atomgit_client", self.configuration)
        self.session = Mock()
        self.session.headers = {}
        self.session.get.return_value = response(data={"login": "owner", "name": "Display Name"})
        with patch.object(self.module.requests, "Session", return_value=self.session):
            self.client = self.module.AtomGitClient()

    def test_auth_and_login(self):
        self.assertEqual(self.client.username, "owner")
        self.assertEqual(self.session.headers["Authorization"], "Bearer test-pat")
        self.session.get.assert_called_once_with("https://api.atomgit.com/api/v5/user", timeout=30)

    def test_only_404_is_absent(self):
        self.session.get.return_value = response(404)
        self.assertFalse(self.client.repo_exists("backup"))
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                self.session.get.return_value = response(status)
                with self.assertRaises(requests.HTTPError):
                    self.client.repo_exists("backup")

    def test_create_explicit_private_path_and_no_readme(self):
        for status in (200, 201):
            with self.subTest(status=status):
                self.session.post.return_value = response(status, {"id": 42})
                self.session.get.return_value = response(data=repository())
                self.client.create_repo("Display", "backup", "Description")
                self.session.post.assert_called_with(
                    "https://api.atomgit.com/api/v5/user/repos",
                    json={"name": "Display", "path": "backup", "description": "Description",
                          "private": True, "auto_init": False},
                    timeout=30,
                )
                self.assertEqual(self.client.push_url("backup"), repository()["http_url_to_repo"])
                self.assertNotIn("test-pat", self.client.push_url("backup"))

    def test_reject_unsafe_repository(self):
        unsafe = [
            repository(private=False, visibility="public"),
            repository(private=False, visibility=None),
            repository(private=True, visibility="internal"),
            repository(private=False, visibility="private"),
            repository(private="true", visibility="private"),
            repository(public=True),
            repository(path="other"),
            repository(http_url_to_repo="https://evil.example/owner/backup.git"),
            repository(http_url_to_repo="https://atomgit.com/another/backup.git"),
            repository(http_url_to_repo="https://user:secret@atomgit.com/owner/backup.git"),
            repository(http_url_to_repo="http://atomgit.com/owner/backup.git"),
            repository(http_url_to_repo=""),
        ]
        for data in unsafe:
            with self.subTest(data=data):
                self.session.get.return_value = response(data=data)
                with self.assertRaises(RuntimeError):
                    self.client.repo_exists("backup")

    def test_verify_details_after_creation(self):
        self.session.post.return_value = response(201, {"id": 42})
        self.session.get.return_value = response(data=repository(private=False, visibility="public"))
        with self.assertRaises(RuntimeError):
            self.client.create_repo("Display", "backup")


class StateIsolationTests(unittest.TestCase):
    def test_local_and_s3_keys_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            configuration = types.SimpleNamespace(
                S3_ENABLED=False,
                LOCAL_STATE_FILE=f"{directory}/gitlab.json",
                LOCAL_STATE_FILE_GITEE=f"{directory}/gitee.json",
                LOCAL_STATE_FILE_ATOMGIT=f"{directory}/atomgit.json",
                S3_ENDPOINT="https://s3.example", S3_BUCKET="test",
                S3_ACCESS_KEY_ID="fake", S3_SECRET_ACCESS_KEY="fake", S3_REGION="test",
                S3_SESSION_TOKEN="", S3_STATE_KEY="gitlab", S3_STATE_KEY_GITEE="gitee",
                S3_STATE_KEY_ATOMGIT="atomgit",
            )
            module = load_module("state_store", configuration)
            stores = [module.get_store(), module.get_store(use_gitee=True),
                      module.get_store(use_atomgit=True)]
            stores[0].save({"backup": "old"})
            self.assertEqual(stores[2].load(), {})
            stores[2].save({"backup": "new"})
            self.assertEqual(stores[0].load(), {"backup": "old"})
            self.assertEqual(stores[1].load(), {})
            configuration.S3_ENABLED = True
            fake_boto = types.ModuleType("boto3")
            fake_boto.client = Mock()
            fake_config = types.ModuleType("botocore.config")
            fake_config.Config = Mock()
            with patch.dict(sys.modules, {"boto3": fake_boto, "botocore.config": fake_config}):
                for options, key in (({}, "gitlab"), ({"use_gitee": True}, "gitee"),
                                     ({"use_atomgit": True}, "atomgit")):
                    with self.subTest(key=key):
                        store = module.get_store(**options)
                        store.save({"backup": "new"})
                        self.assertEqual(
                            fake_boto.client.return_value.put_object.call_args.kwargs["Key"], key
                        )
                for location in ("", configuration.S3_STATE_KEY, configuration.S3_STATE_KEY_GITEE):
                    with self.subTest(s3_location=location):
                        configuration.S3_STATE_KEY_ATOMGIT = location
                        with self.assertRaises(ValueError):
                            module.get_store(use_atomgit=True)
            configuration.S3_ENABLED = False
            for location in ("", configuration.LOCAL_STATE_FILE, configuration.LOCAL_STATE_FILE_GITEE,
                             f"{directory}/./gitlab.json"):
                with self.subTest(local_location=location):
                    configuration.LOCAL_STATE_FILE_ATOMGIT = location
                    with self.assertRaises(ValueError):
                        module.get_store(use_atomgit=True)


class DockerFlowTests(unittest.TestCase):
    def setUp(self):
        self.configuration = types.SimpleNamespace(
            ATOMGIT_TOKEN="fake", GITLAB_TOKEN="", GITLAB_NAMESPACE_PATH="", GITLAB_NAMESPACE_ID=0,
            GITEE_TOKEN="", FORCE_FULL=False, BATCH_SIZE=10, CONCURRENCY=1,
        )
        self.codeup = Mock()
        self.codeup.list_repositories.return_value = [{
            "name": "Display", "path": "backup", "httpUrlToRepo": "https://source/repo.git",
            "lastActivityAt": "today",
        }]
        self.client = Mock(username="owner", token="fake", api_base="https://api.atomgit.com/api/v5")
        self.client.repo_exists.return_value = False
        self.client.push_url.return_value = "https://atomgit.com/owner/backup.git"
        self.store = Mock()
        self.store.load.return_value = {}
        dependencies = {}
        for name, class_name, instance in (
            ("codeup_client", "CodeupClient", self.codeup),
            ("gitlab_client", "GitLabClient", Mock()),
            ("gitee_client", "GiteeClient", Mock()),
            ("atomgit_client", "AtomGitClient", self.client),
        ):
            module = types.ModuleType(name)
            setattr(module, class_name, Mock(return_value=instance))
            dependencies[name] = module
        self.sync = types.ModuleType("git_sync")
        self.sync.mirror_repo = Mock()
        dependencies["git_sync"] = self.sync
        self.states = types.ModuleType("state_store")
        self.states.get_store = Mock(return_value=self.store)
        dependencies["state_store"] = self.states
        self.module = load_module("unified_backup", self.configuration, dependencies)
        self.module._log = Mock()

    def test_atomgit_only_and_success_state(self):
        self.assertEqual(self.module.backup(), 0)
        self.client.create_repo.assert_called_once_with(name="Display", path="backup", description="")
        self.sync.mirror_repo.assert_called_once_with(
            "https://source/repo.git", "https://atomgit.com/owner/backup.git", "backup",
            target_username="owner", target_password="fake",
        )
        self.states.get_store.assert_called_once_with(use_gitee=False, use_atomgit=True)
        self.store.save.assert_called_once_with({
            "target": {"api_base": "https://api.atomgit.com/api/v5", "login": "owner"},
            "repositories": {"backup": "today"},
        })

    def test_failure_does_not_advance_state(self):
        self.sync.mirror_repo.side_effect = RuntimeError("push failed")
        self.assertEqual(self.module.backup(), 1)
        self.store.save.assert_not_called()

    def test_unchanged_is_skipped(self):
        self.store.load.return_value = {
            "target": {"api_base": "https://api.atomgit.com/api/v5", "login": "owner"},
            "repositories": {"backup": "today"},
        }
        self.assertEqual(self.module.backup(), 0)
        self.sync.mirror_repo.assert_not_called()

    def test_changed_account_triggers_full_backup(self):
        self.store.load.return_value = {
            "target": {"api_base": "https://api.atomgit.com/api/v5", "login": "old-owner"},
            "repositories": {"backup": "today"},
        }
        self.assertEqual(self.module.backup(), 0)
        self.sync.mirror_repo.assert_called_once()

    def test_atomgit_auth_failure_reports_failure(self):
        self.module.AtomGitClient.side_effect = RuntimeError("401 Unauthorized")
        self.assertEqual(self.module.backup(), 1)

    def test_legacy_platform_order_and_signatures(self):
        self.configuration.GITLAB_TOKEN = "fake"
        self.configuration.GITLAB_NAMESPACE_PATH = "group"
        self.configuration.GITLAB_NAMESPACE_ID = 1
        self.configuration.GITEE_TOKEN = "fake"
        self.configuration.ATOMGIT_TOKEN = ""
        self.module.backup_to_platform = Mock(return_value=(1, 0, 0))
        self.assertEqual(self.module.backup(), 0)
        self.assertEqual([call.args[0] for call in self.module.backup_to_platform.call_args_list],
                         ["GitLab", "Gitee"])
        client = Mock()
        client.repo_exists.return_value = False
        for platform in ("GitLab", "Gitee"):
            client.reset_mock()
            self.module._sync_one_repo(client, platform, "backup", "Display", "source", "", 1, 1)
            if platform == "GitLab":
                client.create_repo.assert_called_once_with(name="Display", path="backup", description="")
            else:
                client.create_repo.assert_called_once_with(name="backup", description="", private=True)


class GitCredentialTests(unittest.TestCase):
    def test_password_not_in_git_arguments_and_error(self):
        with tempfile.TemporaryDirectory() as directory:
            configuration = types.SimpleNamespace(WORK_DIR=directory, CODEUP_TOKEN="source-pat", GITLAB_TOKEN="old")
            module = load_module("git_sync", configuration)
            with patch.object(module.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)) as run:
                module.mirror_repo("https://source/repo.git", "https://atomgit.com/owner/backup.git",
                                   "backup", target_username="owner", target_password="destination-pat")
                push_call = run.call_args_list[1]
                self.assertNotIn("destination-pat", " ".join(push_call.args[0]))
                self.assertIn("https://owner@atomgit.com/owner/backup.git", push_call.args[0])
                self.assertEqual(push_call.kwargs["env"]["GIT_PASSWORD"], "destination-pat")
                self.assertIn("credential.helper=", push_call.args[0])
            with patch.object(module.subprocess, "run", return_value=types.SimpleNamespace(
                returncode=1, stderr="failed destination-pat"
            )):
                with self.assertRaises(RuntimeError) as error:
                    module._run_git(["push", "https://owner@atomgit.com/test.git"], "destination-pat")
                self.assertNotIn("destination-pat", str(error.exception))

    def test_real_local_git_mirror_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            configuration = types.SimpleNamespace(WORK_DIR=f"{directory}/work", CODEUP_TOKEN="fake", GITLAB_TOKEN="")
            module = load_module("git_sync", configuration)
            source = f"{directory}/source"
            destination = f"{directory}/destination.git"

            def git(*args, cwd=None):
                return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout

            git("init", source)
            git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "test", cwd=source)
            git("branch", "feature", cwd=source)
            git("tag", "v1", cwd=source)
            git("init", "--bare", destination)
            # 本地 Git 集成验证不使用 HTTPS, 仅替换地址认证处理以保留真实 clone/push.
            with patch.object(module, "_strip_credentials", side_effect=lambda url, **kwargs: url):
                module.mirror_repo(source, destination, "backup", target_username="owner", target_password="fake")
            self.assertEqual(git("show-ref", cwd=source), git("show-ref", cwd=destination))
            self.assertFalse(Path(directory, "work", "backup.git").exists())


class StatusTests(unittest.TestCase):
    def test_status_reports_atomgit_without_token(self):
        module = load_module("web_server", types.SimpleNamespace())
        handler = object.__new__(module.StatusHandler)
        handler.path = "/status"
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        with patch.dict("os.environ", {"ATOMGIT_TOKEN": "fake-secret"}, clear=True):
            handler.do_GET()
        status = json.loads(handler.wfile.getvalue())
        self.assertEqual(status["platforms"]["atomgit"], "configured")
        self.assertNotIn("fake-secret", handler.wfile.getvalue().decode())


if __name__ == "__main__":
    unittest.main()
