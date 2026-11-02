"""
SUBSYSTEM 2: SIGNAL GENERATION SYSTEM
- Advanced Candle Dynamics Learning (Bull/Bear Streaks, Volume, Volatility)
- 5 Top Classifiers with Majority Consensus Voting (Green Bullish vs Red Bearish)
- 5 Top Regressors with Modal Consensus Price Selection (Higher Votes)
- Dominant Horizon Arbitration & Smart Money Concepts Integration
"""

from .candle_features import CandleDynamicsFeatureExtractor
from .ensemble_classifier import FiveModelDirectionClassifier
from .ensemble_regressor import FiveModelPriceRegressor
from .signal_generator import SignalGenerationSystem
from .per_coin_models import PerCoinModelRegistry
from .meta_labeler import CoinSpecificMetaLabeler

__all__ = [
    "CandleDynamicsFeatureExtractor",
    "FiveModelDirectionClassifier",
    "FiveModelPriceRegressor",
    "SignalGenerationSystem",
    "PerCoinModelRegistry",
    "CoinSpecificMetaLabeler",
]

