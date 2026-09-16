# analytics/__init__.py
from .feeding_response import FeedingResponseAnalyzer, FrameData, FRSResult
from .amount_advisor import AmountAdvisor, AmountAdvice
from .growth_prediction import (
    GrowthPredictionAnalyzer,
    GrowthPredictionResult,
    GrowthRecord as GrowthPredictionRecord,
    StableFishIdentityMapper,
)
from .growth_tracker import GrowthTracker, GrowthRecord as LegacyGrowthRecord
from .activity_pattern import MultiDayActivityAnalyzer, AnalyzerConfig
from .abr import ABRAnalyzer, ABRResult

__all__ = [
    "FeedingResponseAnalyzer",
    "FrameData",
    "FRSResult",
    "AmountAdvisor",
    "AmountAdvice",
    "GrowthPredictionAnalyzer",
    "GrowthPredictionResult",
    "GrowthPredictionRecord",
    "StableFishIdentityMapper",
    "GrowthTracker",
    "LegacyGrowthRecord",
    "MultiDayActivityAnalyzer",
    "AnalyzerConfig",
    "ABRAnalyzer",
    "ABRResult",
]
