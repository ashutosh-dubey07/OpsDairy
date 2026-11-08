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
            import os
            from pathlib import Path
            from unittest.mock import patch

            from streamlit.testing.v1 import AppTest
            from opsdiary.auth import create_initial_user, reset_password

            database_path = Path(os.environ["OPSDIARY_DATABASE_PATH"])
            with patch("requests.post", side_effect=AssertionError("unexpected provider request")):
                app = AppTest.from_file("app.py").run(timeout=30)
                assert any("create-user" in item.value for item in app.code)

                create_initial_user("operator", "test only passphrase for OpsDiary", database_path)
                app.run(timeout=30)
                assert any(item.key == "login_username" for item in app.text_input)
                app.text_input(key="login_username").set_value("operator")
                app.text_input(key="login_password").set_value("wrong passphrase")
                app.button[0].click()
                app.run(timeout=30)
                assert any("Sign-in failed" in item.value for item in app.error)
                assert app.text_input(key="login_password").value == ""

                app.text_input(key="login_username").set_value("operator")
                app.text_input(key="login_password").set_value("test only passphrase for OpsDiary")
                app.button[0].click()
                app.run(timeout=30)

                assert any(item.key == "app_mode" for item in app.selectbox)
                assert any("Signed in as operator" in item.value for item in app.caption)

                reset_password("operator", "replacement test passphrase for OpsDiary", database_path)
                app.run(timeout=30)
                assert any(item.key == "login_username" for item in app.text_input)
                assert not any(item.key == "app_mode" for item in app.selectbox)
            print("setup, sign-in, and authenticated dashboard passed")
            """
        )

        with TemporaryDirectory() as directory:
            env = os.environ.copy()
            env["OPSDIARY_DATABASE_PATH"] = str(Path(directory) / "app-auth.sqlite3")
            result = subprocess.run(
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
