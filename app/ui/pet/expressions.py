"""启动时扫描真实PNG，建立界面与LLM共用的表情目录。"""
import logging
from pathlib import Path

from PySide6.QtGui import QImageReader
from app.paths import ASSET_DIR


class ExpressionCatalog:
    def __init__(self, assets_dir=None, default="平常", allowed_names=None):
        self.assets_dir = Path(assets_dir) if assets_dir is not None else ASSET_DIR
        self.paths = {}
        logger = logging.getLogger("tachitalk")
        for path in sorted(self.assets_dir.glob("*.png")):
            if allowed_names is not None and path.stem not in allowed_names:
                logger.warning("立绘%s没有对应TTS参考音频，本次不提供给LLM", path.stem)
                continue
            if QImageReader(str(path)).read().isNull():
                logger.warning("立绘图片无法加载，忽略：%s", path)
                continue
            self.paths[path.stem] = path
        if not self.paths:
            raise ValueError(f"没有可加载且符合配置的立绘PNG，请检查：{self.assets_dir}")
        self.default = default if default in self.paths else next(iter(self.paths))
        if self.default != default:
            logger.warning("默认表情%s不可用，改用%s", default, self.default)
        self.names = (self.default, *(name for name in self.paths if name != self.default))

    def normalize(self, expression):
        if not isinstance(expression, str) or expression not in self.paths:
            logging.getLogger("tachitalk").warning("表情%r不可用，回退为%s", expression, self.default)
            return self.default
        return expression
