#!/usr/bin/env python3
"""Export TrendRadar SQLite snapshots as a stable JSON feed for Culture Radar."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SHANGHAI = timezone(timedelta(hours=8))
P0_PEOPLE = [
    "余华", "莫言", "马未都", "余秀华", "王计兵", "贾平凹", "刘震云", "苏童", "阿来", "王安忆",
    "迟子建", "麦家", "毕飞宇", "格非", "梁文道", "许知远", "戴建业", "刘擎", "冯骥才", "孙频",
]
KEY_PEOPLE = [
    "韩少功", "李洱", "张炜", "陈春成", "班宇", "双雪涛", "张悦然", "梁鸿", "杨本芬", "蒋方舟",
    "西川", "欧阳江河", "翟永明", "臧棣", "陈嘉映", "罗新", "项飙", "严飞", "程乐松", "王小伟",
    "吴冠军", "仲树", "周国平", "易中天", "马家辉", "乔晓光", "杭间", "方李莉", "苑利", "田青", "马盛德",
]
CULTURE = re.compile(
    r"文学|作家|诗人|小说|散文|诗歌|写作|阅读|读书|出版|出版人|书店|书展|文学奖|非遗|非物质文化遗产|"
    r"传承人|传统技艺|传统工艺|民俗|戏曲|曲艺|博物馆|文物|古籍|考古|哲学|历史|人类学|社会学|"
    r"美学|人文|文化遗产|纪录片|文化节目|人文节目|艺术家|歌剧|导演|编剧|二十四节气|节气|"
    r"立春|雨水|惊蛰|春分|清明|谷雨|立夏|小满|芒种|夏至|小暑|大暑|立秋|处暑|白露|秋分|"
    r"寒露|霜降|立冬|小雪|大雪|冬至|小寒|大寒"
)
EVENT = re.compile(r"获奖|颁奖|入选|公布|发布|开幕|闭幕|逝世|去世|辞世|病逝|讣告|争议|抄袭|剽窃|侵权|回应|声明|辟谣|判决|官宣|定档|停播|启动|成立|展览|书展|签售|首发|申遗")
CONTENT = re.compile(r"解读|点评|评价|访谈|对谈|演讲|播客|视频|文章|专栏|新作|组诗|谈到|谈起|讲述|分享|自述|口述|写道|金句|片段|出圈|走红")


def iso_for(day: str, clock: str | None) -> str:
    value = (clock or "12:00").replace("-", ":")[:5]
    try:
        return datetime.fromisoformat(f"{day}T{value}:00").replace(tzinfo=SHANGHAI).isoformat()
    except ValueError:
        return datetime.fromisoformat(f"{day}T12:00:00").replace(tzinfo=SHANGHAI).isoformat()


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def classify(text: str) -> str:
    if EVENT.search(text):
        return "事件性热点"
    if CONTENT.search(text) or any(name in text for name in P0_PEOPLE + KEY_PEOPLE):
        return "内容性热点"
    return "日常性热点"


def stable_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:20]


def entities(title: str) -> list[str]:
    return [name for name in P0_PEOPLE + KEY_PEOPLE if name in title]


def item(
    *, title: str, url: str, source: str, source_type: str, platform: str,
    published_at: str, first_seen: str, last_seen: str, summary: str = "",
    rank: int | None = None, appearances: int = 1,
) -> dict[str, Any]:
    people = entities(title)
    return {
        "id": stable_id(url, title),
        "type": classify(title + summary),
        "domain": "非遗 / 传统文化" if re.search(r"非遗|传统技艺|传统工艺|民俗|传承人", title + summary) else "文学 / 人文",
        "title": title,
        "summary": summary or "TrendRadar发现的公开线索，请打开出处核对完整内容。",
        "url": url,
        "source": source,
        "sourceTitle": title,
        "sourceType": source_type,
        "publishedAt": published_at,
        "firstSeen": first_seen,
        "lastSeen": last_seen,
        "platforms": [platform],
        "people": people,
        "works": [],
        "institutions": [],
        "places": [],
        "p0": any(name in P0_PEOPLE for name in people) or bool(re.search(r"诺贝尔文学奖|鲁迅文学奖|茅盾文学奖|逝世|去世|辞世|病逝|讣告|二十四节气|立秋|处暑", title)),
        "rank": rank,
        "appearances": appearances,
        "metrics": "平台互动未接入" if rank is None else f"当前热榜第{rank}位 · 累计在榜{appearances}次",
    }


def read_news(db_path: Path) -> list[dict[str, Any]]:
    day = db_path.stem
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT n.title,n.url,n.mobile_url,n.rank,n.first_crawl_time,n.last_crawl_time,n.crawl_count,
                      p.name AS platform_name
               FROM news_items n LEFT JOIN platforms p ON p.id=n.platform_id"""
        ).fetchall()
    except sqlite3.Error:
        return []
    result = []
    for row in rows:
        title = clean(row["title"])
        url = row["url"] or row["mobile_url"] or ""
        if not title or not url or not (CULTURE.search(title) or entities(title)):
            continue
        result.append(item(
            title=title, url=url, source=row["platform_name"] or "TrendRadar热榜", source_type="平台热榜",
            platform=row["platform_name"] or "公开平台", published_at=iso_for(day, row["first_crawl_time"]),
            first_seen=iso_for(day, row["first_crawl_time"]), last_seen=iso_for(day, row["last_crawl_time"]),
            rank=row["rank"], appearances=row["crawl_count"] or 1,
        ))
    return result


def read_rss(db_path: Path) -> list[dict[str, Any]]:
    day = db_path.stem
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT i.title,i.url,i.published_at,i.summary,i.first_crawl_time,i.last_crawl_time,i.crawl_count,
                      f.name AS feed_name
               FROM rss_items i LEFT JOIN rss_feeds f ON f.id=i.feed_id"""
        ).fetchall()
    except sqlite3.Error:
        return []
    result = []
    for row in rows:
        title, summary, url = clean(row["title"]), clean(row["summary"]), row["url"] or ""
        if not title or not url or not (CULTURE.search(title + summary) or entities(title + summary)):
            continue
        published = row["published_at"] or iso_for(day, row["first_crawl_time"])
        result.append(item(
            title=title, url=url, source=row["feed_name"] or "公开网页", source_type="公开网页/RSS",
            platform="公开网页", published_at=published, first_seen=iso_for(day, row["first_crawl_time"]),
            last_seen=iso_for(day, row["last_crawl_time"]), summary=summary, appearances=row["crawl_count"] or 1,
        ))
    return result


def load_previous(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError, AttributeError):
        return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--previous")
    parser.add_argument("--out", default="culture-feed.json")
    args = parser.parse_args()
    root = Path(args.output_dir)
    now = datetime.now(SHANGHAI)
    cutoff = now - timedelta(days=30)
    current: list[dict[str, Any]] = []
    for db in sorted((root / "news").glob("*.db")):
        if db.stem >= cutoff.date().isoformat():
            current.extend(read_news(db))
    for db in sorted((root / "rss").glob("*.db")):
        if db.stem >= cutoff.date().isoformat():
            current.extend(read_rss(db))

    merged = {x.get("id"): x for x in load_previous(Path(args.previous) if args.previous else None) if x.get("id")}
    for x in current:
        old = merged.get(x["id"])
        if old:
            x["firstSeen"] = min(old.get("firstSeen") or x["firstSeen"], x["firstSeen"])
            x["appearances"] = max(int(old.get("appearances") or 1), int(x.get("appearances") or 1))
        merged[x["id"]] = x

    kept = []
    for x in merged.values():
        stamp = x.get("publishedAt") or x.get("lastSeen")
        try:
            date = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=SHANGHAI)
            if date < cutoff:
                continue
        except (ValueError, AttributeError):
            pass
        kept.append(x)
    kept.sort(key=lambda x: (bool(x.get("p0")), x.get("publishedAt") or x.get("lastSeen") or ""), reverse=True)

    platforms = sorted({p for x in kept for p in x.get("platforms", [])})
    payload = {
        "version": 1,
        "generatedAt": now.isoformat(),
        "windowDays": 30,
        "items": kept[:300],
        "meta": {"total": len(kept[:300]), "platforms": platforms, "collector": "TrendRadar", "interactionMetrics": "未接入"},
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(payload['items'])} culture items to {args.out}")


if __name__ == "__main__":
    main()
