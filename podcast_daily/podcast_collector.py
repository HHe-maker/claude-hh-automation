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
import urllib.request
import urllib.parse
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

# ── 搜索关键词 ───────────────────────────────────────────────────────────
SEARCH_QUERIES = [
    "小宇宙播客 硅谷101 最新一期",
    "小宇宙 AGI Hunt AI 大模型 最新",
    "小宇宙 枫言枫语 科技 最新",
    "小宇宙播客 前沿科技 人工智能 最新",
    "小宇宙 乱翻书 声动早咖啡 科技商业",
    "小宇宙 科技播客 机器人 量子计算 芯片",
    "site:xiaoyuzhoufm.com 科技 AI",
    "小宇宙播客 创业 科技 投资 最新期",
    "小宇宙 生物科技 航天 播客",
    "小宇宙播客 DeepSeek 大模型 最新",
    "小宇宙 Agent 具身智能 播客",
    "小宇宙播客 量子计算 自动驾驶 最新",
]

# 知名科技播客节目
KNOWN_SHOWS = [
    "硅谷101", "AGI Hunt", "枫言枫语", "声动早咖啡", "乱翻书",
    "内核恐慌", "Rexpresso", "科技乱炖", "硬地骇客", "OnBoard",
]


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


# ── Claude API 分析（可选，有则用，无则降级）─────────────────────────────
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
    """返回 anthropic.Anthropic 实例，获取不到则返回 None"""
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
        return anthropic.Anthropic(**kwargs)
    except Exception as e:
        print(f"无法初始化 Claude 客户端: {e}")
        return None


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
核心摘要: （100-150字，有实质内容，禁空话）
核心观点:
· （关键洞察1）
· （关键洞察2）
· （关键洞察3，可选）
收听链接: （URL）
ITEM_END

共10条，不足则用近期知名科技播客知识补充（节目名后加【知识库】）。覆盖不同方向，不输出其他内容。"""

    print("正在用 Claude 分析...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = message.content[0].text
    return parse_items(text)


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


# ── 降级：规则提取（不需要 Claude API）──────────────────────────────────
def extract_show_name(title: str, body: str) -> str:
    for show in KNOWN_SHOWS:
        if show in title or show in body:
            return show
    # 尝试从标题提取括号内节目名
    m = re.search(r'[「|【]([^」|】]+)[」|】]', title)
    if m:
        return m.group(1)
    return "小宇宙科技播客"


def is_tech_podcast(title: str, body: str) -> bool:
    tech_keywords = [
        "AI", "人工智能", "大模型", "机器人", "芯片", "量子", "航天", "自动驾驶",
        "科技", "创业", "DeepSeek", "GPT", "Claude", "Anthropic", "OpenAI",
        "硅谷", "播客", "小宇宙", "xiaoyuzhoufm", "AGI", "LLM", "Agent",
        "生物", "基因", "能源", "半导体", "光子", "卫星",
    ]
    text = title + " " + body
    return any(kw.lower() in text.lower() for kw in tech_keywords)


def smart_extract(raw_results: list) -> list:
    """规则提取：无 Claude API 时的降级方案"""
    print("使用规则提取模式（无 Claude API）")

    # 过滤科技相关
    filtered = [r for r in raw_results if is_tech_podcast(r["title"], r["body"])]

    # 优先选小宇宙直链
    priority = [r for r in filtered if "xiaoyuzhoufm.com" in r["url"]]
    others = [r for r in filtered if "xiaoyuzhoufm.com" not in r["url"]]
    ordered = priority + others

    # 去重（标题相似）
    seen_titles = set()
    unique = []
    for r in ordered:
        key = r["title"][:30]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(r)

    items = []
    for r in unique[:10]:
        title = r["title"]
        body = r["body"]
        show = extract_show_name(title, body)

        # 提取单集标题（去掉节目名和括号）
        episode = re.sub(r'[「|【][^」|】]+[」|】]', '', title).strip(" -|·—")
        if not episode or episode == show:
            episode = title[:60]

        # 摘要取前200字
        summary = body[:200].strip()
        if not summary.endswith(('。', '…', '?', '？', '！', '!')):
            summary += "…"

        items.append({
            "show": show,
            "episode": episode,
            "summary": summary,
            "points": [],
            "url": r["url"],
        })

    return items


# ── 构建飞书消息 ──────────────────────────────────────────────────────────
def build_feishu_content(items: list, used_claude: bool) -> list:
    DIV = [t("─" * 28)]
    mode_note = "" if used_claude else "（规则提取模式）"
    content = [
        [t(f"今日精选10档前沿科技播客{mode_note}，涵盖AI、机器人、芯片、生物科技等方向。")],
        [t(" ")],
    ]
    for i, item in enumerate(items, 1):
        show = item.get("show", "未知节目")
        episode = item.get("episode", "")
        summary = item.get("summary", "")
        points = item.get("points", [])
        url = item.get("url", "")

        content.append(DIV)
        header = f"{i:02d} | {show}"
        if episode and episode != show:
            header += f"  {episode[:40]}"
        content.append([t(header)])
        if summary:
            content.append([t(f"摘要：{summary}")])
        for pt in points:
            if pt.strip():
                content.append([t(pt.strip())])
        if url and url.startswith("http"):
            content.append([a("收听链接", url)])
        content.append([t(" ")])

    content.append(DIV)
    content.append([t(f"整理时间：{datetime.now(BJT).strftime('%Y-%m-%d %H:%M')} BJT | 来源：小宇宙播客")])
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

        if claude_client:
            try:
                items = analyze_with_claude(claude_client, raw_results)
                used_claude = True
                print(f"Claude 分析完成，得到 {len(items)} 条")
            except Exception as e:
                print(f"Claude 分析失败: {e}，降级到规则提取")
                items = smart_extract(raw_results)
        else:
            items = smart_extract(raw_results)

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
