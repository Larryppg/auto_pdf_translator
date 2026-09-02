from pdf_translation_workflow.models import Box


def test_box_overlap_uses_smaller_region() -> None:
    large = Box(0, 0, 100, 100)
    small = Box(10, 10, 20, 20)
    separate = Box(200, 200, 210, 210)
    assert large.coverage_of_smaller(small) == 1
    assert large.coverage_of_smaller(separate) == 0
