"""Download MonoNav's ZoeDepth weights before a time-limited campaign."""
import sys

sys.path.insert(0, "ZoeDepth")

from zoedepth.models.builder import build_model
from zoedepth.utils.config import get_config


build_model(get_config("zoedepth", "eval"))
print("MonoNav model cache is ready.", flush=True)
