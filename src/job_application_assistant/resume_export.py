"""Export approved resume text to verified DOCX and PDF documents."""

import argparse
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4
from xml.sax.saxutils import escape

import reportlab
from docx import Document
from docx.shared import Inches, Pt
from dotenv import dotenv_values
from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from job_application_assistant.job_requirements_storage import (
    load_requirements,
)
from job_application_assistant.profile_match_service import (
    load_saved_profile,
)
from job_application_assistant.resume_draft import ROOT
from job_application_assistant.resume_review import verify_approval


HEADINGS = {"EXPERIENCE", "EDUCATION"}


def normalized_text(text):
    """Ignore layout whitespace while preserving word order."""
    return " ".join(text.split())


def render_documents(text):
    """Build both formats and verify their extracted content."""
    if not text.strip():
        raise ValueError("Cannot export an empty resume.")

    lines = text.splitlines()
    name = lines[0]
    document = Document()
    document.core_properties.author = name
    document.core_properties.title = "Resume"
    document.core_properties.comments = ""

    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)

    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(4)

    for index, line in enumerate(lines):
        paragraph = document.add_paragraph(line)
        if index == 0 or line in HEADINGS:
            paragraph.paragraph_format.keep_with_next = True
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(16 if index == 0 else 11.5)

    docx_buffer = BytesIO()
    document.save(docx_buffer)
    docx_bytes = docx_buffer.getvalue()

    # Embed the font supplied with ReportLab.
    font_directory = Path(reportlab.__file__).parent / "fonts"
    font_name = "ResumeVera"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(
            TTFont(font_name, str(font_directory / "Vera.ttf"))
        )
    font = pdfmetrics.getFont(font_name)
    unsupported = {
        character
        for character in text
        if not character.isspace()
        and ord(character) not in font.face.charToGlyph
    }
    if unsupported:
        raise ValueError(
            "PDF font lacks these characters: "
            + repr("".join(sorted(unsupported)))
        )

    body = ParagraphStyle(
        "ResumeBody",
        fontName=font_name,
        fontSize=10.5,
        leading=14,
        spaceAfter=4,
    )
    title = ParagraphStyle(
        "ResumeTitle",
        parent=body,
        fontSize=16,
        leading=20,
        keepWithNext=True,
    )
    heading = ParagraphStyle(
        "ResumeHeading",
        parent=body,
        fontSize=11.5,
        leading=16,
        keepWithNext=True,
    )

    flowables = []
    for index, line in enumerate(lines):
        if not line.strip():
            flowables.append(Spacer(1, 5))
            continue
        style = title if index == 0 else (
            heading if line in HEADINGS else body
        )
        flowables.append(Paragraph(escape(line), style))

    pdf_buffer = BytesIO()
    SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        topMargin=0.65 * 72,
        bottomMargin=0.65 * 72,
        leftMargin=0.7 * 72,
        rightMargin=0.7 * 72,
        title="Resume",
        author=name,
    ).build(flowables)
    pdf_bytes = pdf_buffer.getvalue()

    extracted_docx = "\n".join(
        paragraph.text
        for paragraph in Document(BytesIO(docx_bytes)).paragraphs
    )
    extracted_pdf = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(BytesIO(pdf_bytes)).pages
    )
    expected = normalized_text(text)
    if normalized_text(extracted_docx) != expected:
        raise ValueError("DOCX text or reading-order verification failed.")
    if normalized_text(extracted_pdf) != expected:
        raise ValueError("PDF text or reading-order verification failed.")

    return {"resume.docx": docx_bytes, "resume.pdf": pdf_bytes}


def export_approved_resume(directory, profile, requirements):
    """Create a new export bundle only from a valid approved draft."""
    directory = Path(directory)
    text = verify_approval(directory, profile, requirements)
    documents = render_documents(text)

    # Detect file edits made while rendering.
    if verify_approval(directory, profile, requirements) != text:
        raise ValueError("The approved draft changed during export.")

    output = directory / "exports" / str(uuid4())
    output.mkdir(parents=True, exist_ok=False)
    for filename, content in documents.items():
        (output / filename).write_bytes(content)

    receipt = {
        "status": "exported",
        "resume_text_sha256": sha256(
            text.encode("utf-8")
        ).hexdigest(),
        "text_and_order_verified": True,
        "files": {
            filename: sha256(content).hexdigest()
            for filename, content in documents.items()
        },
    }
    (output / "export.json").write_text(
        json.dumps(receipt, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def main():
    """Load current sources and export the approved resume locally."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()

    settings = dotenv_values(ROOT / ".env")
    configured = (
        settings.get("CAREER_PROFILE_PATH")
        or "data/private/profile/career_profile.md"
    ).strip()
    profile_path = (ROOT / configured).resolve()
    manifest = json.loads(
        (args.directory / "evidence.json").read_text(encoding="utf-8")
    )
    database = ROOT / "data/private/job_captures.sqlite"
    capture_uuid = UUID(manifest["capture_uuid"])

    profile = load_saved_profile(profile_path)
    requirements = load_requirements(database, capture_uuid)
    if requirements is None:
        raise ValueError("Saved job requirements are unavailable.")

    output = export_approved_resume(
        args.directory, profile, requirements
    )

    # Recheck current disk sources before reporting success.
    current_profile = load_saved_profile(profile_path)
    current_requirements = load_requirements(database, capture_uuid)
    try:
        if current_requirements is None:
            raise ValueError("Job requirements became unavailable.")
        verify_approval(
            args.directory, current_profile, current_requirements
        )
    except (ValueError, OSError):
        for path in output.iterdir():
            path.unlink()
        output.rmdir()
        raise

    print(f"Verified DOCX: {output / 'resume.docx'}")
    print(f"Verified PDF: {output / 'resume.pdf'}")
    print("Open both files for visual review before use.")


if __name__ == "__main__":
    main()