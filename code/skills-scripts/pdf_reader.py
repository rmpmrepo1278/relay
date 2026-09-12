import pypdf
import os

def extract_pdf_text(file_path: str) -> str:
    """Extracts raw text from a PDF file for analysis."""
    if not os.path.exists(file_path):
        return f"Error: File {file_path} not found."
    try:
        reader = pypdf.PdfReader(file_path)
        text = f"--- PDF Content: {os.path.basename(file_path)} ---\n"
        for i, page in enumerate(reader.pages):
            text += f"\n[Page {i+1}]\n" + page.extract_text()
        return text[:10000] # Cap to 10k chars for LLM context
    except Exception as e:
        return f"Error reading PDF: {str(e)}"
