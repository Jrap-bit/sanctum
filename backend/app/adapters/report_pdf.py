from fpdf import FPDF


def _clean(val) -> str:
    if val is None:
        return ""
    return str(val).encode("latin-1", "replace").decode("latin-1")


class ReportPDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_x(self.l_margin)
        self.set_font("Helvetica", "", 8)
        text = _clean(f"Clinical judgment remains with the authorised practitioner. Page {self.page_no()}")
        self.multi_cell(0, 5, text, new_x="LMARGIN", new_y="NEXT")


def write_line(pdf: FPDF, text: str, line_height: float = 6):
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, line_height, _clean(text), new_x="LMARGIN", new_y="NEXT")


def render(manifest: dict) -> bytes:
    pdf = ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    write_line(pdf, "Sanctum clinical report", line_height=10)

    # Patient name
    pdf.set_font("Helvetica", "B", 13)
    write_line(pdf, manifest.get("patientName", ""), line_height=8)

    # Metadata
    pdf.set_font("Helvetica", "", 10)
    write_line(pdf, f"Coverage: {manifest.get('coverage', '')}", line_height=6)
    write_line(pdf, f"Prepared by {manifest.get('author', '')} on {manifest.get('createdAt', '')}", line_height=6)

    pdf.ln(4)

    # Determine records
    records = manifest.get("records") or manifest.get("included", [])
    sessions = [r for r in records if r.get("kind") == "session"]
    summaries = [r for r in records if r.get("kind") == "summary"]
    indicators = [r for r in records if r.get("kind") == "indicator"]
    excluded = manifest.get("excluded", [])

    # Section: Session records
    if sessions:
        pdf.set_font("Helvetica", "B", 12)
        write_line(pdf, "Session records", line_height=8)
        for s in sessions:
            pdf.set_font("Helvetica", "B", 10)
            date_str = s.get("eventDate") or "Undated"
            title_str = s.get("title") or "Session"
            write_line(pdf, f"{date_str} - {title_str}", line_height=6)
            pdf.set_font("Helvetica", "", 10)
            write_line(pdf, s.get("text", ""), line_height=5)
            pdf.ln(3)

    # Section: Approved summaries
    if summaries:
        pdf.set_font("Helvetica", "B", 12)
        write_line(pdf, "Approved summaries", line_height=8)
        pdf.set_font("Helvetica", "", 10)
        for sm in summaries:
            write_line(pdf, sm.get("text", ""), line_height=5)
            pdf.ln(3)

    # Section: Reviewed indicators
    if indicators:
        pdf.set_font("Helvetica", "B", 12)
        write_line(pdf, "Reviewed indicators", line_height=8)
        for ind in indicators:
            pdf.set_font("Helvetica", "B", 10)
            write_line(pdf, f"{ind.get('name', '')} ({ind.get('reviewState', '')})", line_height=6)
            pdf.set_font("Helvetica", "", 10)
            write_line(pdf, f"Outcome: {ind.get('outcome', '')}", line_height=5)
            write_line(pdf, f"Explanation: {ind.get('explanation', '')}", line_height=5)
            write_line(pdf, f"Rule version {ind.get('ruleVersion', 1)}", line_height=5)
            write_line(pdf, f"Review state: {ind.get('reviewState', '')}", line_height=5)
            pdf.ln(3)

    # Section: Not included
    pdf.set_font("Helvetica", "B", 12)
    write_line(pdf, "Not included", line_height=8)
    pdf.set_font("Helvetica", "", 10)
    if not excluded:
        write_line(pdf, "Nothing was excluded.", line_height=6)
    else:
        for ex in excluded:
            write_line(pdf, f"{ex.get('label')}: {ex.get('reason')}", line_height=5)

    return bytes(pdf.output())
