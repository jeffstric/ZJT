from unittest.mock import MagicMock, patch

from task.visual_drivers.base_video_driver import BaseVideoDriver


class DummyVideoDriver(BaseVideoDriver):
    def __init__(self):
        super().__init__("dummy", 0)

    def submit_task(self, ai_tool):
        return {}

    def check_status(self, project_id):
        return {}

    def build_create_request(self, ai_tool):
        return {}

    def build_check_query(self, project_id):
        return {}


def test_mask_multipart_form_data_keeps_image_size_fields_and_masks_secret():
    driver = DummyVideoDriver()

    result = driver._mask_multipart_form_data({
        "prompt": "make it vertical",
        "size": "1024x1536",
        "ratio": "9:16",
        "image_size": "1K",
        "api_key": "secret-value",
    })

    assert result["size"] == "1024x1536"
    assert result["ratio"] == "9:16"
    assert result["image_size"] == "1K"
    assert result["api_key"] == "secr***alue"


def test_mask_multipart_form_data_tolerates_unexpected_sequence_items():
    driver = DummyVideoDriver()

    result = driver._mask_multipart_form_data([
        ("size", "1024x1536"),
        "unexpected",
    ])

    assert result[0] == ("size", "1024x1536")
    assert result[1] == {"field": "unknown", "repr": "<class 'str'>"}


def test_summarize_multipart_files_excludes_file_bytes():
    driver = DummyVideoDriver()

    result = driver._summarize_multipart_files([
        ("image", ("input.png", b"image-bytes", "image/png")),
        ("mask", ("mask.png", b"mask-bytes", "image/png")),
    ])

    assert result == [
        {
            "field": "image",
            "filename": "input.png",
            "content_type": "image/png",
            "size_bytes": 11,
        },
        {
            "field": "mask",
            "filename": "mask.png",
            "content_type": "image/png",
            "size_bytes": 10,
        },
    ]


def test_summarize_multipart_files_tolerates_unseekable_file_objects():
    class UnseekableFile:
        def tell(self):
            raise OSError("not seekable")

        def seek(self, *_args):
            raise OSError("not seekable")

    driver = DummyVideoDriver()

    result = driver._summarize_multipart_files([
        ("image", ("input.png", UnseekableFile(), "image/png")),
    ])

    assert result == [
        {
            "field": "image",
            "filename": "input.png",
            "content_type": "image/png",
            "size_bytes": None,
        },
    ]


@patch("task.visual_drivers.base_video_driver.api_logger")
@patch("task.visual_drivers.base_video_driver.requests.request")
def test_request_logs_multipart_context_form_data_and_files(mock_request, mock_api_logger):
    driver = DummyVideoDriver()
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.json.return_value = {"ok": True}
    response.raise_for_status.return_value = None
    mock_request.return_value = response

    driver._request(
        "https://example.test/v1/images/edits",
        data={"size": "1024x1536", "api_key": "secret-value"},
        files=[("image", ("input.png", b"image-bytes", "image/png"))],
        request_context={"ratio": "9:16", "image_size": "1K", "mapped_size": "1024x1536"},
    )

    logged = "\n".join(str(call.args[0]) for call in mock_api_logger.info.call_args_list)
    assert "Context: {'ratio': '9:16', 'image_size': '1K', 'mapped_size': '1024x1536'}" in logged
    assert "Form Data: {'size': '1024x1536', 'api_key': 'secr***alue'}" in logged
    assert "Files: [{'field': 'image', 'filename': 'input.png', 'content_type': 'image/png', 'size_bytes': 11}]" in logged
    assert "request_context" not in mock_request.call_args.kwargs
