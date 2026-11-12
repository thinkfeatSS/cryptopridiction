"""
QUANT EDGE V16 DATA INGESTION & CACHING SUBSYSTEM
Provides high-performance local delta-caching and deep historical candle pagination.
"""

from .cache_manager import OHLCVCacheManager
from .candle_paginator import AsyncCandlePaginator, get_mtf_candles_batch, get_mtf_candles_batch_sync

__all__ = [
    "OHLCVCacheManager",
    "AsyncCandlePaginator",
    "get_mtf_candles_batch",
    "get_mtf_candles_batch_sync",
]
