"""标题解析器：从 PT 发布标题还原「片名 + 年份 + 季集」。

这是整个追更链路的基石。PT 站标题五花八门，例如：

    剧集（有季集）  Mushoku Tensei Isekai Ittara Honki Dasu S03 2026 1080p CR WEB-DL x264 AAC-ADWeb
    剧集（绝对集）  [动漫]某番剧 - 07 1080p B-Global WEB-DL AAC
    剧集（中文集）  某部剧.第05集.1080p.WEB-DL
    合集           某剧 全12集 1080p WEB-DL
    电影            超新星.2020.1080p.BluRay.x264-GROUP

要还原成结构化的 ParsedTitle：
    title   = 干净片名（拿去搜 TMDB）
    year    = 发行年份
    season  = 季号
    episode = 集号（绝对集或季内集）
    complete= 是否合集标记（全N集）

核心策略：**从右往左剥规格**。片名可能自带点号（S.W.A.T.）、
年份（2001）、数字（3.10.to.Yuma），所以不能简单按点号切第一个词，
而是从右往左剥掉已知的技术段，剩下的才是片名。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ============================================================================
# 词汇表
# ============================================================================

# 分辨率
_RESOLUTIONS = {
    "2160p", "1080p", "1080i", "720p", "576p", "480p", "4k", "8k", "uhd",
    "fhd", "hd", "sd", "qhd", "2k",
}

# 来源 / 介质
_SOURCES = {
    "bluray", "blu-ray", "bdrip", "brrip", "bdremux", "remux", "webrip",
    "web-dl", "webdl", "web", "hdtv", "dvdrip", "dvd", "hdrip", "tvrip",
    "uhdbd", "bd", "blurayrip",
}

# 编码
_CODECS = {
    "x264", "x265", "h264", "h265", "h.264", "h.265", "hevc", "avc", "av1",
    "xvid", "divx", "vp9", "mpeg2",
}

# 音轨
_AUDIO = {
    "aac", "ac3", "eac3", "ddp", "dd", "dts", "dts-hd", "dtshd", "truehd",
    "atmos", "flac", "lpcm", "pcm", "mp3", "opus", "ddp5", "dd5", "aac2.0",
}

# HDR / 色彩 / 位深
_HDR = {
    "hdr", "hdr10", "hdr10+", "dv", "dolby", "vision", "sdr", "hlg",
    "10bit", "8bit", "hdrvivid", "hdr10plus",
}

# 其他常见标记
_MISC = {
    "repack", "proper", "internal", "complete", "limited", "remastered",
    "extended", "uncut", "unrated", "criterion", "imax", "ma", "multi",
    "dual", "chs", "cht", "gb", "big5", "hq", "uhq", "fps",
    "简", "繁", "简繁", "中字", "国语", "粤语", "双语", "英语", "日语", "无字",
    "subs", "sub", "subtitle", "subtitles", "audio", "rip", "full", "batch",
    "合集", "字幕", "内封", "外挂",
}

# 季集关键词（本身不作为片名，仅用于分界识别）
_SEASON_KEYS = {"season", "ep", "episode"}

# 片源平台（出现在标题里但不是片名）
_PLATFORMS = {
    "apple", "appletv", "appletv+", "itunes", "netflix", "nf", "amzn",
    "amazon", "prime", "disney", "disney+", "hulu", "hbo", "max", "hbomax",
    "paramount", "peacock", "atvp", "atv", "ip", "iqiyi", "youku",
    "bilibili", "viu", "tv", "tv+", "series", "tx", "腾讯", "爱奇艺", "芒果",
    "mgtv", "b站",
    # 日番 / 动画区常见片源平台标签
    "cr", "crunchyroll", "baha", "bahamut", "at-x", "b-global", "bglobal",
    "abema", "danime", "funimation", "hidive", "adn", "wakanim",
    "ani-one", "anione",
}

# 全部技术词（合并，统一小写）
_TECH_WORDS = (
    _RESOLUTIONS | _SOURCES | _CODECS | _AUDIO | _HDR | _MISC
    | _SEASON_KEYS | _PLATFORMS
)

# ============================================================================
# 正则
# ============================================================================

# 季集标记：S01E05 / S01 / E05 / EP05 / 第05集 / 绝对集 - 07
_SE_EP = re.compile(r"(?i)\bS(\d{1,2})E(\d{1,4})\b")
_SE_ONLY = re.compile(r"(?i)\bS(\d{1,2})\b(?=\s|$|[.\-_（(])")
_EP_ONLY = re.compile(r"(?i)\bE(?:P)?(\d{1,4})\b")
_CN_EP = re.compile(r"第\s*(\d{1,4})\s*[集话話]")
# 动漫绝对集数：`- 07` / `-07`（连字符 + 纯数字，通常出现在片名后）
_ABS_EP = re.compile(r"-\s*(\d{1,4})\b")

# 合集 / 多季：S01-S03 / 1-3季
_RANGE = re.compile(r"(?i)\bS\d{1,2}\s*[-~]\s*S?\d{1,2}\b")

# 年份（独立段落）
_YEAR_TOKEN = re.compile(r"^(19\d{2}|20\d{2})$")

# 括号标签：[中字] [更多资源]（容忍嵌套括号）
_BRACKET_TAG = re.compile(r"[\[【][^\[\]【】]*[\]】]|[（(][^（()）]*[）)]")

# 结尾压制组：-GROUP
_TRAILING_GROUP = re.compile(r"-[A-Za-z0-9][A-Za-z0-9._-]{0,24}$")

# 未闭合括号残片（RSS 截断）
_UNCLOSED_BRACKET = re.compile(r"[\[【][^\[\]【】]*$")

# 带点号的技术串：H.265 / DDP5.1 / DTS-HD.MA（切段前整段删）
_DOTTED_TECH = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"h\.?26[45]"
    r"|x\.?26[45]"
    r"|(?:dd|ddp|dts|aac|ac3|eac3|truehd|atmos|flac|lpcm|mp3)[.\-]?(?:hd|ma|plus|\d+(?:\.\d+)?)?"
    r"|(?:uhd|bd|web)[.\-]?(?:dl|rip|remux)"
    r")(?![A-Za-z0-9])"
)

# 分界标记（整段匹配才算）：从这里往右全是规格
_BOUNDARY_PATTERNS = [
    re.compile(r"(?i)^S\d{1,2}E\d{1,4}$"),
    re.compile(r"(?i)^S\d{1,2}$"),
    re.compile(r"(?i)^E(?:P)?\d{1,4}$"),
    re.compile(r"^第\d{1,4}[集话話季]$"),
    re.compile(r"(?i)^S\d{1,2}[-~]S?\d{1,2}$"),
    re.compile(r"^\d{1,2}季$"),
]

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


@dataclass
class ParsedTitle:
    """解析结果。拿不准的字段留空（None/空串），由调用方决定怎么办。"""

    title: str = ""                 # 干净片名（可直接搜 TMDB）
    year: int | None = None         # 发行年份
    season: int | None = None       # 季号
    episode: int | None = None      # 集号（季内集或绝对集）
    complete: bool = False          # 是否合集标记（全N集）
    raw: str = ""                   # 原始标题
    confident: bool = False         # 是否有把握

    @property
    def has_episode(self) -> bool:
        return self.season is not None or self.episode is not None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "year": self.year,
            "season": self.season,
            "episode": self.episode,
            "complete": self.complete,
            "confident": self.confident,
        }

    def __str__(self) -> str:
        bits = [self.title or "(未识别)"]
        if self.year:
            bits.append(f"({self.year})")
        if self.season is not None:
            if self.episode is not None:
                bits.append(f"S{self.season:02d}E{self.episode:02d}")
            else:
                bits.append(f"S{self.season:02d}")
        elif self.episode is not None:
            bits.append(f"E{self.episode:02d}")
        return " ".join(bits)


# ============================================================================
# 辅助判断
# ============================================================================

def _is_tech_token(cleaned: str) -> bool:
    """这一段是不是纯规格标记（可安全丢掉）。"""
    low = cleaned.lower()
    if low in _TECH_WORDS:
        return True
    # 合集标记：全24集 / 全 24 集 / 24集全
    if re.match(r"^全?\s*\d{1,3}\s*[集话話]全?$", low) and re.search(r"\d", low):
        return True
    # 裸分辨率数字：2160 / 1080 / 720
    if re.match(r"^(?:4320|2160|1440|1080|900|720|576|480)$", low):
        return True
    # 组合技术段：ddp5 / truehd7.1 / 10bit / 2ch / 24fps
    if re.match(r"^(?:dd|ddp|dts|aac|ac3|eac3|truehd|atmos|flac)\d", low):
        return True
    if re.match(r"^\d+(?:bit|ch|kbps|fps|mbps)$", low):
        return True
    if re.match(r"^\d(?:\.\d)?$", low):
        return True
    if re.match(r"^\d{2,3}fps$", low):
        return True
    return False


def _is_boundary_token(cleaned: str) -> bool:
    """这一段是不是「片名与规格的分界」。"""
    if not cleaned:
        return False
    if _YEAR_TOKEN.match(cleaned):
        return True
    for p in _BOUNDARY_PATTERNS:
        if p.match(cleaned):
            return True
    return False


def _is_empty_shell_token(token: str) -> bool:
    """全大写无元音短串（发布组前缀残片，如 UBWEB / CHDWEB）。"""
    if not (3 <= len(token) <= 7):
        return False
    if not token.isascii() or not token.isalpha():
        return False
    if not token.isupper():
        return False
    return not any(ch in "AEIOUaeiou" for ch in token)


def _is_strippable(token: str) -> bool:
    return _is_tech_token(token) or _is_boundary_token(token) or _is_empty_shell_token(token)


# ============================================================================
# 主解析
# ============================================================================

def _extract_episode_marks(text: str) -> tuple[str, int | None, int | None, bool]:
    """摘掉季集/合集标记，返回 (剩余文本, 季, 集, 是否合集)。"""
    season = episode = None
    complete = False

    # 合集标记：全24集
    m = re.search(r"全\s*(\d{1,3})\s*[集话話]", text)
    if m:
        complete = True
        text = text[: m.start()] + " " + text[m.end():]

    # S01E05
    m = _SE_EP.search(text)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        text = text[: m.start()] + " " + text[m.end():]
        return text, season, episode, complete

    # 第05集
    m = _CN_EP.search(text)
    if m:
        episode = int(m.group(1))
        text = text[: m.start()] + " " + text[m.end():]
        return text, season, episode, complete

    # 单独季号 S01
    m = _SE_ONLY.search(text)
    if m:
        season = int(m.group(1))
        text = text[: m.start()] + " " + text[m.end():]
        return text, season, episode, complete

    # E05 / EP05
    m = _EP_ONLY.search(text)
    if m:
        episode = int(m.group(1))
        text = text[: m.start()] + " " + text[m.end():]
        return text, season, episode, complete

    return text, season, episode, complete


def parse_release_title(raw: str) -> ParsedTitle:
    """把发布标题解析成「片名 + 年份 + 季集」。"""
    result = ParsedTitle(raw=raw)
    text = (raw or "").strip()
    if not text:
        return result

    # 0. 括号里的年份（全角/半角括号）
    yp = re.search(r"[（(\[]\s*(19\d{2}|20\d{2})\s*[）)\]]", text)
    if yp:
        result.year = int(yp.group(1))

    # 1. 括号标签 + 未闭合括号 + 季范围 + 压制组
    for _ in range(5):
        nt = _UNCLOSED_BRACKET.sub("", text)
        if nt == text:
            break
        text = nt
    text = _BRACKET_TAG.sub(" ", text)
    text = _RANGE.sub(" ", text)
    text = text.rstrip()
    text = _TRAILING_GROUP.sub("", text)

    # 2. 季集 + 带点技术串
    text, season, episode, complete = _extract_episode_marks(text)
    result.season, result.episode, result.complete = season, episode, complete
    text = _DOTTED_TECH.sub(" ", text)

    # 3. 切段
    parts = [p for p in re.split(r"[._\s]+", text) if p]

    # 4. 从右往左剥规格
    idx = len(parts) - 1
    year: int | None = None
    saw_tech = season is not None or episode is not None or complete
    while idx >= 0:
        cleaned = parts[idx].strip("-+")
        if not cleaned:
            idx -= 1
            continue
        if _is_boundary_token(cleaned):
            if year is None and _YEAR_TOKEN.match(cleaned):
                year = int(cleaned)
            saw_tech = True
            idx -= 1
            break
        if _is_strippable(cleaned):
            saw_tech = True
            idx -= 1
            continue
        break

    keep = [p.strip("-+") for p in parts[: idx + 1] if p.strip("-+")]
    if not keep:
        return result

    # 5. 年份落在片名区
    if year is None:
        for pos in range(len(keep) - 1, 0, -1):
            if _YEAR_TOKEN.match(keep[pos]):
                year = int(keep.pop(pos))
                saw_tech = True
                break

    # 6. 年份左边残留的季集标记
    while len(keep) > 1 and _is_boundary_token(keep[-1]):
        keep.pop()
        saw_tech = True

    # 7. 片名区尾部混着的技术段
    if len(keep) > 1:
        last_content = 0
        for pos, token in enumerate(keep):
            if not _is_strippable(token):
                last_content = pos
        if last_content < len(keep) - 1:
            saw_tech = True
            keep = keep[: last_content + 1]

    # 8. 开头残留的多字符技术串
    while len(keep) > 1:
        head = keep[0]
        if len(head) < 2 or head.isdigit():
            break
        if not _is_tech_token(head):
            break
        keep.pop(0)
        saw_tech = True

    while keep and _is_tech_token(keep[-1]):
        keep.pop()

    if not keep:
        return result

    title = " ".join(keep).strip(" -_.")

    # 9. 点号片名还原（S.W.A.T. / 3.10.to.Yuma）
    title = _restore_dotted_title(raw, title, keep)

    result.title = title
    result.year = year or result.year
    result.confident = bool(saw_tech and 1 <= len(title) <= 80)
    return result


def _restore_dotted_title(raw: str, title: str, keep: list[str]) -> str:
    """还原「缩写式点号片名」。

    只有前两个词是「缩写式」（单字母或纯数字）才进入点号片名模式：
        S.W.A.T.    → S.W.A.T（S / W / A / T）
        3.10.to.Yuma → 3.10.to.Yuma（3 / 10 / to / Yuma）

    普通英文单词间的点号（The.Matrix → The Matrix）不触发，还原成空格。
    """
    if len(keep) < 2:
        return title

    def _is_abbr(w: str) -> bool:
        return w.isdigit() or (len(w) == 1 and w.isalpha())

    if not (_is_abbr(keep[0]) and _is_abbr(keep[1])):
        return title

    first = re.escape(keep[0])
    m = re.search(r"(?i)" + first + r"((?:\.[A-Za-z0-9'\-]+)+)", raw)
    if not m:
        return title

    dotted_words = m.group(1).strip(".").split(".")
    if not dotted_words:
        return title

    rejoined = keep[0]
    idx = 1
    for dw in dotted_words:
        if idx >= len(keep):
            break
        if keep[idx].lower() != dw.lower():
            break
        rejoined += "." + keep[idx]
        idx += 1

    if idx == 1:
        return title

    rest = keep[idx:]
    return rejoined + (" " + " ".join(rest) if rest else "")


# ============================================================================
# 搜索词生成
# ============================================================================

def search_query(raw: str) -> str:
    """只要片名（搜索用）。解析失败返回空串。"""
    return parse_release_title(raw).title


def search_terms(raw: str) -> list[str]:
    """按优先级给出所有可搜索名：先原文/拼音，再中文别名。"""
    terms: list[str] = []
    p = parse_release_title(raw)
    if p.title and p.confident:
        terms.append(p.title)
    for alias in _aliases(raw):
        if alias not in terms:
            terms.append(alias)
    return terms


# ============================================================================
# 中文别名提取（国产动漫常用拼音当标题，方括号里带中文名）
# ============================================================================

_ALIAS_NOISE = re.compile(
    r"(?:第\s*\d+\s*[集话話季]|\d+\s*[集话話季]|EP?\d+|S\d{1,2}E?\d{0,3}|"
    r"第[一二三四五六七八九十]+季|[一二三四五六七八九十]+季|"
    r"导演|主演|编剧|演员|类型|地区|语言|片长|上映|简介|剧情|"
    r"澳剧|美剧|英剧|日剧|韩剧|国产剧|港剧|台剧|泰剧|新剧|"
    r"简繁|中字|内封|外挂|国语|粤语|日语|双语|原盘|"
    r"WEB-?DL|BluRay|HDR|H\.?26[45]|HEVC|AVC|AAC|DDP|DTS|Atmos|"
    r"\d{3,4}p|\d+bit|\d+Fps|UBWEB|CHDWEB|X264|X265|"
    r"Animations?|Animation|Series|Movie|Documentary)",
    re.IGNORECASE,
)

_ALIAS_CREDITS = re.compile(
    r"(?:导演|主演|编剧|演员|配音|原作|监制|制片)\s*[:：]?\s*[^|｜/\[\]【】]*",
)

_ALIAS_PREFIX = re.compile(
    r"^(?:澳剧|美剧|英剧|日剧|韩剧|国产剧|港剧|台剧|泰剧|新剧|"
    r"欧美剧|日番|国漫|动漫|动画)\s*[:：]?\s*",
)

_ALIAS_STOPWORDS = {
    "动漫", "动画", "动画片", "综艺", "纪录片", "电视剧", "电影", "合集", "体育",
    "animations", "animation", "tvseries", "tv series", "tv", "series",
    "movie", "movies", "documentary", "music", "sports", "anime",
}


def _clean_alias(text: str) -> str:
    out = _ALIAS_CREDITS.sub(" ", text or "")
    out = _ALIAS_PREFIX.sub("", out)
    out = _ALIAS_NOISE.sub(" ", out)
    out = re.sub(r"[\[\]【】()（）<>《》|｜/\\,，;；:：\-—_·*]+", " ", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _aliases(raw: str) -> list[str]:
    text = raw or ""
    if not text:
        return []
    for _ in range(5):
        nt = _UNCLOSED_BRACKET.sub("", text)
        if nt == text:
            break
        text = nt

    found: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        cleaned = _clean_alias(candidate)
        if not cleaned or not _CJK.search(cleaned):
            return
        bare = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", cleaned.lower())
        for stop in _ALIAS_STOPWORDS:
            if bare == re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", stop.lower()):
                return
        stripped = re.sub(r"^(动漫|动画|综艺|纪录片|电视剧|电影|合集)+\s*", "", cleaned).strip()
        if stripped and len(_CJK.findall(stripped)) >= 2:
            cleaned = stripped
        if len(_CJK.findall(cleaned)) < 2 or len(cleaned) > 40:
            return
        if cleaned in seen:
            return
        seen.add(cleaned)
        found.append(cleaned)

    for bracket in re.findall(r"[\[【]([^\[\]【】]+)[\]】]", text):
        for piece in re.split(r"[|｜/]", bracket):
            add(piece)

    body = re.sub(r"[\[【][^\[\]【】]*[\]】]", " ", text)
    for piece in re.split(r"[._\s|｜/]+", body):
        add(piece)

    found.sort(key=len, reverse=True)
    return found
