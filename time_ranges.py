# -*- coding: utf-8 -*-
"""导出时间段：解析、合并、筛选。

纯函数模块，不依赖微信或 wechatauto，便于单独测试。

输入写法（每行一个时间段，空行和 # 开头的行忽略；也可以用 ; 或 ； 分隔）：

    2025-03-01                       整天
    2025-03-01 ~ 2025-03-05          含首尾两天
    2025-03-01 14:00 ~ 16:30         同一天的时间段，结束只写时间
    2025-03-01 14:00 ~ 2025-03-02 09:15:30
    2025-03-01 ~                     从该天起，不限结束
    ~ 2025-03-05                     到该天为止，不限开始
    2025年3月1日 14:05 至 2025年3月1日 18:00

分隔符可用 ~ ～ 至 到。日期可用 - / . 或“年月日”。时区为本机时区。
结束时间是“包含”的：只写日期表示到当天结束；写到分钟表示包含这一分钟。
重叠或相邻的时间段会自动合并。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

_SEPARATOR_RE = re.compile(r"\s*(?:~|～|至|到)\s*")
_LINE_SPLIT_RE = re.compile(r"[;；\r\n]+")
_DATE_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


@dataclass(frozen=True)
class TimeRange:
    """[start, end) 的 Unix 秒区间；None 表示该端不限制。

    start_text / end_text 是给人看的“包含”写法，例如结束 "2025-03-05"
    在内部对应 2025-03-06 00:00 的开区间端点。
    """

    start: int | None
    end: int | None
    start_text: str | None
    end_text: str | None

    def contains(self, ts: int) -> bool:
        if self.start is not None and ts < self.start:
            return False
        if self.end is not None and ts >= self.end:
            return False
        return True

    @property
    def label(self) -> str:
        start = self.start_text or "不限"
        end = self.end_text or "不限"
        if self.start_text and self.end_text and self.start_text == self.end_text:
            return self.start_text
        return f"{start} ~ {end}"

    def to_dict(self) -> dict:
        return {"start": self.start_text, "end": self.end_text, "label": self.label}


def _normalize_text(text: str) -> str:
    value = str(text).strip()
    value = value.replace("：", ":")
    value = value.replace("年", "-").replace("月", "-")
    value = value.replace("日", " ").replace("号", " ")
    return " ".join(value.split())


def _parse_date(text: str):
    match = _DATE_RE.match(text)
    if not match:
        raise ValueError(f"无法识别日期“{text}”，请写成 2025-03-01")
    year, month, day = (int(g) for g in match.groups())
    try:
        return datetime(year, month, day)
    except ValueError:
        raise ValueError(f"日期“{text}”不存在") from None


def _parse_time(text: str):
    match = _TIME_RE.match(text)
    if not match:
        raise ValueError(f"无法识别时间“{text}”，请写成 14:05 或 14:05:30")
    hour, minute = int(match.group(1)), int(match.group(2))
    second = match.group(3)
    if hour > 23 or minute > 59 or (second is not None and int(second) > 59):
        raise ValueError(f"时间“{text}”不存在")
    if second is None:
        return hour, minute, None
    return hour, minute, int(second)


def _parse_point(text: str, *, is_end: bool, base_date: datetime | None = None):
    """返回 (Unix 秒, 显示文本, 日期)。结束点会换算成开区间端点。"""
    parts = text.split(" ")
    if len(parts) == 1 and _TIME_RE.match(parts[0]):
        if base_date is None:
            raise ValueError(f"“{text}”只有时间没有日期；只有结束时间可以省略日期（沿用开始日期）")
        day = base_date
        time_part = parts[0]
    elif len(parts) == 1:
        day = _parse_date(parts[0])
        time_part = None
    elif len(parts) == 2:
        day = _parse_date(parts[0])
        time_part = parts[1]
    else:
        raise ValueError(f"无法识别“{text}”")

    date_text = day.strftime("%Y-%m-%d")
    if time_part is None:
        moment = day + timedelta(days=1) if is_end else day
        return int(moment.timestamp()), date_text, day

    hour, minute, second = _parse_time(time_part)
    moment = day.replace(hour=hour, minute=minute, second=second or 0)
    if second is None:
        display = f"{date_text} {hour:02d}:{minute:02d}"
        step = timedelta(minutes=1)
    else:
        display = f"{date_text} {hour:02d}:{minute:02d}:{second:02d}"
        step = timedelta(seconds=1)
    if is_end:
        moment += step
    return int(moment.timestamp()), display, day


def parse_range_line(line: str) -> TimeRange:
    """解析一行时间段；格式错误时抛出说明原因的 ValueError。"""
    text = _normalize_text(line)
    if not text:
        raise ValueError("空的时间段")
    parts = _SEPARATOR_RE.split(text)
    if len(parts) > 2:
        raise ValueError("一行只能写一个时间段（只能有一个 ~）")

    if len(parts) == 1:
        if " " in text:
            raise ValueError("带具体时间时请写成“开始 ~ 结束”")
        start, start_text, day = _parse_point(text, is_end=False)
        end, end_text, _ = _parse_point(text, is_end=True)
        return TimeRange(start, end, start_text, end_text)

    start_raw, end_raw = (p.strip() for p in parts)
    if not start_raw and not end_raw:
        raise ValueError("开始和结束至少要写一个")

    start = start_text = start_day = None
    if start_raw:
        start, start_text, start_day = _parse_point(start_raw, is_end=False)
    end = end_text = None
    if end_raw:
        end, end_text, _ = _parse_point(end_raw, is_end=True, base_date=start_day)

    if start is not None and end is not None and start >= end:
        raise ValueError("结束时间早于开始时间")
    return TimeRange(start, end, start_text, end_text)


def merge_ranges(ranges) -> list[TimeRange]:
    """按开始时间排序，合并重叠或首尾相接的时间段。"""
    items = sorted(
        ranges,
        key=lambda r: (r.start is not None, r.start if r.start is not None else 0),
    )
    merged: list[TimeRange] = []
    for item in items:
        if merged:
            last = merged[-1]
            touches = last.end is None or item.start is None or item.start <= last.end
            if touches:
                if last.end is None or (item.end is not None and item.end <= last.end):
                    continue
                merged[-1] = TimeRange(last.start, item.end, last.start_text, item.end_text)
                continue
        merged.append(item)
    return merged


def parse_time_ranges(value) -> list[TimeRange]:
    """把多行文本 / 字符串列表 / TimeRange 列表解析为合并后的时间段。

    空输入返回 []，表示不限制时间。任何一行出错都会抛出带行号的 ValueError。
    """
    if value is None:
        return []
    if isinstance(value, TimeRange):
        return [value]
    if isinstance(value, str):
        chunks = [value]
    else:
        chunks = list(value)

    ranges: list[TimeRange] = []
    errors: list[str] = []
    line_no = 0
    for chunk in chunks:
        if isinstance(chunk, TimeRange):
            line_no += 1
            ranges.append(chunk)
            continue
        for raw in _LINE_SPLIT_RE.split(str(chunk)):
            line = raw.strip()
            if not line:
                continue
            line_no += 1
            if line.startswith("#"):
                continue
            try:
                ranges.append(parse_range_line(line))
            except ValueError as exc:
                errors.append(f"第 {line_no} 个时间段“{line}”：{exc}")
    if errors:
        raise ValueError("时间段格式有误：\n" + "\n".join(errors))
    return merge_ranges(ranges)


def describe_ranges(ranges) -> str:
    return "；".join(r.label for r in ranges)


def filter_rows_by_ranges(rows, ranges, get_ts):
    """保留落在任一时间段内的行，并在行上写入 _range_index（从 1 开始）。

    get_ts(row) 返回 Unix 秒，无法识别时返回 <= 0。
    返回 (保留的行, 时间无效而丢弃的条数)。ranges 为空时原样返回。
    """
    if not ranges:
        return list(rows), 0
    kept = []
    unknown = 0
    for row in rows:
        ts = get_ts(row)
        if ts <= 0:
            unknown += 1
            continue
        for index, item in enumerate(ranges, 1):
            if item.contains(ts):
                row["_range_index"] = index
                kept.append(row)
                break
    return kept, unknown
