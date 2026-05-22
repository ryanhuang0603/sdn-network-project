#!/usr/bin/env python3
"""Unit tests for traffic prediction helpers."""

import os
import sys
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from analysis.predictor import (  # noqa: E402
    CongestionDetector,
    LinearRegressionPredictor,
    SlidingWindowPredictor,
    TrafficPredictor,
)


class PredictorTest(unittest.TestCase):
    def test_sliding_window_predictor_uses_average_plus_recent_trend(self):
        predictor = SlidingWindowPredictor(window_size=3)
        for value in [1.0, 2.0, 4.0]:
            predictor.add(value)

        self.assertAlmostEqual(predictor.get_average(), 7.0 / 3.0)
        self.assertAlmostEqual(predictor.predict(), (7.0 / 3.0) + 2.0)

    def test_sliding_window_predictor_never_predicts_negative_rate(self):
        predictor = SlidingWindowPredictor(window_size=3)
        predictor.add(10.0)
        predictor.add(1.0)

        self.assertEqual(predictor.predict(), 0)

    def test_linear_regression_predictor_detects_linear_trend(self):
        predictor = LinearRegressionPredictor(window_size=5)
        for value in [2.0, 4.0, 6.0, 8.0]:
            predictor.add(value)

        self.assertAlmostEqual(predictor.get_slope(), 2.0)
        self.assertAlmostEqual(predictor.predict(), 10.0)

    def test_traffic_predictor_falls_back_then_uses_linear_regression(self):
        predictor = TrafficPredictor(window_size=10)
        for value in [1.0, 2.0, 3.0, 4.0]:
            predictor.add(value)

        self.assertAlmostEqual(predictor.predict(), 3.5)

        predictor.add(5.0)
        self.assertAlmostEqual(predictor.predict(), 6.0)

    def test_congestion_detector_threshold_and_utilization(self):
        detector = CongestionDetector(link_capacity_mbps=10.0, threshold_ratio=0.8)

        self.assertFalse(detector.is_congested(8.0))
        self.assertTrue(detector.is_congested(8.1))
        self.assertEqual(detector.get_utilization(5.0), 0.5)


if __name__ == "__main__":
    unittest.main()
