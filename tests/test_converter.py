"""
Tests for media_optimizer.converter module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest

from media_optimizer.converter import ConversionResult, ImageConverter


def test_conversion_result_defaults():
    res = ConversionResult()
    assert res.total_files == 0
    assert res.converted == 0
    assert res.error_details == []


def test_find_images(temp_workspace):
    converter = ImageConverter()
    images = converter.find_images(temp_workspace["input_dir"])
    # Should find img_large (jpg), img_rgba (png), img_small (jpg)
    assert len(images) == 3

    # Non-existent directory
    assert converter.find_images(Path("/non/existent/dir")) == []


def test_convert_single_image_standard_and_rgba(temp_workspace, tmp_path):
    converter = ImageConverter(quality=90, target_format="JPG")
    dest_dir = tmp_path / "out"

    # 1. Standard JPG
    dest1 = dest_dir / "foto_grande.jpg"
    assert converter.convert_single_image(temp_workspace["img_large"], dest1) is True
    assert dest1.exists()
    assert dest1.stat().st_size > 0

    # 2. RGBA PNG with alpha
    dest2 = dest_dir / "transparente.jpg"
    assert converter.convert_single_image(temp_workspace["img_rgba"], dest2) is True
    assert dest2.exists()
    with Image.open(dest2) as img:
        assert img.mode == "RGB"


def test_convert_skip_existing_and_dry_run(temp_workspace, tmp_path):
    # Dry run
    converter_dry = ImageConverter(dry_run=True)
    dest_dry = tmp_path / "dry.jpg"
    assert converter_dry.convert_single_image(temp_workspace["img_small"], dest_dry) is True
    assert not dest_dry.exists()

    # Skip existing
    dest_skip = tmp_path / "skip.jpg"
    dest_skip.write_bytes(b"existing_content")
    converter_skip = ImageConverter(skip_existing=True)
    assert converter_skip.convert_single_image(temp_workspace["img_small"], dest_skip) is True
    assert dest_skip.read_bytes() == b"existing_content"


def test_convert_raw_mock(tmp_path):
    raw_file = tmp_path / "test.arw"
    raw_file.write_bytes(b"dummy_raw_bytes")

    converter = ImageConverter()
    dest = tmp_path / "raw_out.jpg"

    mock_raw = MagicMock()
    # Dummy 100x100x3 numpy array
    import numpy as np
    mock_raw.postprocess.return_value = np.zeros((100, 100, 3), dtype=np.uint8)

    mock_rawpy = MagicMock()
    mock_rawpy.imread.return_value.__enter__.return_value = mock_raw

    with patch("media_optimizer.converter.rawpy", mock_rawpy):
        assert converter.convert_single_image(raw_file, dest) is True
        assert dest.exists()


def test_convert_error_cleanup(tmp_path):
    corrupt_file = tmp_path / "corrupt.jpg"
    corrupt_file.write_bytes(b"not an image")

    converter = ImageConverter()
    dest = tmp_path / "fail.jpg"

    with patch.object(Image, "open", side_effect=ValueError("Corrupted image")):
        with pytest.raises(ValueError):
            converter.convert_single_image(corrupt_file, dest)
        assert not dest.exists()
        assert not dest.with_name(f"{dest.name}.tmp").exists()


def test_converter_run_full(temp_workspace, tmp_path):
    out_dir = tmp_path / "converted_out"
    converter = ImageConverter(workers=2)

    progress_events = []
    def on_prog(curr, tot, name):
        progress_events.append((curr, tot, name))

    result = converter.run(
        input_dir=temp_workspace["input_dir"],
        output_dir=out_dir,
        progress_callback=on_prog,
    )

    assert result.total_files == 3
    assert result.converted == 3
    assert result.errors == 0
    assert len(progress_events) >= 3


def test_converter_run_empty_and_cancelled(tmp_path):
    empty_in = tmp_path / "empty_in"
    empty_in.mkdir()
    converter = ImageConverter()

    res_empty = converter.run(empty_in, tmp_path / "out")
    assert res_empty.total_files == 0

    # Cancelled before start
    full_in = tmp_path / "in"
    full_in.mkdir()
    (full_in / "img.jpg").touch()

    res_cancelled = converter.run(
        full_in,
        tmp_path / "out",
        cancel_check=lambda: True,
    )
    assert res_cancelled.converted == 0


def test_converter_run_skips(temp_workspace, tmp_path):
    out_dir = tmp_path / "converted_out"
    converter = ImageConverter(workers=2, skip_existing=True)

    # First run creates the files
    converter.run(input_dir=temp_workspace["input_dir"], output_dir=out_dir)

    # Second run should skip all existing files
    progress_calls = []
    res2 = converter.run(
        input_dir=temp_workspace["input_dir"],
        output_dir=out_dir,
        progress_callback=lambda c, t, n: progress_calls.append(n),
    )
    assert res2.skipped == 3
    assert res2.converted == 0
    assert any("Ignorado" in p for p in progress_calls)


def test_converter_run_errors(temp_workspace, tmp_path):
    out_dir = tmp_path / "converted_err"
    converter = ImageConverter(workers=2)

    with patch.object(ImageConverter, "convert_single_image", side_effect=RuntimeError("Disk full")):
        res = converter.run(input_dir=temp_workspace["input_dir"], output_dir=out_dir)
        assert res.errors == 3
        assert len(res.error_details) == 3


def test_convert_temp_cleanup_on_save_error(temp_workspace, tmp_path):
    converter = ImageConverter()
    dest = tmp_path / "fail_temp.jpg"

    def fail_save(path, *args, **kwargs):
        Path(path).write_bytes(b"temp_data")
        raise RuntimeError("Save failed midway")

    with patch.object(Image.Image, "save", side_effect=fail_save):
        with pytest.raises(RuntimeError):
            converter.convert_single_image(temp_workspace["img_small"], dest)
        assert not (tmp_path / "fail_temp.jpg.tmp").exists()


def test_convert_grayscale_and_webp(tmp_path):
    # Grayscale image
    gray_img = Image.new("L", (100, 100), color=128)
    src_gray = tmp_path / "gray.png"
    gray_img.save(src_gray)

    converter_webp = ImageConverter(target_format="WEBP")
    dest_webp = tmp_path / "gray.webp"
    assert converter_webp.convert_single_image(src_gray, dest_webp) is True
    assert dest_webp.exists()


def test_convert_with_exif_and_overwrite(temp_workspace, tmp_path):
    dest = tmp_path / "exif_overwrite.jpg"
    dest.write_bytes(b"initial_dest")

    converter = ImageConverter(skip_existing=False)

    # Mock Image.open to have dummy exif info
    real_open = Image.open
    def mock_open(*args, **kwargs):
        img = real_open(*args, **kwargs)
        img.info["exif"] = b"Exif\x00\x00mock_exif_data"
        return img

    with patch.object(Image, "open", side_effect=mock_open):
        assert converter.convert_single_image(temp_workspace["img_small"], dest) is True
        assert dest.exists()
        assert dest.read_bytes() != b"initial_dest"


def test_converter_relpath_exception(tmp_path):
    in_dir = tmp_path / "in_custom"
    in_dir.mkdir()
    (in_dir / "img1.jpg").touch()

    converter = ImageConverter()
    with patch.object(ImageConverter, "convert_single_image", return_value=True):
        with patch.object(Path, "relative_to", side_effect=ValueError("Different drive")):
            res = converter.run(in_dir, tmp_path / "out")
            assert res.total_files == 1
            assert res.converted == 1


def test_converter_cancel_during_as_completed(tmp_path):
    in_dir = tmp_path / "in_cancel"
    in_dir.mkdir()
    (in_dir / "img1.jpg").touch()
    (in_dir / "img2.jpg").touch()

    converter = ImageConverter(workers=1)

    cancel_flag = [False]
    def mock_convert(*args, **kwargs):
        cancel_flag[0] = True  # Cancel after first file is processed
        return True

    with patch.object(ImageConverter, "convert_single_image", side_effect=mock_convert):
        res = converter.run(in_dir, tmp_path / "out", cancel_check=lambda: cancel_flag[0])
        assert res.total_files == 2



