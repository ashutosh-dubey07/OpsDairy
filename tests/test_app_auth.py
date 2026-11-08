import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AuthenticationGateUITests(unittest.TestCase):
    def test_setup_login_and_authenticated_dashboard_without_provider_requests(self) -> None:
        child_script = textwrap.dedent(
            """
            from unittest.mock import patch

            from opsdiary import settings
            from streamlit.testing.v1 import AppTest
            from opsdiary.storage import list_assistant_interactions
            settings.GNANI_API_KEY = ""
            with patch("requests.post", side_effect=AssertionError("unexpected provider request")):
                app = AppTest.from_file("app.py").run(timeout=30)
                assert any(item.key == "registration_username" for item in app.text_input)

                app.text_input(key="registration_username").set_value("operator")
                app.text_input(key="registration_password").set_value("test only passphrase for OpsDiary")
                app.text_input(key="registration_password_confirm").set_value("different passphrase")
                app.button(key="registration_submit").click()
                app.run(timeout=30)
                assert any("do not match" in item.value for item in app.error)

                app.text_input(key="registration_password").set_value("test only passphrase for OpsDiary")
                app.text_input(key="registration_password_confirm").set_value("test only passphrase for OpsDiary")
                app.button(key="registration_submit").click()
                app.run(timeout=30)
                assert any(item.key == "login_username" for item in app.text_input)
                assert len(app.code) > 0, "registration recovery code was not rendered"
                recovery_code = app.code[0].value
                assert len(recovery_code) >= 40, "rendered recovery code was unexpectedly short"
                app.run(timeout=30)
                assert all(recovery_code not in item.value for item in app.code)

                app.text_input(key="login_username").set_value("operator")
                app.text_input(key="login_password").set_value("wrong passphrase")
                app.button(key="login_submit").click()
                app.run(timeout=30)
                assert any("Sign-in failed" in item.value for item in app.error)
                assert app.text_input(key="login_password").value == ""

                app.text_input(key="login_username").set_value("operator")
                app.text_input(key="login_password").set_value("test only passphrase for OpsDiary")
                app.button(key="login_submit").click()
                app.run(timeout=30)

                mode_select = next(item for item in app.selectbox if item.key == "app_mode")
                assert mode_select.options == ["Demo"]
                assert any("Signed in as operator" in item.value for item in app.caption)
                app.chat_input(key="assistant_query_input").set_value("hii")
                app.run(timeout=30)
                saved_queries = list_assistant_interactions("operator")
                assert saved_queries[0]["query"] == "hii"
                assert saved_queries[0]["intent"] == "greeting"
                assert saved_queries[0]["source"] == "local-faq"

                app.button(key="auth_sign_out").click()
                app.run(timeout=30)
                assert any(item.key == "login_username" for item in app.text_input)
                app.text_input(key="recovery_username").set_value("operator")
                app.text_input(key="recovery_code").set_value(recovery_code)
                app.text_input(key="recovery_password").set_value("new passphrase from recovery flow")
                app.text_input(key="recovery_password_confirm").set_value("new passphrase from recovery flow")
                app.button(key="recovery_submit").click()
                app.run(timeout=30)
                rotated_recovery_code = app.code[0].value
                assert len(rotated_recovery_code) >= 40
                app.run(timeout=30)
                assert all(rotated_recovery_code not in item.value for item in app.code)
                app.text_input(key="login_username").set_value("operator")
                app.text_input(key="login_password").set_value("new passphrase from recovery flow")
                app.button(key="login_submit").click()
                app.run(timeout=30)
                assert any(item.key == "app_mode" for item in app.selectbox)
            print("setup, sign-in, and authenticated dashboard passed")
            """
        )

        with TemporaryDirectory() as directory:
            env = os.environ.copy()
            env["OPSDIARY_DATABASE_PATH"] = str(Path(directory) / "app-auth.sqlite3")
            result = subprocess.run(  # noqa: S603 -- Fixed test script and trusted interpreter path.
                [sys.executable, "-c", child_script],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertIn("setup, sign-in, and authenticated dashboard passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
