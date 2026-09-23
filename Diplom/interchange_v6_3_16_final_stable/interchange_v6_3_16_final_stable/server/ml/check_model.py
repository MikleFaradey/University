#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline compatibility check for an Interchange model package."""

from __future__ import print_function

import argparse
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
SERVER_DIR = THIS_FILE.parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from model_runtime import ModelManager, ModelLoadError  # noqa: E402
from traffic_features import FEATURE_COLUMNS, finalize_window, make_empty_window  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate an Interchange .joblib/.pkl model"
    )
    parser.add_argument("model", help="Path to model file")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    path = Path(args.model).expanduser().resolve()

    manager = ModelManager()
    try:
        status = manager.load(path)
    except ModelLoadError as exc:
        print("MODEL CHECK FAILED: %s" % exc, file=sys.stderr)
        return 1

    metrics = finalize_window(make_empty_window())
    try:
        result = manager.predict_window(
            "offline-check",
            "127.0.0.1",
            0.0,
            metrics,
        )
    except Exception as exc:
        print("MODEL CHECK FAILED DURING PREDICTION: %s" % exc, file=sys.stderr)
        return 1

    print("MODEL CHECK OK")
    print("File:        %s" % path)
    print("Features:    %d" % status.get("feature_count", 0))
    print("Window:      %.1f sec" % float(status.get("window_sec", 0.0)))
    print("Classes:     %s" % ", ".join(status.get("classes", [])))
    print("Prediction:  %s" % result.get("prediction"))
    confidence = result.get("confidence")
    if confidence is not None:
        print("Confidence:  %.2f%%" % (float(confidence) * 100.0))
    print("Canonical features available: %d" % len(FEATURE_COLUMNS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
