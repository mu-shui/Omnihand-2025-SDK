import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Waypoint:
    name: str
    arm_joints: list[float]
    hand_joints: list[float]
    arm_max_vel: list[float] = field(default_factory=lambda: [1.0] * 7)
    goal_tolerance: float = 0.01
    hand_timeout: float = 5.0

    def validate(self) -> None:
        if len(self.arm_joints) != 7:
            raise ValueError(f"arm_joints length must be 7, got {len(self.arm_joints)}")
        if len(self.arm_max_vel) != 7:
            raise ValueError(f"arm_max_vel length must be 7, got {len(self.arm_max_vel)}")
        if len(self.hand_joints) == 0:
            raise ValueError("hand_joints must not be empty")
        if self.goal_tolerance <= 0.0:
            raise ValueError("goal_tolerance must be > 0")
        if self.hand_timeout <= 0.0:
            raise ValueError("hand_timeout must be > 0")
        for value in self.arm_joints + self.hand_joints + self.arm_max_vel:
            if not math.isfinite(value):
                raise ValueError("joint/velocity values must be finite")
        for value in self.arm_max_vel:
            if value <= 0.0:
                raise ValueError("arm_max_vel values must be > 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arm_joints": self.arm_joints,
            "hand_joints": self.hand_joints,
            "arm_max_vel": self.arm_max_vel,
            "goal_tolerance": self.goal_tolerance,
            "hand_timeout": self.hand_timeout,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Waypoint":
        wp = cls(
            name=str(raw["name"]),
            arm_joints=[float(v) for v in raw["arm_joints"]],
            hand_joints=[float(v) for v in raw["hand_joints"]],
            arm_max_vel=[float(v) for v in raw.get("arm_max_vel", [1.0] * 7)],
            goal_tolerance=float(raw.get("goal_tolerance", 0.01)),
            hand_timeout=float(raw.get("hand_timeout", 5.0)),
        )
        wp.validate()
        return wp


@dataclass
class SequencePlan:
    steps: list[str]

    def validate(self) -> None:
        if len(self.steps) == 0:
            raise ValueError("steps must not be empty")
        for step in self.steps:
            if not step.strip():
                raise ValueError("step names must not be blank")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SequencePlan":
        plan = cls(steps=[str(v) for v in raw["steps"]])
        plan.validate()
        return plan


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
    if not isinstance(content, dict):
        raise ValueError(f"YAML root must be a map: {path}")
    return content
