import pytest
from app.adapters.ocr_tesseract import parse_tesseract_tsv
from app.adapters.registry import ocr_engines, text_extractors
from app.core.exceptions import AdapterConfigurationError


def test_tesseract_tsv_parser():
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t\n"
        "2\t1\t1\t0\t0\t0\t10\t10\t80\t80\t-1\t\n"
        "3\t1\t1\t1\t0\t0\t10\t10\t80\t40\t-1\t\n"
        "4\t1\t1\t1\t1\t0\t10\t10\t80\t20\t-1\t\n"
        "5\t1\t1\t1\t1\t1\t10\t10\t30\t20\t95\tPatient\n"
        "5\t1\t1\t1\t1\t2\t45\t10\t40\t20\t90\tRecord\n"
        "4\t1\t1\t1\t2\t0\t10\t35\t80\t20\t-1\t\n"
        "5\t1\t1\t1\t2\t1\t10\t35\t35\t20\t88\tSecond\n"
        "5\t1\t1\t1\t2\t2\t50\t35\t30\t20\t85\tLine\n"
        "2\t1\t2\t0\t0\t0\t10\t100\t80\t30\t-1\t\n"
        "3\t1\t2\t1\t0\t0\t10\t100\t80\t30\t-1\t\n"
        "4\t1\t2\t1\t1\t0\t10\t100\t80\t30\t-1\t\n"
        "5\t1\t2\t1\t1\t1\t10\t100\t50\t30\t92\tBlockTwo\n"
        "5\t1\t2\t1\t1\t2\t65\t100\t10\t30\t-1\tNegativeConfIgnored\n"
        "5\t1\t2\t1\t1\t3\t80\t100\t10\t30\t99\t   \n"
    )
    result = parse_tesseract_tsv(tsv, page=1)
    assert result.text == "Patient Record\nSecond Line\n\nBlockTwo"
    assert len(result.regions) == 5
    assert result.regions[0].text == "Patient"
    assert result.regions[0].page == 1
    assert result.regions[0].left == 10
    assert result.regions[0].top == 10
    assert result.regions[0].width == 30
    assert result.regions[0].height == 20
    assert result.regions[0].confidence == 95.0
    assert result.regions[4].text == "BlockTwo"


def test_tesseract_tsv_parser_page_text_limit():
    long_word = "A" * 100_001
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        f"5\t1\t1\t1\t1\t1\t10\t10\t30\t20\t95\t{long_word}\n"
    )
    with pytest.raises(ValueError) as exc:
        parse_tesseract_tsv(tsv, page=1)
    assert str(exc.value) == "page_text_limit"
    assert "A" * 50 not in str(exc.value)


def test_unknown_names_raise_adapter_configuration_error():
    with pytest.raises(AdapterConfigurationError):
        text_extractors.create("unknown_extractor")
    with pytest.raises(AdapterConfigurationError):
        ocr_engines.create("unknown_ocr_engine")


def test_fake_ocr():
    engine = ocr_engines.create("fake")
    result = engine.recognize(b"fake_png", "eng", page=4)
    assert result.text == "Synthetic OCR text for page 4."
    assert result.regions == ()
