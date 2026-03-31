"""
공통 Base Agent 클래스 — 모든 Agent가 상속
"""
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOG_DIR = ROOT / "logs"
OUT_DIR = ROOT / "output"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "system.log", encoding="utf-8"),
    ],
)


class _SafeEncoder(json.JSONEncoder):
    """bool, numpy, pandas 등 비표준 타입 안전 직렬화 (Python 3.14 대응)"""
    def default(self, obj):
        if isinstance(obj, bool):
            return bool(obj)
        try:
            import numpy as np
            if isinstance(obj, np.integer):  return int(obj)
            if isinstance(obj, np.floating): return float(obj)
            if isinstance(obj, np.ndarray):  return obj.tolist()
            if isinstance(obj, np.bool_):    return bool(obj)
        except ImportError:
            pass
        try:
            import pandas as pd
            if isinstance(obj, pd.Timestamp): return obj.isoformat()
            if isinstance(obj, pd.Series):    return obj.tolist()
        except ImportError:
            pass
        return super().default(obj)


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(name)
        self.result: dict = {}
        self.status: str = "idle"

    @abstractmethod
    def fetch(self) -> dict:
        pass

    @abstractmethod
    def analyze(self, data: dict) -> dict:
        pass

    def run(self) -> dict:
        self.status = "running"
        self.logger.info(f"{self.name} 시작")
        try:
            data = self.fetch()
            self.result = self.analyze(data)
            self.result["agent"] = self.name
            self.result["timestamp"] = datetime.now().isoformat()
            self.status = "done"
            self.logger.info(f"{self.name} 완료")
        except Exception as e:
            self.status = "error"
            self.result = {"agent": self.name, "error": str(e)}
            self.logger.error(f"{self.name} 오류: {e}")
        return self.result

    def save(self, subdir: str = "daily") -> Path:
        path = OUT_DIR / subdir / f"{self.name}_{datetime.now().strftime('%Y%m%d')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.result, f, ensure_ascii=False, indent=2, cls=_SafeEncoder)
        self.logger.info(f"저장 완료: {path}")
        return path
