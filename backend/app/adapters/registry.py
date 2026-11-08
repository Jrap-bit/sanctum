"""Factories that build an adapter from its configured name, importing only what is selected."""
from importlib import import_module

from ..core.exceptions import AdapterConfigurationError


class Registry:
    def __init__(self, kind, implementations):
        self.kind = kind
        self.implementations = implementations

    def names(self):
        return sorted(self.implementations)

    def create(self, name, **options):
        try:
            module, attribute = self.implementations[name].split(":")
        except KeyError:
            raise AdapterConfigurationError(f"Unknown {self.kind} '{name}'. Choose one of: {', '.join(self.names())}.") from None
        return getattr(import_module(module), attribute)(**options)


text_extractors = Registry("text extractor", {"pdfium": "app.adapters.text_pdfium:PdfiumTextExtractor"})
ocr_engines = Registry("OCR engine", {"tesseract": "app.adapters.ocr_tesseract:TesseractOCR",
                                      "fake": "app.adapters.ocr_fake:FakeOCR"})
object_stores = Registry("object store", {"filesystem": "app.adapters.objectstore:FilesystemStore",
                                          "s3": "app.adapters.objectstore:S3Store"})
llm_engines = Registry("LLM engine", {"openai_compat": "app.adapters.llm_openai:OpenAICompatEngine",
                                      "fake": "app.adapters.llm_fake:FakeEngine"})
