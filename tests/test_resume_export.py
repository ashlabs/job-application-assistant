"""Check exported content, pagination, and approval enforcement."""

from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document
from pypdf import PdfReader

from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.models import CareerProfile
from job_application_assistant.resume_export import (
    export_approved_resume,
    normalized_text,
    render_documents,
)


@pytest.mark.parametrize("repetitions", [1, 100])
def test_documents_preserve_text_and_order(repetitions):
    text = (
        "Example Candidate\n\nEXPERIENCE\n\n"
        "Engineering Manager | Example Company\n"
        "2018-01 – 2022-12\n"
        + "- Coached engineers & reviewed delivery <weekly>.\n"
        * repetitions
        + "\nEDUCATION\n\n"
        "Master of Science | Artificial Intelligence | In progress\n"
    )
    documents = render_documents(text)

    docx_text = "\n".join(
        paragraph.text
        for paragraph in Document(
            BytesIO(documents["resume.docx"])
        ).paragraphs
    )
    pdf = PdfReader(BytesIO(documents["resume.pdf"]))
    pdf_text = "\n".join(
        page.extract_text() or "" for page in pdf.pages
    )

    assert normalized_text(docx_text) == normalized_text(text)
    assert normalized_text(pdf_text) == normalized_text(text)
    if repetitions == 100:
        assert len(pdf.pages) > 1


def test_export_rejects_unapproved_draft(tmp_path, monkeypatch):
    import job_application_assistant.resume_export as module

    def reject(*args):
        raise ValueError("This resume has not been approved.")

    monkeypatch.setattr(module, "verify_approval", reject)
    requirements = JobRequirements(
        capture_uuid=uuid4(), jd_text_sha256="a" * 64
    )
    with pytest.raises(ValueError, match="not been approved"):
        export_approved_resume(
            tmp_path, CareerProfile(), requirements
        )
    assert not (tmp_path / "exports").exists()


def test_unsupported_pdf_characters_are_rejected():
    with pytest.raises(ValueError, match="font lacks"):
        render_documents("Example Candidate\nUnsupported: 😀\n")