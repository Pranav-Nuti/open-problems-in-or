"""Phase A: user email/status columns and approval-gated login."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException


class UserStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        root = Path(cls._tmpdir.name)
        os.environ["DATA_DIR"] = str(root / "data")
        os.environ["UPLOAD_DIR"] = str(root / "data" / "uploads")
        os.environ["SESSION_SECRET"] = "test-session-secret-for-user-status"
        os.environ["UPLOAD_SEED_USERNAME"] = "pete"
        os.environ["UPLOAD_SEED_PASSWORD"] = "westbrook"
        os.environ["WORKER_API_TOKEN"] = "test-worker-token"
        os.environ["CORS_ORIGINS"] = "http://test"
        os.environ["HOST"] = "127.0.0.1"
        os.environ["RELOAD"] = "0"

        from importlib import reload

        from app import auth
        from app import config
        from app import db as db_mod
        from app import main

        reload(config)
        reload(db_mod)
        reload(auth)
        reload(main)

        cls.db_mod = db_mod
        cls.auth = auth
        cls.main = main
        cls.db_mod.init_db()
        cls.auth.seed_admin_user_if_needed()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_seed_admin_is_approved(self) -> None:
        admin = self.db_mod.get_user_by_username("pete")
        assert admin is not None
        self.assertEqual(admin["status"], "approved")
        self.assertTrue(self.auth.user_is_approved(admin))
        public = self.auth.public_user(admin)
        self.assertEqual(public["status"], "approved")
        self.assertIn("email", public)

    def test_pending_user_cannot_login(self) -> None:
        pending = self.db_mod.create_user(
            username="pending_user",
            password_hash=self.auth.hash_password("secret123"),
            role="uploader",
            email="pending@example.com",
            status="pending",
        )
        self.assertEqual(pending["status"], "pending")
        self.assertIsNone(pending.get("approved_at"))

        with self.assertRaises(HTTPException) as ctx:
            self.main.login(
                self.main.LoginRequest(username="pending_user", password="secret123")
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("pending", str(ctx.exception.detail).lower())

    def test_approve_then_login(self) -> None:
        user = self.db_mod.create_user(
            username="to_approve",
            password_hash=self.auth.hash_password("secret123"),
            role="uploader",
            email="approve_me@example.com",
            status="pending",
        )
        admin = self.db_mod.get_user_by_username("pete")
        assert admin is not None
        updated = self.db_mod.set_user_status(
            user_id=int(user["id"]),
            status="approved",
            approved_by=int(admin["id"]),
        )
        assert updated is not None
        self.assertEqual(updated["status"], "approved")
        self.assertIsNotNone(updated.get("approved_at"))

        body = self.main.login(
            self.main.LoginRequest(username="to_approve", password="secret123")
        )
        self.assertIn("token", body)
        self.assertEqual(body["user"]["status"], "approved")

    def test_rejected_user_blocked(self) -> None:
        user = self.db_mod.create_user(
            username="rejected_user",
            password_hash=self.auth.hash_password("secret123"),
            role="uploader",
            email="rejected@example.com",
            status="rejected",
        )
        with self.assertRaises(HTTPException) as ctx:
            self.auth.assert_user_approved(user)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_list_pending_and_email_lookup(self) -> None:
        self.db_mod.create_user(
            username="wait1",
            password_hash=self.auth.hash_password("x"),
            role="uploader",
            email="wait1@example.com",
            status="pending",
        )
        found = self.db_mod.get_user_by_email("WAIT1@example.com")
        assert found is not None
        self.assertEqual(found["username"], "wait1")
        pending = self.db_mod.list_users_by_status("pending")
        names = {u["username"] for u in pending}
        self.assertIn("wait1", names)


if __name__ == "__main__":
    unittest.main()
