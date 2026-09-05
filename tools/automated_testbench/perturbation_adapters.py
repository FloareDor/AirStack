"""Narrow adapters for declared perturbation surfaces.

Adapters transform validated data into launch configuration.  They never own a
mission, oracle, result file, or lifecycle operation.  WS1 patch assets remain
explicitly unavailable until their canonical CyLab handoff is supplied.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


class AdapterError(ValueError):
    pass


class PerturbationAdapter(Protocol):
    name: str

    def resolve(self, configuration: Mapping[str, Any]) -> dict[str, str]: ...


@dataclass(frozen=True)
class IsaacEnvironmentAdapter:
    """Environment changes presently supported by the MonoNav Isaac launcher."""

    name: str = "isaac_environment"

    def resolve(self, configuration: Mapping[str, Any]) -> dict[str, str]:
        permitted = {
            "MONONAV_SCENE_SEED",
            "MONONAV_SCENE_LATERAL_JITTER_M",
            "MONONAV_SCENE_LONGITUDINAL_JITTER_M",
            "MONONAV_SCENE_SCALE_JITTER",
            "MONONAV_SCENE_OBSTACLE_COUNT",
            "MONONAV_DOME_LIGHT_INTENSITY",
            "MONONAV_DOME_LIGHT_EXPOSURE",
        }
        unknown = set(configuration) - permitted
        if unknown:
            raise AdapterError("unsupported Isaac environment keys: " + ", ".join(sorted(unknown)))
        return {key: _finite_string(key, value) for key, value in configuration.items()}


@dataclass(frozen=True)
class Ros2SensorProxyAdapter:
    """Configuration contract for the future isolated ROS 2 sensor proxy."""

    name: str = "ros2_sensor_proxy"

    def resolve(self, configuration: Mapping[str, Any]) -> dict[str, str]:
        allowed = {"noise_stddev", "bias", "fixed_delay_s", "jitter_s", "dropout_probability"}
        unknown = set(configuration) - allowed
        if unknown:
            raise AdapterError("unsupported sensor proxy keys: " + ", ".join(sorted(unknown)))
        values = {key: _finite_string(key, value) for key, value in configuration.items()}
        dropout = float(configuration.get("dropout_probability", 0.0))
        if not 0.0 <= dropout <= 1.0:
            raise AdapterError("dropout_probability must be in [0, 1]")
        for key in ("noise_stddev", "fixed_delay_s", "jitter_s"):
            if float(configuration.get(key, 0.0)) < 0.0:
                raise AdapterError(f"{key} must be nonnegative")
        # This is data for the dedicated proxy launch, not an instruction that
        # allows a generator to launch a node itself.
        return {"WS2_SENSOR_PROXY_CONFIG_JSON": json.dumps(values, sort_keys=True)}


@dataclass(frozen=True)
class WS1VisualPatchAdapter:
    """Patch-scene adapter enabled only with a supplied canonical asset bundle."""

    asset_root: Path | None = None
    name: str = "ws1_visual_patch"

    def resolve(self, configuration: Mapping[str, Any]) -> dict[str, str]:
        if self.asset_root is None:
            raise AdapterError(
                "WS1 visual patches are unavailable until the canonical CyLab asset handoff"
            )
        scene = configuration.get("scene")
        asset = configuration.get("asset")
        if not isinstance(scene, str) or not isinstance(asset, str):
            raise AdapterError("WS1 patch configuration requires string scene and asset")
        asset_path = (self.asset_root / asset).resolve()
        if not asset_path.is_file() or self.asset_root.resolve() not in asset_path.parents:
            raise AdapterError("WS1 patch asset is missing or escapes the approved asset root")
        digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        return {
            "WS1_PATCH_SCENE": scene,
            "WS1_PATCH_ASSET": str(asset_path),
            "WS1_PATCH_ASSET_SHA256": digest,
        }


def _finite_string(name: str, value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterError(f"{name} must be numeric")
    if not math.isfinite(float(value)):
        raise AdapterError(f"{name} must be finite")
    return str(float(value))
