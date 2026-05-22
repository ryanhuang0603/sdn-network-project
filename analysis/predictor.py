#!/usr/bin/env python3
"""Traffic prediction module: sliding window moving average and simple linear regression."""

from collections import deque
import numpy as np


class SlidingWindowPredictor:
    """Sliding window moving average predictor."""

    def __init__(self, window_size=10):
        self.window_size = window_size
        self.data = deque(maxlen=window_size)

    def add(self, value):
        self.data.append(value)

    def predict(self):
        if len(self.data) < 2:
            return 0.0
        avg = sum(self.data) / len(self.data)
        if len(self.data) >= 2:
            trend = list(self.data)[-1] - list(self.data)[-2]
        else:
            trend = 0
        return max(0, avg + trend)

    def get_average(self):
        if not self.data:
            return 0.0
        return sum(self.data) / len(self.data)

    def len(self):
        return len(self.data)


class LinearRegressionPredictor:
    """Simple linear regression predictor."""

    def __init__(self, window_size=10):
        self.window_size = window_size
        self.x_data = deque(maxlen=window_size)
        self.y_data = deque(maxlen=window_size)

    def add(self, value):
        t = len(self.x_data)
        self.x_data.append(t)
        self.y_data.append(value)

    def predict(self, steps=1):
        if len(self.y_data) < 2:
            return 0.0
        x = np.array(self.x_data, dtype=float)
        y = np.array(self.y_data, dtype=float)
        n = len(x)
        if n < 2:
            return max(0, y[-1])
        slope = (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / \
                max(n * np.sum(x * x) - np.sum(x) ** 2, 1e-10)
        intercept = (np.sum(y) - slope * np.sum(x)) / n
        predicted = slope * (n + steps - 1) + intercept
        return max(0, predicted)

    def get_slope(self):
        if len(self.y_data) < 2:
            return 0.0
        x = np.array(self.x_data, dtype=float)
        y = np.array(self.y_data, dtype=float)
        n = len(x)
        return (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / \
               max(n * np.sum(x * x) - np.sum(x) ** 2, 1e-10)

    def len(self):
        return len(self.y_data)


class TrafficPredictor:
    """Unified predictor combining moving average and linear regression.

    Uses linear regression for trend-aware prediction when sufficient data is available,
    falling back to moving average.
    """

    def __init__(self, window_size=15):
        self.ma = SlidingWindowPredictor(window_size)
        self.lr = LinearRegressionPredictor(window_size)

    def add(self, value):
        self.ma.add(value)
        self.lr.add(value)

    def predict(self):
        if self.lr.len() < 5:
            return self.ma.predict()
        return self.lr.predict()

    def predict_both(self):
        return self.ma.predict(), self.lr.predict()

    def len(self):
        return self.lr.len()


class CongestionDetector:
    """Detects potential congestion based on predicted traffic vs link capacity."""

    def __init__(self, link_capacity_mbps=10.0, threshold_ratio=0.8):
        self.link_capacity = link_capacity_mbps
        self.threshold_ratio = threshold_ratio
        self.threshold = link_capacity_mbps * threshold_ratio

    def is_congested(self, predicted_rate_mbps):
        return predicted_rate_mbps > self.threshold

    def get_utilization(self, current_rate_mbps):
        return current_rate_mbps / self.link_capacity if self.link_capacity > 0 else 1.0
