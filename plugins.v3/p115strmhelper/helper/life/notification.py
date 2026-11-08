"""生活事件合并通知的计数与正文渲染。

只依赖标准库，便于在无 MoviePilot 后端的环境下直接单测；`MonitorLife`
负责产生文件路径，本模块负责「记多少、怎么显示」。
"""

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

# 每个类别默认最多列出多少个文件，其余只报数量
DEFAULT_ITEM_LIMIT = 10


class NotificationBatch:
    """
    累积一段静默窗口内生成或下载的文件，供合并通知使用

    计数与实际展示分离：大目录事件只保留前 ``item_limit`` 条路径用于展示，
    但计数照常累加，避免通知正文被上千行路径撑爆。
    """

    def __init__(self, item_limit: int = DEFAULT_ITEM_LIMIT) -> None:
        """
        初始化空批次

        :param item_limit (int): 每个类别最多保留多少条路径用于展示
        """
        self._item_limit = max(0, int(item_limit))
        self._items: Dict[str, List[str]] = {"strm_items": [], "mediainfo_items": []}
        self._counts: Dict[str, int] = {"strm_count": 0, "mediainfo_count": 0}

    @property
    def empty(self) -> bool:
        """批次内没有可通知的内容时返回 True。"""
        return self._counts["strm_count"] == 0 and self._counts["mediainfo_count"] == 0

    def add(
        self,
        bucket: str,
        paths: Sequence[Union[str, Path]],
        count: Optional[int] = None,
    ) -> None:
        """
        追加一批文件

        :param bucket (str): ``strm_items`` 或 ``mediainfo_items``
        :param paths (Sequence): 文件完整路径
        :param count (int): 计入的数量，缺省按 ``paths`` 条数；批量场景可大于展示条数
        """
        if bucket not in self._items:
            raise ValueError(f"未知的通知类别: {bucket}")
        counter = "strm_count" if bucket == "strm_items" else "mediainfo_count"
        self._counts[counter] += len(paths) if count is None else count
        room = self._item_limit - len(self._items[bucket])
        if room > 0:
            self._items[bucket].extend(
                Path(path).as_posix() for path in list(paths)[:room]
            )

    def add_one(
        self, bucket: str, path: Union[str, Path], count: int = 1
    ) -> None:
        """
        追加单个文件

        :param bucket (str): ``strm_items`` 或 ``mediainfo_items``
        :param path (str|Path): 文件完整路径
        :param count (int): 计入的数量
        """
        self.add(bucket, [path], count)

    def _render(self, bucket: str, counter: str, heading: str) -> List[str]:
        """
        渲染一个类别的小标题、文件行与省略行

        :param bucket (str): 路径列表所在的键
        :param counter (str): 计数所在的键
        :param heading (str): 小标题模板，``{count}`` 会被替换

        :return List: 逐行文本，无内容时返回空列表
        """
        total = self._counts[counter]
        if total <= 0:
            return []
        items = self._items[bucket]
        lines = [heading.format(count=total)]
        lines.extend(f"  - {item}" for item in items)
        if total > len(items):
            lines.append(f"  ... 还有 {total - len(items)} 个")
        return lines

    def render(self) -> str:
        """
        渲染合并通知正文

        :return str: 以换行分隔的正文；批次为空时返回空字符串
        """
        lines: List[str] = []
        lines.extend(self._render("strm_items", "strm_count", "📄 生成STRM文件 {count} 个"))
        lines.extend(
            self._render("mediainfo_items", "mediainfo_count", "⬇️ 下载媒体文件 {count} 个")
        )
        return "\n".join(lines)
