import io
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from portal_server import Handler, ROOT, resume_response


class ResumePreviewTests(unittest.TestCase):
    def test_pdf_previews_inline_and_downloads_original(self):
        original = b"%PDF-1.4\nexample"
        self.assertEqual(resume_response(original, "cv.pdf", False), (original, "application/pdf", "inline"))
        self.assertEqual(resume_response(original, "cv.pdf", True), (original, "application/octet-stream", "attachment"))

    def test_docx_previews_as_text_and_downloads_original(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>产品经历</w:t></w:r></w:p></w:body></w:document>')
        original = buffer.getvalue()
        preview, content_type, disposition = resume_response(original, "cv.docx", False)
        self.assertIn("产品经历", preview.decode("utf-8"))
        self.assertEqual((content_type, disposition), ("text/plain; charset=utf-8", "inline"))
        self.assertEqual(resume_response(original, "cv.docx", True)[0], original)

    def test_alumni_resume_route_only_downloads_when_requested(self):
        class Client:
            def request(self, method, path):
                return {"record": {"fields": {"简历": [{"name": "cv.pdf", "file_token": "fake"}]}}}

            def authenticate(self):
                pass

            def download_attachment(self, item, path):
                path.write_bytes(b"%PDF-1.4\nexample")

        client = Client()
        real_temporary_directory = tempfile.TemporaryDirectory
        with patch("portal_server.list_recommendations", return_value=[{"id": "local_test"}]), patch("recommendation_store.get", return_value={"candidate_id": "recCandidate01"}), patch("portal_server._client", return_value=(client, "app")), patch("match_engine._record_location", return_value=(None, "table")), patch("portal_server.tempfile.TemporaryDirectory", side_effect=lambda: real_temporary_directory(dir=ROOT)):
            for download in (False, True):
                handler = object.__new__(Handler)
                handler.path = "/api/alumni/recommendation-resume?id=local_test&index=0" + ("&download=1" if download else "")
                handler.wfile = io.BytesIO()
                headers = {}
                handler.send_response = lambda code: None
                handler.send_header = lambda key, value: headers.__setitem__(key, value)
                handler.end_headers = lambda: None
                handler._download_recommendation_resume({"id": "recOwner", "role": "alumni"})
                self.assertEqual(handler.wfile.getvalue(), b"%PDF-1.4\nexample")
                self.assertEqual(headers["Content-Type"], "application/octet-stream" if download else "application/pdf")
                self.assertTrue(headers["Content-Disposition"].startswith("attachment" if download else "inline"))


if __name__ == "__main__":
    unittest.main()
