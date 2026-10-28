#!/usr/bin/env python3
"""Create an original, redistributable two-page PDF for retrieval verification."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUTPUT = Path(__file__).resolve().parents[1] / "sample-data/papers/sample-pdf-eqa.pdf"
PAGES = [
    (
        "01 / Frame buffer baseline",
        "FRAMEBUFFER2026",
        [
            "A frame buffer stores recent observations for embodied question answering.",
            "The example baseline retains raw features from a fixed number of frames.",
            "Longer sequences increase memory usage and introduce irrelevant evidence.",
            "This document defines test inputs only. It reports no measured accuracy.",
        ],
    ),
    (
        "02 / Room identity constraint",
        "ROOMMERGE2026",
        [
            "A room identity constraint prevents merging objects across different rooms.",
            "Multiple views of the same object are aggregated before matching candidates.",
            "The planned evaluation compares object duplication and peak memory usage.",
            "This is an original fictional research note, not a published paper or result.",
        ],
    ),
]


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, invariant=1)
    pdf.setTitle("LabTrace original EQA PDF fixture - example data")
    pdf.setAuthor("LabTrace sample data")
    width, height = A4
    for number, (title, marker, paragraphs) in enumerate(PAGES, 1):
        pdf.setFillColor(colors.HexColor("#10182a"))
        pdf.rect(0, height - 155, width, 155, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#b6c5ff"))
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(48, height - 49, "LABTRACE / ORIGINAL TEST DOCUMENT")
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 21)
        pdf.drawString(48, height - 91, title)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(
            48, height - 121, "Example data - freely redistributable under CC0-1.0"
        )
        pdf.setFillColor(colors.HexColor("#344363"))
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(48, height - 202, "Retrieval marker: " + marker)
        pdf.setFont("Helvetica", 11)
        for index, paragraph in enumerate(paragraphs):
            pdf.drawString(48, height - 250 - index * 43, paragraph)
        pdf.setStrokeColor(colors.HexColor("#dce2ec"))
        pdf.line(48, 75, width - 48, 75)
        pdf.setFillColor(colors.HexColor("#67758f"))
        pdf.setFont("Helvetica", 9)
        pdf.drawString(
            48,
            54,
            "No real participants, experiments, or scientific results are represented.",
        )
        pdf.drawRightString(width - 48, 34, f"{number} / 2")
        pdf.showPage()
    pdf.save()
    print(OUTPUT)


if __name__ == "__main__":
    main()
