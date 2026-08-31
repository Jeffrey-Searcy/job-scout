"""
Turn a tailored resume's structured text into a clean, ATS-safe Word document.

Why a .docx (not a PDF): the user tweaks the wording before submitting, and a
Word file is far easier to edit than a PDF. They "Save as PDF" from Word/Google
Docs right before uploading to an application. Why build it here in the backend
(not on the host worker): python-docx and the media volume both live inside the
backend container, and this keeps file-building in one place — the same place the
resume PDFs already live.

ATS-safety is the whole point of the layout choices below:
  - No tables, columns, images, or text boxes. Applicant tracking systems (the
    software that scans and ranks resumes before a human sees them) parse those
    badly. Everything is plain top-to-bottom headings and paragraphs.
  - Real selectable text in a standard font, so a scanner reads words, not shapes.
  - Simple, named section headings the scanner recognizes (Summary, Experience...).

The input is the structured dict the tailoring worker produces (see
agent_worker.py build_prompt for the 'tailor' task). We do NOT invent content
here — we only lay out exactly the text the worker returned.
"""
from io import BytesIO

from docx import Document
from docx.shared import Pt


def build_tailored_docx(data: dict) -> bytes:
    """Render a tailored-resume dict into .docx bytes.

    ``data`` is the JSON the worker posts back, shape:
        {
          "name": str,                      # candidate name for the header
          "contact": str,                   # one line: email · phone · location · links
          "summary": str,                   # tailored professional summary paragraph
          "skills": [str, ...],             # skills list, already keyword-matched
          "experience": [                   # newest first
            {"header": str, "bullets": [str, ...]}, ...
          ],
          "education": [str, ...],          # each a line
          "extra": [                        # optional extra sections, in order
            {"heading": str, "lines": [str, ...]}, ...
          ],
        }

    Returns the .docx file as raw bytes, ready to save to the FileField. Raises
    KeyError/TypeError loudly if the worker sent a malformed shape — we do NOT
    paper over missing sections with blanks, because a silently empty resume is
    worse than a clear failure the user can see and re-run.
    """
    doc = Document()

    # Base body font: a common, ATS-friendly serif at a normal reading size.
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    # --- Header: name (large) + contact line ---
    name = (data["name"] or "").strip()
    if not name:
        # A resume with no name is not usable; fail loudly rather than ship a
        # nameless file the user would only discover after submitting it.
        raise ValueError("tailored resume has no name")
    name_p = doc.add_paragraph()
    name_run = name_p.add_run(name)
    name_run.bold = True
    name_run.font.size = Pt(20)

    contact = (data.get("contact") or "").strip()
    if contact:
        c_p = doc.add_paragraph()
        c_run = c_p.add_run(contact)
        c_run.font.size = Pt(10)

    def _section_heading(text):
        """Add a bold, slightly larger section heading (no fancy styling)."""
        h = doc.add_paragraph()
        run = h.add_run(text.upper())
        run.bold = True
        run.font.size = Pt(12)

    # --- Summary ---
    summary = (data.get("summary") or "").strip()
    if summary:
        _section_heading("Summary")
        doc.add_paragraph(summary)

    # --- Skills (comma-joined single paragraph — scanners read this cleanly) ---
    skills = [s.strip() for s in data.get("skills", []) if s and s.strip()]
    if skills:
        _section_heading("Skills")
        doc.add_paragraph(", ".join(skills))

    # --- Experience: each job a header line + bullet points ---
    experience = data.get("experience", [])
    if experience:
        _section_heading("Experience")
        for job in experience:
            head = (job.get("header") or "").strip()
            if head:
                hp = doc.add_paragraph()
                hp.add_run(head).bold = True
            for bullet in job.get("bullets", []):
                b = (bullet or "").strip()
                if b:
                    # "List Bullet" is a built-in style — real bullets, no manual
                    # dashes that a scanner might mistake for hyphenated words.
                    doc.add_paragraph(b, style="List Bullet")

    # --- Education ---
    education = [e.strip() for e in data.get("education", []) if e and e.strip()]
    if education:
        _section_heading("Education")
        for line in education:
            doc.add_paragraph(line)

    # --- Optional extra sections (certifications, projects, etc.) ---
    for section in data.get("extra", []):
        heading = (section.get("heading") or "").strip()
        lines = [ln.strip() for ln in section.get("lines", []) if ln and ln.strip()]
        if heading and lines:
            _section_heading(heading)
            for line in lines:
                doc.add_paragraph(line)

    # Serialize to bytes so the caller can hand it straight to a FileField.
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
