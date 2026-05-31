#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke test for auto action module.

This test is intentionally lightweight and works even when OpenCV is missing.
"""

from dmd_auto_action import AutoActionConfig, available_detectors, preprocess_video_for_dmd


def main() -> int:
    dets = available_detectors()
    assert "person" in dets, "person detector should be available by default"

    # Expected failure path on non-existing source and/or missing OpenCV.
    ok, out_path, msg = preprocess_video_for_dmd("__missing__.mp4", AutoActionConfig())
    assert ok is False, "missing source should not succeed"
    assert out_path is None, "failed run should not return an output path"
    assert isinstance(msg, str) and len(msg) > 0, "failure reason should be provided"

    print("auto_action_smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

