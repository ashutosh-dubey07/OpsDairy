import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AuthenticationGateUITests(unittest.TestCase):
    def test_sign_in_and_authenticated_dashboard_without_provider_requests(self) -> None:
        child_script = textwrap.dedent(
            """
            from unittest.mock import patch
            import time

            from opsdiary import auth
            from opsdiary import settings
            from streamlit.testing.v1 import AppTest
            from opsdiary.storage import init_db, list_assistant_interactions
            settings.GNANI_API_KEY = ""
            init_db()
            with patch("requests.post", side_effect=AssertionError("unexpected provider request")):
                app = AppTest.from_file("app.py")
                app.run(timeout=30)
                assert not app.exception, [item.message for item in app.exception]
                assert any("Create local account" in item.value for item in app.subheader)

                auth.create_initial_user("operator", "TestOnlyPass8!")
                app.run(timeout=30)
                assert not app.exception, [item.message for item in app.exception]
                assert any("Sign in" in item.value for item in app.subheader)

                now = time.monotonic()
                app.session_state["auth_username"] = "operator"
                app.session_state["auth_version"] = auth.get_auth_version("operator")
                app.session_state["auth_created_at"] = now
                app.session_state["auth_last_seen"] = now
                app.run(timeout=30)

                assert any("Signed in as operator" in item.value for item in app.caption)
                assert any("Set GNANI_API_KEY" in item.value for item in app.error)
                assert not any(item.label == "Mode" for item in app.selectbox)
                app.chat_input(key="assistant_query_input").set_value("hii")
                app.run(timeout=30)
                saved_queries = list_assistant_interactions("operator")
                assert saved_queries[0]["query"] == "hii"
                assert saved_queries[0]["intent"] == "greeting"
                assert saved_queries[0]["source"] == "local-faq"

                app.button(key="auth_sign_out").click()
                app.run(timeout=30)
                assert app.session_state["auth_notice"] == "You have been signed out."
            print("sign-in and authenticated dashboard passed")
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
        self.assertIn("sign-in and authenticated dashboard passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
