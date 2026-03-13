#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小宇宙播客每日精选 - 自动搜集、分析并推送到飞书
每天北京时间 22:00 由 GitHub Actions 自动执行
"""

import os
import sys
import json
import ssl
import re
import hashlib
import urllib.request
import subprocess
from datetime import datetime, timezone, timedelta

# Windows 编码修复
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 兼容新旧包名
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

# ── 配置 ──────────────────────────────────────────────────────────────
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/3ec93fad-8609-4dfc-9b0a-8fa413f08943"
BJT = timezone(timedelta(hours=8))

# ── 搜索关键词 ─────────────────────────────���─────────────────────────────
SEARCH_QUERIES = [
    "小宇宙播客 硅谷101 最新一期 内容",
    "小宇宙 AGI Hunt AI 大模型 最新期",
    "小宇宙 枫言枫语 科技 程序员 最新",
    "小宇宙播客 前沿科技 人工智能 最新发布",
    "小宇宙 乱翻书 声动早咖啡 科技商业",
    "小宇宙 科技播客 机器人 具身智能",
    "site:xiaoyuzhoufm.com 科技 AI 播客",
    "小宇宙 播客 DeepSeek 大模型 最新",
    "小宇宙 生物科技 芯片 量子计算 播客",
    "小宇宙 OnBoard 硬地骇客 科技创业 播客",
    "小宇宙 科技播客 2026 最新期 推荐",
    "xiaoyuzhoufm 科技 前沿 最新 episode",
]

# 知名科技播客节目（匹配优先级）
KNOWN_SHOWS = [
    "硅谷101", "AGI Hunt", "枫言枫语", "声动早咖啡", "乱翻书",
    "内核恐慌", "Rexpresso", "OnBoard", "硬地骇客", "科技乱炖",
    "跳进兔子洞", "What's Next 科技早知道", "Steve说", "商业就是这样",
    "泡腾VC", "投资人说", "凹凸曼打怪兽", "张小珺Jùn",
]

# 科技方向标签
TECH_TAGS = {
    "AI/大模型": ["AI", "大模型", "LLM", "GPT", "Claude", "Gemini", "DeepSeek", "Llama", "人工智能", "AGI", "推理模型"],
    "机器人/具身智能": ["机器人", "具身智能", "人形机器人", "宇树", "Figure", "Boston Dynamics", "RaaS"],
    "芯片/半导体": ["芯片", "半导体", "GPU", "英伟达", "台积电", "AMD", "华为昇腾", "寒武纪"],
    "自动驾驶": ["自动驾驶", "FSD", "Waymo", "特斯拉", "端到端", "L4", "智能驾驶"],
    "量子计算": ["量子", "量子计算", "量子比特", "qubit", "Google Willow"],
    "生物科技": ["生物", "基因", "蛋白质", "mRNA", "AlphaFold", "医疗", "药物"],
    "航天": ["航天", "卫星", "SpaceX", "火箭", "星链", "低轨", "商业航天"],
    "科技创业": ["创业", "融资", "估值", "VC", "投资", "startup", "独角兽"],
    "科技商业": ["科技", "商业", "产品", "互联网", "平台", "出海"],
}


# ── 工具函数 ────────────────────────────────────────────────────────────
def send_feishu(title: str, content: list):
    payload = {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": title, "content": content}}}
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        FEISHU_WEBHOOK, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        if result.get("code", -1) != 0:
            raise RuntimeError(f"飞书返回错误: {result}")
    print("飞书推送成功")


def t(text: str) -> dict:
    return {"tag": "text", "text": text}

def a(text: str, href: str) -> dict:
    return {"tag": "a", "text": text, "href": href}


# ── Claude API 配置 ────────────��─────────────────────────────────────────
def _get_reg_value(name: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        result = subprocess.run(
            ["reg", "query", "HKCU\\Environment", "/v", name],
            capture_output=True, text=True, encoding="gbk", errors="ignore"
        )
        for line in result.stdout.split("\n"):
            if name in line and "REG_SZ" in line:
                return line.split("REG_SZ")[-1].strip()
    except Exception:
        pass
    return ""


def get_anthropic_client():
    try:
        import anthropic
        api_key = (
            os.environ.get("ANTHROPIC_API_KEY") or
            os.environ.get("ANTHROPIC_AUTH_TOKEN") or
            _get_reg_value("ANTHROPIC_AUTH_TOKEN")
        )
        base_url = (
            os.environ.get("ANTHROPIC_BASE_URL") or
            _get_reg_value("ANTHROPIC_BASE_URL") or
            None
        )
        if not api_key:
            return None
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**kwargs)
        return client
    except Exception as e:
        print(f"Claude 客户端初始化失败: {e}")
        return None


# ── 搜索 ────────────────────────────────────────────────────────────────
def search_podcasts() -> list:
    results = []
    seen_urls = set()
    print("开始搜索播客信息...")

    with DDGS() as ddgs:
        for query in SEARCH_QUERIES:
            try:
                hits = list(ddgs.text(query, max_results=8))
                for h in hits:
                    url = h.get("href", "")
                    if url not in seen_urls:
                        seen_urls.add(url)
                        results.append({
                            "title": h.get("title", ""),
                            "body": h.get("body", ""),
                            "url": url,
                            "query": query,
                        })
            except Exception as e:
                print(f"搜索 '{query}' 失败: {e}")
                continue

    print(f"共搜集到 {len(results)} 条原始结果")
    return results


# ── Claude 分析 ─────────────────────────────────────────────────────────
def analyze_with_claude(client, raw_results: list) -> list:
    today = datetime.now(BJT).strftime("%Y年%m月%d日")
    raw_text = ""
    for i, r in enumerate(raw_results[:60], 1):
        raw_text += f"\n[{i}] 标题: {r['title']}\n摘要: {r['body'][:300]}\n链接: {r['url']}\n"

    prompt = f"""你是专业科技播客分析师，今天是{today}。

以下是搜索引擎收集到的小宇宙播客平台科技类播客的原始信息：
{raw_text}

请筛选出10条最有价值的前沿科技播客（优先：AI/大模型、机器人、芯片、量子计算、生物科技、航天、科技创业），严格按格式输出：

ITEM_START
节目名称: （如"硅谷101"）
单集标题: （这期具体标题）
核心摘要: （100-150字，有实质内容，禁空话，说清楚讨论了什么、得出了什么结论）
核心观点:
· （关键洞察1）
· （关键洞察2）
· （关键洞察3，可选）
收听链接: （URL）
ITEM_END

共10条，不足则用近期知名科技播客知识补充（节目名后加���知识库】）。覆盖不同方向，不输出其他内容。"""

    print("正在用 Claude 分析...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    return parse_items(message.content[0].text)


def parse_items(text: str) -> list:
    items = []
    blocks = text.split("ITEM_START")
    for block in blocks[1:]:
        block = block.split("ITEM_END")[0].strip()
        item = {"points": []}
        for line in block.split("\n"):
            line = line.strip()
            if line.startswith("节目名称:"):
                item["show"] = line[5:].strip()
            elif line.startswith("单集标题:"):
                item["episode"] = line[5:].strip()
            elif line.startswith("核心摘要:"):
                item["summary"] = line[5:].strip()
            elif line.startswith("核心观点:"):
                pass
            elif line.startswith("·"):
                item["points"].append(line)
            elif line.startswith("收听链接:"):
                item["url"] = line[5:].strip()
        if item.get("show") and item.get("episode"):
            items.append(item)
    return items[:10]


# ── 智能规则提取（无 Claude 时的高质量降级方案）───────────────────────────
def detect_show(title: str, body: str) -> str:
    text = title + " " + body
    for show in KNOWN_SHOWS:
        if show in text:
            return show
    # 正则：「节目名」或【节目名】
    for pat in [r'[「]([^」]+)[」]', r'[【]([^】]+)[】]']:
        m = re.search(pat, title)
        if m and len(m.group(1)) < 20:
            return m.group(1)
    return ""


def detect_tags(title: str, body: str) -> list:
    text = (title + " " + body).lower()
    tags = []
    for tag, keywords in TECH_TAGS.items():
        if any(kw.lower() in text for kw in keywords):
            tags.append(tag)
    return tags[:2]


def is_podcast_content(r: dict) -> bool:
    url = r["url"]
    title = r["title"]
    body = r["body"]
    # 小宇宙直链最优先
    if "xiaoyuzhoufm.com" in url:
        return True
    # 包含已知节目名
    if any(show in title or show in body for show in KNOWN_SHOWS):
        return True
    # 包含科技关键词 + 播客相���词
    tech_hit = any(
        kw in title or kw in body
        for kws in TECH_TAGS.values()
        for kw in kws
    )
    podcast_hit = any(w in title or w in body for w in ["播客", "小宇宙", "podcast", "episode", "Vol.", "EP"])
    return tech_hit and podcast_hit


def clean_episode_title(title: str, show: str) -> str:
    """清理标题，去掉节目名、平台名等冗余"""
    # 去掉 | 后的平台名
    for sep in [" | 小宇宙", " - 小宇宙", " | Podcast", " - Podcast", " | Apple Podcasts"]:
        title = title.split(sep)[0]
    # 去掉节目名前缀
    if show and title.startswith(show):
        title = title[len(show):].lstrip(" -|·—：:")
    # 去掉「」【】内的节目名
    for pat in [f'[「【]{re.escape(show)}[」】]', f'{re.escape(show)}[|·—]']:
        if show:
            title = re.sub(pat, '', title).strip()
    return title.strip() or title


def smart_extract(raw_results: list) -> list:
    """高质量规则提取"""
    print("使用智能规则提取模式")

    # 过滤出播客相关内容
    filtered = [r for r in raw_results if is_podcast_content(r)]
    print(f"过滤后: {len(filtered)} 条相关内容")

    # 优先级排序：小宇宙直链 > 知名节目 > 其他
    def priority(r):
        score = 0
        if "xiaoyuzhoufm.com/episode" in r["url"]:
            score += 100
        elif "xiaoyuzhoufm.com" in r["url"]:
            score += 50
        show = detect_show(r["title"], r["body"])
        if show:
            score += 30
        tags = detect_tags(r["title"], r["body"])
        score += len(tags) * 10
        return -score

    filtered.sort(key=priority)

    # 去重：标题前30字符去重
    seen = set()
    unique = []
    for r in filtered:
        key = r["title"][:30]
        h = hashlib.md5(key.encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(r)

    items = []
    for r in unique[:10]:
        title = r["title"]
        body = r["body"]
        url = r["url"]
        show = detect_show(title, body) or "小宇宙科技播客"
        episode = clean_episode_title(title, show)
        tags = detect_tags(title, body)

        # 摘要：取body前200字，确保句子完整
        summary = body[:250]
        # 截断到最后一个句号
        for end_char in ['。', '！', '？', '…']:
            last = summary.rfind(end_char)
            if last > 80:
                summary = summary[:last + 1]
                break
        else:
            summary = summary[:200] + "…"

        # 生成要点（从body中提取关键句子）
        points = []
        sentences = re.split(r'[。！？；\n]', body)
        for s in sentences:
            s = s.strip()
            if len(s) > 20 and any(kw in s for kws in TECH_TAGS.values() for kw in kws):
                points.append(f"· {s[:60]}")
            if len(points) >= 2:
                break

        items.append({
            "show": show,
            "episode": episode[:60] if episode else title[:60],
            "summary": summary,
            "points": points,
            "url": url,
            "tags": tags,
        })

    return items


# ── 构建飞书消息 ──────────────────────────────────────────────────────────
def build_feishu_content(items: list, used_claude: bool) -> list:
    DIV = [t("─" * 28)]
    today = datetime.now(BJT).strftime("%m月%d日")
    content = [
        [t(f"今日精选10档前沿科技播客，涵盖AI、机器人、芯片、生物科技等方向。")],
        [t(" ")],
    ]
    for i, item in enumerate(items, 1):
        show = item.get("show", "")
        episode = item.get("episode", "")
        summary = item.get("summary", "")
        points = item.get("points", [])
        url = item.get("url", "")
        tags = item.get("tags", [])

        content.append(DIV)
        # 标题行
        tag_str = f"  [{' | '.join(tags)}]" if tags else ""
        content.append([t(f"{i:02d} | {show}{tag_str}")])
        if episode and episode != show:
            content.append([t(f"   {episode[:60]}")])
        if summary:
            content.append([t(f"摘要：{summary}")])
        for pt in points:
            if pt.strip():
                content.append([t(pt)])
        if url and url.startswith("http"):
            content.append([a("收听链接", url)])
        content.append([t(" ")])

    content.append(DIV)
    mode_note = "AI分析" if used_claude else "智能搜索"
    content.append([t(f"整理时间：{datetime.now(BJT).strftime('%Y-%m-%d %H:%M')} BJT | {mode_note} | 来源：小宇宙播客")])
    return content


def send_error_to_feishu(err_msg: str):
    try:
        today = datetime.now(BJT).strftime("%m月%d日")
        send_feishu(f"每日播客推送失败（{today}）", [[t(f"错误：{err_msg[:500]}")]])
    except Exception:
        pass


# ── 主流程 ───────────────────────────────────────────────────────────────
def main():
    print(f"=== 小宇宙播客日报 {datetime.now(BJT).strftime('%Y-%m-%d %H:%M')} BJT ===")
    try:
        # 1. 搜索
        raw_results = search_podcasts()

        # 2. 分析：优先 Claude，降级规则提取
        claude_client = get_anthropic_client()
        used_claude = False
        items = []

        if claude_client:
            try:
                items = analyze_with_claude(claude_client, raw_results)
                used_claude = True
                print(f"Claude 分析完成，得到 {len(items)} 条")
            except Exception as e:
                print(f"Claude 分析失败: {e}，降级到规则提取")

        if not items:
            items = smart_extract(raw_results)
            print(f"规则提取完成，得到 {len(items)} 条")

        if not items:
            raise ValueError("未能提取到任何播客条目")

        # 3. 发送
        today = datetime.now(BJT).strftime("%m月%d日")
        title = f"小宇宙前沿科技播客精选 {today}"
        content = build_feishu_content(items, used_claude)
        send_feishu(title, content)
        print(f"=== 完成，共推送 {len(items)} 条 ===")

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        send_error_to_feishu(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
