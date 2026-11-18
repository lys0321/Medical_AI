"""本机模式（数据不出本机）：开关、出站清单与各出口的短路。"""
import os
import unittest
from unittest import mock

import server
from api import ask as ask_module


class LocalOnlyModeTest(unittest.TestCase):
    def test_switch_reads_environment(self):
        with mock.patch.dict(os.environ, {"MEDNEXUS_LOCAL_ONLY": "1"}, clear=False):
            self.assertTrue(server.local_only())
        with mock.patch.dict(os.environ, {"MEDNEXUS_LOCAL_ONLY": "0"}, clear=False):
            self.assertFalse(server.local_only())
        with mock.patch.dict(os.environ, {"MEDNEXUS_LOCAL_ONLY": "yes"}, clear=False):
            self.assertTrue(server.local_only())

    def test_local_mode_has_no_egress(self):
        with mock.patch.dict(os.environ, {"MEDNEXUS_LOCAL_ONLY": "1"}, clear=False):
            mode = server.data_mode()
        self.assertEqual(mode["mode"], "local")
        self.assertEqual(mode["egress"], [])
        self.assertIn("本机", mode["label"])

    def test_cloud_mode_lists_model_and_pubmed(self):
        env = {"MEDNEXUS_LOCAL_ONLY": "0",
               "MEDNEXUS_API_KEY": "test-key",
               "MEDNEXUS_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
               "MEDNEXUS_MODEL": "glm-4-flash"}
        with mock.patch.dict(os.environ, env, clear=False):
            mode = server.data_mode()
        self.assertEqual(mode["mode"], "cloud")
        self.assertIn("open.bigmodel.cn", mode["egress"])
        self.assertIn("eutils.ncbi.nlm.nih.gov", mode["egress"])

    def test_local_mode_blocks_cloud_json(self):
        """有密钥也不许连：本机模式下云端出口必须直接返回 None。"""
        env = {"MEDNEXUS_LOCAL_ONLY": "1", "MEDNEXUS_API_KEY": "test-key"}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(ask_module.tutor_model, "cloud_json") as fake:
                self.assertIsNone(ask_module.cloud_json("system", {"q": "x"}))
                fake.assert_not_called()

    def test_local_mode_blocks_tutor_cloud(self):
        import tutor_model
        env = {"MEDNEXUS_LOCAL_ONLY": "1",
               "MEDNEXUS_API_KEY": "test-key",
               "MEDNEXUS_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
               "MEDNEXUS_MODEL": "glm-4-flash"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertIsNone(tutor_model._cloud_config())

    def test_local_mode_blocks_pubmed(self):
        from api.research import ncbi_get_url
        with mock.patch.dict(os.environ, {"MEDNEXUS_LOCAL_ONLY": "1"}, clear=False):
            with self.assertRaises(server.InputError):
                ncbi_get_url("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed")

    def test_overview_status_carries_data_mode(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(server, "DB_PATH", Path(tmp) / "t.sqlite3"):
                server.init_db()
                with server.connect() as db:
                    learner = "a" * 48
                    payload = server.overview_payload(db, learner)
        self.assertIn("data_mode", payload["status"])
        self.assertIn(payload["status"]["data_mode"]["mode"], ("local", "cloud"))


if __name__ == "__main__":
    unittest.main()