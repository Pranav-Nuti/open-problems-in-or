"""Phase B: register + admin approve/reject endpoints."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException


class AuthRegisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        root = Path(cls._tmpdir.name)
        os.environ["DATA_DIR"] = str(root / "data")
        os.environ["UPLOAD_DIR"] = str(root / "data" / "uploads")
        os.environ["SESSION_SECRET"] = "test-session-secret-for-register"
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
        cls.admin = cls.db_mod.get_user_by_username("pete")
        assert cls.admin is not None

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_register_pending_then_approve_login(self) -> None:
        created = self.main.register(
            self.main.RegisterRequest(
                username="newcomer",
                email="newcomer@example.com",
                password="password123",
            )
        )
        self.assertEqual(created["user"]["status"], "pending")
        self.assertNotIn("token", created)

        with self.assertRaises(HTTPException) as login_ctx:
            self.main.login(
                self.main.LoginRequest(username="newcomer", password="password123")
            )
        self.assertEqual(login_ctx.exception.status_code, 403)

        pending = self.main.list_pending_users(admin=dict(self.admin))
        names = {u["username"] for u in pending["items"]}
        self.assertIn("newcomer", names)

        user_id = int(created["user"]["id"])
        approved = self.main.approve_pending_user(user_id=user_id, admin=dict(self.admin))
        self.assertEqual(approved["user"]["status"], "approved")

        logged_in = self.main.login(
            self.main.LoginRequest(username="newcomer", password="password123")
        )
        self.assertIn("token", logged_in)
        self.assertEqual(logged_in["user"]["role"], "uploader")

    def test_register_duplicate_username_and_email(self) -> None:
        self.main.register(
            self.main.RegisterRequest(
                username="dupuser",
                email="dup@example.com",
                password="password123",
            )
        )
        with self.assertRaises(HTTPException) as ctx_user:
            self.main.register(
                self.main.RegisterRequest(
                    username="dupuser",
                    email="other@example.com",
                    password="password123",
                )
            )
        self.assertEqual(ctx_user.exception.status_code, 409)

        with self.assertRaises(HTTPException) as ctx_email:
            self.main.register(
                self.main.RegisterRequest(
                    username="otheruser",
                    email="DUP@example.com",
                    password="password123",
                )
            )
        self.assertEqual(ctx_email.exception.status_code, 409)

    def test_reject_pending(self) -> None:
        created = self.main.register(
            self.main.RegisterRequest(
                username="nope",
                email="nope@example.com",
                password="password123",
            )
        )
        user_id = int(created["user"]["id"])
        rejected = self.main.reject_pending_user(user_id=user_id, admin=dict(self.admin))
        self.assertEqual(rejected["user"]["status"], "rejected")

        with self.assertRaises(HTTPException) as ctx:
            self.main.approve_pending_user(user_id=user_id, admin=dict(self.admin))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_non_admin_cannot_list_pending(self) -> None:
        uploader = self.db_mod.create_user(
            username="plain",
            password_hash=self.auth.hash_password("password123"),
            role="uploader",
            email="plain@example.com",
            status="approved",
        )
        import asyncio

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(self.auth.require_admin(user=dict(uploader)))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_invalid_register_payload(self) -> None:
        with self.assertRaises(HTTPException) as bad_email:
            self.main.register(
                self.main.RegisterRequest(
                    username="validname",
                    email="not-an-email",
                    password="password123",
                )
            )
        self.assertEqual(bad_email.exception.status_code, 400)

        with self.assertRaises(HTTPException) as bad_user:
            self.main.register(
                self.main.RegisterRequest(
                    username="bad user!",
                    email="ok@example.com",
                    password="password123",
                )
            )
        self.assertEqual(bad_user.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
