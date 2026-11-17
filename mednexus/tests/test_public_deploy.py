"""云端托管模式的配置契约。

守住两条边界：
  · 本机默认不设置 MEDNEXUS_PUBLIC：同源校验与 CSP 与从前完全一致（self only）；
  · 显式开启托管模式后：CSP 放行云 SDK 的 CDN 与公开配置里的云服务端点。
不启动真实服务，纯函数级断言，避免与端口/文件锁纠缠。
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
from api import routing


class PublicDeployTests(unittest.TestCase):
    def test_local_default_is_strict(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(routing.public_deploy())
            csp = routing.content_security_policy()
            self.assertIn("script-src 'self';", csp)
            self.assertIn("connect-src 'self';", csp)
            self.assertNotIn("cdn.jsdelivr.net", csp)
            self.assertNotIn("workbuddy.host", csp)

    def test_public_flag_enables_hosted_mode(self):
        with patch.dict(os.environ, {"MEDNEXUS_PUBLIC": "1"}, clear=True):
            self.assertTrue(routing.public_deploy())

    def test_hosted_csp_allows_sdk_cdn(self):
        with patch.dict(os.environ, {"MEDNEXUS_PUBLIC": "1"}, clear=True):
            csp = routing.content_security_policy()
        self.assertIn("https://cdn.jsdelivr.net", csp)
        self.assertIn("script-src", csp)

    def test_hosted_csp_allows_cloud_endpoints_from_config(self):
        with patch.dict(os.environ, {"MEDNEXUS_PUBLIC": "1"}, clear=True):
            csp = routing.content_security_policy()
        for origin in routing.cloud_connect_origins():
            self.assertIn(origin, csp)

    def test_hosted_csp_keeps_hard_deny_directives(self):
        with patch.dict(os.environ, {"MEDNEXUS_PUBLIC": "1"}, clear=True):
            csp = routing.content_security_policy()
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_allowed_uses_public_gate(self):
        # 用轻量假对象触发 Handler.allowed：托管模式应直接放行，本机模式走原校验。
        class FakeHandler(routing.Handler):
            def __init__(self):
                class Server:
                    server_port = 7860
                    server_address = ("0.0.0.0", 7860)
                self.server = Server()
                self.headers = {"Host": "mednexus.app.workbuddy.host",
                                "Origin": "https://mednexus.app.workbuddy.host"}

        with patch.dict(os.environ, {"MEDNEXUS_PUBLIC": "1"}, clear=True):
            self.assertTrue(FakeHandler().allowed())
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(FakeHandler().allowed())


if __name__ == "__main__":
    unittest.main()
