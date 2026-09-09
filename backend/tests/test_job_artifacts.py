"""Local tests for multi-artifact job results (no Railway / httpx required)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _pdf_upload(name: str = "paper.pdf") -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(_minimal_pdf_bytes()))


class JobArtifactsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        root = Path(cls._tmpdir.name)
        os.environ["DATA_DIR"] = str(root / "data")
        os.environ["UPLOAD_DIR"] = str(root / "data" / "uploads")
        os.environ["SESSION_SECRET"] = "test-session-secret-for-artifacts"
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
        cls.worker = {"is_worker": True, "id": 0, "username": "worker", "role": "worker"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def _source_and_running_job(self) -> tuple[int, int]:
        user = self.db_mod.get_user_by_username("pete")
        assert user is not None
        src = self.db_mod.insert_upload(
            user_id=int(user["id"]),
            filename="paper.pdf",
            stored_name=f"{os.urandom(4).hex()}_paper.pdf",
            content_type="application/pdf",
            size_bytes=12,
            sha256="a" * 64,
            kind="source",
        )
        Path(self.db_mod.storage_path(src["stored_name"])).write_bytes(_minimal_pdf_bytes())
        job = self.db_mod.create_job(upload_id=int(src["id"]), kind="extract")
        claimed = self.db_mod.claim_next_job(kind="extract")
        assert claimed is not None
        return int(src["id"]), int(job["id"])

    def test_extract_finalize_default_marks_done(self) -> None:
        _src_id, job_id = self._source_and_running_job()
        body = asyncio.run(
            self.main.upload_job_result(
                job_id=job_id,
                file=_pdf_upload("extracted_paper.pdf"),
                artifact_kind="extraction",
                finalize=True,
                worker=self.worker,
            )
        )
        self.assertTrue(body["finalized"])
        self.assertEqual(body["job"]["status"], "done")
        self.assertEqual(len(body["job"]["artifacts"]), 1)
        self.assertEqual(body["upload"]["kind"], "extraction")
        self.assertEqual(body["artifact"]["artifact_kind"], "extraction")

    def test_multi_artifact_without_finalize_keeps_running(self) -> None:
        src_id, job_id = self._source_and_running_job()

        first = asyncio.run(
            self.main.upload_job_result(
                job_id=job_id,
                file=_pdf_upload("extracted.pdf"),
                artifact_kind="extraction",
                finalize=False,
                worker=self.worker,
            )
        )
        self.assertFalse(first["finalized"])
        self.assertEqual(first["job"]["status"], "running")
        self.assertEqual(len(first["job"]["artifacts"]), 1)

        second = asyncio.run(
            self.main.upload_job_result(
                job_id=job_id,
                file=_pdf_upload("lit_review.pdf"),
                artifact_kind="literature_review",
                finalize=False,
                worker=self.worker,
            )
        )
        self.assertEqual(second["job"]["status"], "running")
        self.assertEqual(len(second["job"]["artifacts"]), 2)

        third = asyncio.run(
            self.main.upload_job_result(
                job_id=job_id,
                file=_pdf_upload("solver.pdf"),
                artifact_kind="solver_verified",
                finalize=True,
                worker=self.worker,
            )
        )
        self.assertTrue(third["finalized"])
        self.assertEqual(third["job"]["status"], "done")
        kinds = [a["artifact_kind"] for a in third["job"]["artifacts"]]
        self.assertEqual(kinds, ["extraction", "literature_review", "solver_verified"])

        user = self.db_mod.get_user_by_username("pete")
        items = self.db_mod.list_uploads_for_user(int(user["id"]), limit=50)
        by_kind = {}
        for item in items:
            if int(item.get("parent_upload_id") or 0) == src_id or int(item["id"]) == src_id:
                by_kind[item["kind"]] = item
        self.assertIn("source", by_kind)
        self.assertIn("extraction", by_kind)
        self.assertIn("literature_review", by_kind)
        self.assertIn("solver_verified", by_kind)
        self.assertEqual(by_kind["solver_verified"]["status"], "verified")

    def test_solver_partial_and_legacy_attempt_kinds(self) -> None:
        _src_id, job_id = self._source_and_running_job()
        body = asyncio.run(
            self.main.upload_job_result(
                job_id=job_id,
                file=_pdf_upload("attempt.pdf"),
                artifact_kind="solver_partial",
                finalize=True,
                worker=self.worker,
            )
        )
        self.assertEqual(body["upload"]["kind"], "solver_partial")
        self.assertEqual(body["upload"]["status"], "partial")

        _src2, job2 = self._source_and_running_job()
        legacy = asyncio.run(
            self.main.upload_job_result(
                job_id=job2,
                file=_pdf_upload("legacy.pdf"),
                artifact_kind="solver_attempt",
                finalize=True,
                worker=self.worker,
            )
        )
        self.assertEqual(legacy["upload"]["kind"], "solver_attempt")
        self.assertEqual(legacy["upload"]["status"], "partial")

    def test_invalid_artifact_kind_rejected(self) -> None:
        from fastapi import HTTPException

        _src_id, job_id = self._source_and_running_job()
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                self.main.upload_job_result(
                    job_id=job_id,
                    file=_pdf_upload("x.pdf"),
                    artifact_kind="nope",
                    finalize=False,
                    worker=self.worker,
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_cancel_and_reap_stale(self) -> None:
        from fastapi import HTTPException

        _src_id, job_id = self._source_and_running_job()
        user = self.db_mod.get_user_by_username("pete")
        assert user is not None
        cancelled = self.main.cancel_job(job_id=job_id, user=dict(user))
        self.assertEqual(cancelled["status"], "failed")
        self.assertIn("Cancelled", cancelled.get("error_message") or "")

        with self.assertRaises(HTTPException) as ctx:
            self.main.cancel_job(job_id=job_id, user=dict(user))
        self.assertEqual(ctx.exception.status_code, 409)

        _src2, job2 = self._source_and_running_job()
        reaped = self.main.reap_stale_jobs(worker=self.worker)
        self.assertEqual(reaped["count"], 1)
        self.assertEqual(reaped["reaped_job_ids"], [job2])
        row = self.db_mod.get_job_by_id(job2)
        assert row is not None
        self.assertEqual(row["status"], "failed")
        # no-op when nothing running
        again = self.main.reap_stale_jobs(worker=self.worker)
        self.assertEqual(again["count"], 0)

    def test_fail_job_flips_active_stage_pills(self) -> None:
        _src_id, job_id = self._source_and_running_job()
        self.db_mod.update_job_stages(
            job_id=job_id,
            stages={"extraction": "done", "literature_review": "done", "solver": "running"},
        )
        failed = self.main.fail_job(
            job_id=job_id,
            body={"error_message": "boom"},
            worker=self.worker,
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(
            failed["stages"],
            {"extraction": "done", "literature_review": "done", "solver": "failed"},
        )


if __name__ == "__main__":
    unittest.main()
