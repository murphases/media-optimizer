"""
Tests for media_optimizer.image_optimizer module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest

from media_optimizer.image_optimizer import ImageOptimizer, OptimizationResult


def test_optimization_result_defaults():
    res = OptimizationResult()
    assert res.total_files == 0
    assert res.saved_bytes == 0
    assert res.savings_percent == 0.0
    assert res.error_details == []


def test_find_images(temp_workspace):
    optimizer = ImageOptimizer()
    images = optimizer.find_images(temp_workspace["input_dir"])
    # Should match JPG files
    assert len(images) == 2

    assert optimizer.find_images(Path("/non/existent/dir")) == []


def test_optimize_single_image_downscale(temp_workspace, tmp_path):
    optimizer = ImageOptimizer(quality=70, max_dim=1350)
    dest = tmp_path / "opt_large.jpg"

    orig_sz, new_sz = optimizer.optimize_single_image(temp_workspace["img_large"], dest)
    assert dest.exists()
    assert new_sz > 0

    with Image.open(dest) as img:
        assert max(img.size) <= 1350


def test_optimize_single_image_no_upscale(temp_workspace, tmp_path):
    optimizer = ImageOptimizer(quality=75, max_dim=1350)
    dest = tmp_path / "opt_small.jpg"

    orig_sz, new_sz = optimizer.optimize_single_image(temp_workspace["img_small"], dest)
    assert dest.exists()

    with Image.open(dest) as img:
        # Was 800x600, should stay 800x600
        assert img.size == (800, 600)


def test_optimize_skip_existing_and_dry_run(temp_workspace, tmp_path):
    # Dry-run
    optimizer_dry = ImageOptimizer(dry_run=True)
    dest_dry = tmp_path / "dry.jpg"
    orig_sz, new_sz = optimizer_dry.optimize_single_image(temp_workspace["img_small"], dest_dry)
    assert not dest_dry.exists()
    assert new_sz < orig_sz

    # Skip existing
    dest_skip = tmp_path / "skip.jpg"
    dest_skip.write_bytes(b"existing_optimized_file")
    optimizer_skip = ImageOptimizer(skip_existing=True)
    orig_sz2, new_sz2 = optimizer_skip.optimize_single_image(temp_workspace["img_small"], dest_skip)
    assert new_sz2 == len(b"existing_optimized_file")


def test_optimize_error_cleanup(tmp_path):
    optimizer = ImageOptimizer()
    corrupt_file = tmp_path / "corrupt.jpg"
    corrupt_file.write_bytes(b"not valid image")
    dest = tmp_path / "failed.jpg"

    with patch.object(Image, "open", side_effect=IOError("Corrupt")):
        with pytest.raises(IOError):
            optimizer.optimize_single_image(corrupt_file, dest)
        assert not dest.exists()


def test_image_optimizer_run_full(temp_workspace, tmp_path):
    out_dir = tmp_path / "opt_out"
    optimizer = ImageOptimizer(workers=2)

    progress_calls = []
    def on_prog(curr, tot, name):
        progress_calls.append((curr, tot, name))

    res = optimizer.run(
        input_dir=temp_workspace["input_dir"],
        output_dir=out_dir,
        progress_callback=on_prog,
    )

    assert res.total_files == 2
    assert res.optimized == 2
    assert res.orig_bytes > 0
    assert res.optimized_bytes > 0
    assert res.saved_bytes >= 0
    assert len(progress_calls) >= 2


def test_image_optimizer_empty_and_cancelled(tmp_path):
    optimizer = ImageOptimizer()
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    res = optimizer.run(empty_dir, tmp_path / "out")
    assert res.total_files == 0

    full_dir = tmp_path / "in"
    full_dir.mkdir()
    (full_dir / "img.jpg").touch()

    res_cancel = optimizer.run(
        full_dir,
        tmp_path / "out",
        cancel_check=lambda: True,
    )
    assert res_cancel.optimized == 0


def test_image_optimizer_run_skips(temp_workspace, tmp_path):
    out_dir = tmp_path / "opt_out_skips"
    optimizer = ImageOptimizer(workers=2, skip_existing=True)

    # First run creates files
    optimizer.run(input_dir=temp_workspace["input_dir"], output_dir=out_dir)

    # Second run should skip
    progress_names = []
    res2 = optimizer.run(
        input_dir=temp_workspace["input_dir"],
        output_dir=out_dir,
        progress_callback=lambda c, t, n: progress_names.append(n),
    )
    assert res2.skipped == 2
    assert res2.optimized == 0
    assert any("Ignorado" in name for name in progress_names)


def test_image_optimizer_run_errors(temp_workspace, tmp_path):
    out_dir = tmp_path / "opt_out_errors"
    optimizer = ImageOptimizer(workers=2)

    with patch.object(ImageOptimizer, "optimize_single_image", side_effect=RuntimeError("Disk full")):
        res = optimizer.run(input_dir=temp_workspace["input_dir"], output_dir=out_dir)
        assert res.errors == 2
        assert len(res.error_details) == 2


def test_optimize_temp_cleanup_on_save_error(temp_workspace, tmp_path):
    optimizer = ImageOptimizer()
    dest = tmp_path / "fail_opt_temp.jpg"

    def fail_save(path, *args, **kwargs):
        Path(path).write_bytes(b"temp_opt_bytes")
        raise RuntimeError("Optimization save failed")

    with patch.object(Image.Image, "save", side_effect=fail_save):
        with pytest.raises(RuntimeError):
            optimizer.optimize_single_image(temp_workspace["img_small"], dest)
        assert not (tmp_path / "fail_opt_temp.jpg.tmp").exists()


def test_optimize_non_rgb_image(tmp_path):
    cmyk_img = Image.new("CMYK", (200, 200), color=(10, 20, 30, 40))
    src = tmp_path / "cmyk.jpg"
    cmyk_img.save(src, "JPEG")

    optimizer = ImageOptimizer()
    dest = tmp_path / "rgb_out.jpg"
    orig_sz, new_sz = optimizer.optimize_single_image(src, dest)
    assert dest.exists()
    with Image.open(dest) as img:
        assert img.mode == "RGB"


def test_optimize_with_exif_and_overwrite(temp_workspace, tmp_path):
    dest = tmp_path / "exif_opt_overwrite.jpg"
    dest.write_bytes(b"initial_dest_content")

    optimizer = ImageOptimizer(skip_existing=False)

    real_open = Image.open
    def mock_open(*args, **kwargs):
        img = real_open(*args, **kwargs)
        img.info["exif"] = b"Exif\x00\x00dummy_exif"
        return img

    with patch.object(Image, "open", side_effect=mock_open):
        orig_sz, new_sz = optimizer.optimize_single_image(temp_workspace["img_small"], dest)
        assert dest.exists()
        assert dest.read_bytes() != b"initial_dest_content"


def test_optimize_relpath_exception(tmp_path):
    in_dir = tmp_path / "opt_in_custom"
    in_dir.mkdir()
    (in_dir / "img1.jpg").touch()

    optimizer = ImageOptimizer()
    with patch.object(ImageOptimizer, "optimize_single_image", return_value=(100, 50)):
        with patch.object(Path, "relative_to", side_effect=ValueError("Different drive")):
            res = optimizer.run(in_dir, tmp_path / "out")
            assert res.total_files == 1
            assert res.optimized == 1


def test_optimize_cancel_during_as_completed(tmp_path):
    in_dir = tmp_path / "opt_in_cancel"
    in_dir.mkdir()
    (in_dir / "img1.jpg").touch()
    (in_dir / "img2.jpg").touch()

    optimizer = ImageOptimizer(workers=1)

    cancel_flag = [False]
    def mock_opt(*args, **kwargs):
        cancel_flag[0] = True
        return (100, 50)

    with patch.object(ImageOptimizer, "optimize_single_image", side_effect=mock_opt):
        res = optimizer.run(in_dir, tmp_path / "out", cancel_check=lambda: cancel_flag[0])
        assert res.total_files == 2



