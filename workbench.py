#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日工作台生成器 (Daily Workbench)
抓取 5 个数据源，生成自包含 HTML 仪表盘 dashboard.html（并归档到 archive/YYYY-MM-DD.html）。

模块:
  1. AI 日报        -> aihot.virxact.com (今日精选)
  2. 基金涨幅榜+资讯 -> 天天基金(东方财富)公开排行榜 (替代养基宝, 免登录)
  3. 每日财报&招股书 -> 东方财富公告(eastmoney)
  4. AIPM 学习       -> 完整镜像 GitHub 学习路径网页(xiaokaishuibuxing/aipm-learning-path)
  5. GitHub AI 热点  -> github.com/trending 过滤 AI 相关
  6. 行测每日练      -> 粉笔网「行测小讲堂」(/page/.../178) 按日轮换
  7. 申论每日读      -> 粉笔网「申论小讲堂」(/page/.../181) 按日轮换
  8. 雅思单词        -> 本地离线词库(ielts_words.py)，按日轮换 15 词，可翻转/朗读/标记掌握

用法:
  python3 workbench.py            # 生成当日仪表盘
  python3 workbench.py --debug     # 打印抓取诊断
  python3 workbench.py --date 2026-07-24  # 指定基准日(通常用于回测)
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import traceback
import warnings
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

import requests
from bs4 import BeautifulSoup

# ---------------- 配置 ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = BASE_DIR
ARCHIVE_DIR = os.path.join(BASE_DIR, "archive")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 禁用 requests verify=False 时的不安全 HTTPS 警告
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

S = requests.Session()
S.headers.update({"User-Agent": UA,
                 "Accept": "text/html,application/xhtml+xml,application/json,*/*",
                 "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

DEBUG = False
STATUS = {}  # 模块状态: name -> (ok:bool, msg:str)


def log(*a):
    if DEBUG:
        print("[debug]", *a, file=sys.stderr)


def set_status(name, ok, msg=""):
    STATUS[name] = (ok, msg)


# ---------------- 1. AI 日报 (aihot) ----------------
def fetch_aihot():
    try:
        r = S.get("https://aihot.virxact.com/", timeout=25)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "lxml")
        groups = soup.select(".m-daygroup")
        target = groups[0] if groups else soup
        rows = []
        for wrap in target.select(".m-row-wrap"):
            a = wrap.select_one("a.m-row")
            if not a:
                continue
            href = a.get("href", "")
            time_el = wrap.select_one(".m-row-time")
            src_el = wrap.select_one(".m-row-src")
            score_el = wrap.select_one(".m-score")
            title_el = wrap.select_one(".m-row-title")
            sum_el = wrap.select_one(".m-row-summary")
            tags = [t.get_text(strip=True) for t in wrap.select(".m-row-tag, .m-tag") if t.get_text(strip=True)]
            url = href if href.startswith("http") else "https://aihot.virxact.com" + href
            rows.append({
                "time": time_el.get_text(strip=True) if time_el else "",
                "source": src_el.get_text(strip=True) if src_el else "",
                "score": score_el.get_text(strip=True) if score_el else "",
                "title": title_el.get_text(strip=True) if title_el else "",
                "summary": sum_el.get_text(strip=True) if sum_el else "",
                "tags": tags,
                "url": url,
            })
        if not rows:
            set_status("aihot", False, "未解析到今日条目")
            return []
        set_status("aihot", True, f"{len(rows)} 条")
        return rows[:18]
    except Exception as e:
        set_status("aihot", False, str(e))
        log("aihot error", traceback.format_exc())
        return []


# ---------------- 2. 基金涨幅榜 + 资讯 (天天基金) ----------------
def _fund_day(date_str):
    """返回某交易日排行榜 list[dict]，无数据返回 []"""
    tab = ",,,,"
    url = "https://fund.eastmoney.com/data/rankhandler.aspx"
    params = {"op": "ph", "dt": "kf", "ft": "all", "rs": "", "gs": "0",
              "sc": "zzf", "st": "desc", "sd": date_str, "ed": date_str,
              "qdii": "", "tabSubtype": tab, "pi": "1", "pn": "20", "dx": "1",
              "v": "0.123456"}
    r = S.get(url, params=params, headers={"Referer": "https://fund.eastmoney.com/"}, timeout=25)
    if len(r.text) < 50:
        return []
    m = re.search(r"datas:\s*(\[.*?\])\s*[,}]", r.text, re.S)
    if not m:
        return []
    arr = json.loads(m.group(1))  # list of CSV strings
    out = []
    for s in arr[:20]:
        f = s.split(",")
        if len(f) < 7:
            continue
        out.append({
            "code": f[0],
            "name": f[1],
            "nav": f[4],
            "gain": f[6],          # 日增长率
            "week": f[7] if len(f) > 7 else "",
            "month": f[8] if len(f) > 8 else "",   # 近1月 ≈ 近30天涨幅
            "year": f[13] if len(f) > 13 else "",
        })
    return out


def fetch_fund_ranking(base_date):
    """回退到最近交易日"""
    try:
        for back in range(0, 8):
            d = (base_date - timedelta(days=back)).strftime("%Y-%m-%d")
            rows = _fund_day(d)
            if rows:
                set_status("fund", True, f"{d} 交易日 {len(rows)} 只")
                return {"date": d, "rows": rows}
        set_status("fund", False, "近8日无交易日数据")
        return {"date": "", "rows": []}
    except Exception as e:
        set_status("fund", False, str(e))
        log("fund error", traceback.format_exc())
        return {"date": "", "rows": []}


def fetch_fund_news():
    """养基宝资讯的替代源：东方财富基金快讯/新浪基金，多源兜底"""
    # 1) 东方财富基金快讯 API
    try:
        u = "https://np-anotice-stock.eastmoney.com/api/content/headline"
        r = S.get(u, params={"client": "web", "pagesize": "12", "ut": "0"}, timeout=15)
        if r.status_code == 200:
            j = r.json()
            items = (j.get("data") or {}).get("list") or []
            if items:
                out = []
                for it in items[:10]:
                    out.append({"title": it.get("title", ""),
                                "url": it.get("url", ""),
                                "time": it.get("showtime", "")})
                if out:
                    set_status("fundnews", True, f"东财快讯 {len(out)} 条")
                    return out
    except Exception as e:
        log("fundnews eastmoney err", e)
    # 2) 新浪基金新闻页（响应头未声明 charset，实际为 UTF-8，需显式用 apparent_encoding）
    try:
        r = S.get("https://finance.sina.com.cn/fund/", timeout=15)
        if r.status_code == 200:
            r.encoding = r.apparent_encoding
            soup = BeautifulSoup(r.text, "lxml")
            out = []
            seen = set()
            for a in soup.select("a[href*='fund']"):
                t = a.get_text(strip=True)
                h = a.get("href", "")
                if t and len(t) > 8 and t not in seen and h.startswith("http"):
                    seen.add(t)
                    out.append({"title": t, "url": h, "time": ""})
                if len(out) >= 10:
                    break
            if out:
                set_status("fundnews", True, f"新浪基金 {len(out)} 条")
                return out
    except Exception as e:
        log("fundnews sina err", e)
    set_status("fundnews", False, "资讯源暂不可用")
    return []


# ---------------- 3. 每日财报 & 招股书 (东方财富公告) ----------------
import html as _html
EM_ANN = "https://np-anotice-stock.eastmoney.com/api/security/ann"
# 真实定期报告 / 业绩预告 的栏目特征（排除问询函、评级、担保等噪声）
REPORT_COL_RE = re.compile(r"(半年度报告|年度报告|季度报告|年度财务报告|业绩预告)")


def _em_ann(title, srdate, n=50):
    """东方财富公告接口：按标题关键词 + 起始日拉取，返回 list[item]"""
    params = {"srdate": srdate, "page_size": str(n), "page_index": "1",
              "ann_type": "A", "client_source": "web", "title": title}
    try:
        r = S.get(EM_ANN, params=params,
                  headers={"Referer": "https://data.eastmoney.com/"}, timeout=25)
        if r.status_code != 200:
            return []
        j = r.json()
        return (j.get("data") or {}).get("list") or []
    except Exception as e:
        log("em_ann error", e)
        return []


def _clean_title(t):
    return _html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()


def _ann_url(it):
    codes = it.get("codes") or []
    code = (codes[0].get("stock_code") if codes else "") or ""
    ac = it.get("art_code", "")
    if code and ac:
        return f"https://data.eastmoney.com/notices/detail/{code}/{ac}.html"
    return "https://data.eastmoney.com/"


def _first_code(it):
    codes = it.get("codes") or [{}]
    return codes[0].get("short_name", ""), codes[0].get("stock_code", "")


def _col_name(it):
    cols = it.get("columns") or []
    return cols[0].get("column_name", "") if cols else ""


def fetch_financial(base_date):
    try:
        # 招股书：标题含「招股说明书」，栏目为招股书类
        zg_items = _em_ann("招股说明书", base_date.strftime("%Y-%m-%d"), 30)
        prospectus = None
        for it in zg_items:
            cn = _col_name(it)
            if "招股说明书" in cn or "招股意向书" in cn:
                comp, code = _first_code(it)
                prospectus = {
                    "title": _clean_title(it.get("title", "")),
                    "company": comp, "code": code,
                    "url": _ann_url(it),
                    "date": (it.get("notice_date") or "")[:10],
                }
                break
        # 财报：扩大窗口，按栏目精准过滤真实定期报告
        sr = (base_date - timedelta(days=30)).strftime("%Y-%m-%d")
        rep_items = _em_ann("报告", sr, 80)
        report = None
        for it in rep_items:
            cn = _col_name(it)
            if REPORT_COL_RE.search(cn):
                comp, code = _first_code(it)
                report = {
                    "title": _clean_title(it.get("title", "")),
                    "company": comp, "code": code,
                    "url": _ann_url(it),
                    "date": (it.get("notice_date") or "")[:10],
                }
                break
        if prospectus or report:
            set_status("financial", True,
                       f"招股书{'有' if prospectus else '无'} / 财报{'有' if report else '无'}")
        else:
            set_status("financial", False, "近30日无匹配公告")
        return {"prospectus": prospectus, "report": report}
    except Exception as e:
        set_status("financial", False, str(e))
        log("financial error", traceback.format_exc())
        return {"prospectus": None, "report": None}


# ---------------- 4. AIPM 学习 (完整镜像 GitHub 仓库网页) ----------------
AIPM_REPO = "xiaokaishuibuxing/aipm-learning-path"
AIPM_GITHUB_API = f"https://api.github.com/repos/{AIPM_REPO}/contents/index.html"
AIPM_GITHUB_PAGE = f"https://github.com/{AIPM_REPO}"
AIPM_CACHE = os.path.join(BASE_DIR, "aipm_cache.json")

# AIPM 学习任务讲解（AI 生成，按任务标题精确匹配）
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("aipm_lessons", os.path.join(BASE_DIR, "aipm_lessons.py"))
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    AIPM_LESSONS = getattr(_mod, "AIPM_LESSONS", {})
except Exception:
    AIPM_LESSONS = {}


# 雅思核心词库 (本地离线，不依赖外部 API)
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("ielts_words", os.path.join(BASE_DIR, "ielts_words.py"))
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    IELTS_WORDS = getattr(_mod, "IELTS_WORDS", [])
except Exception:
    IELTS_WORDS = []


def _load_aipm_cache():
    try:
        with open(AIPM_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_aipm_cache(data):
    try:
        with open(AIPM_CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _fetch_aipm_full():
    """抓取 GitHub 仓库 index.html，完整解析四阶段学习路径 + 面试题，镜像原网页。"""
    r = S.get(AIPM_GITHUB_API, timeout=25, verify=False)
    if r.status_code != 200:
        raise Exception(f"GitHub API status {r.status_code}")
    j = r.json()
    content = j.get("content", "")
    if not content:
        raise Exception("GitHub API 无内容")
    text = base64.b64decode(content).decode("utf-8")
    soup = BeautifulSoup(text, "lxml")

    # 阶段概览 (导航 rail)
    phases = []
    for ph in soup.find_all(class_="jj-phase"):
        num = ph.find(class_="jj-phase-num")
        weeks = ph.find(class_="jj-phase-weeks")
        title = ph.find(class_="jj-phase-title")
        desc = ph.find(class_="jj-phase-desc")
        badge = ph.find(class_="jj-phase-badge")
        phases.append({
            "num": num.get_text(strip=True) if num else "",
            "weeks": weeks.get_text(" ", strip=True) if weeks else "",
            "title": title.get_text(" ", strip=True) if title else "",
            "desc": desc.get_text(" ", strip=True) if desc else "",
            "badge": badge.get_text(strip=True) if badge else "",
        })

    # 每个阶段详情：任务清单 + 推荐资源
    blocks = []
    total_tasks = 0
    for i in range(1, 5):
        sec = soup.find(id=f"phase{i}")
        if not sec:
            continue
        meta = phases[i - 1] if i - 1 < len(phases) else {}
        tasks = []
        for item in sec.find_all(class_="jj-task-item"):
            txt = item.find(class_="jj-task-text")
            if txt:
                tasks.append({"text": txt.get_text(" ", strip=True), "time": item.get("data-time", "")})
        total_tasks += len(tasks)
        resources = []
        for rc in sec.find_all(class_="jj-resource-card"):
            t = rc.find(class_="jj-resource-title")
            sub = rc.find(class_="jj-resource-sub")
            typ = rc.find(class_="jj-resource-type-tag")
            a = rc if rc.name == "a" else rc.find("a")
            href = rc.get("href", "") or (a.get("href", "") if a else "")
            resources.append({
                "title": t.get_text(strip=True) if t else "",
                "sub": sub.get_text(strip=True) if sub else "",
                "type": typ.get_text(strip=True) if typ else "",
                "url": href,
            })
        blocks.append({
            "idx": i,
            "num": meta.get("num", f"阶段 {i}"),
            "title": meta.get("title", f"阶段 {i}"),
            "weeks": meta.get("weeks", ""),
            "badge": meta.get("badge", ""),
            "desc": meta.get("desc", ""),
            "tasks": tasks,
            "resources": resources,
        })

    # 高频面试题
    interview = []
    interview_sec = soup.find(id="interview")
    if interview_sec:
        for card in interview_sec.find_all(class_="jj-interview-card"):
            tag = card.find(class_="jj-interview-tag")
            q = card.find(class_="jj-interview-q")
            hint = card.find(class_="jj-interview-hint")
            ans = card.find(class_="jj-interview-answer-body")
            interview.append({
                "tag": tag.get_text(strip=True) if tag else "",
                "q": q.get_text(" ", strip=True) if q else "",
                "hint": hint.get_text(" ", strip=True) if hint else "",
                "answer": ans.get_text(" ", strip=True) if ans else "",
            })

    data = {
        "repo_url": AIPM_GITHUB_PAGE,
        "phases": phases,
        "blocks": blocks,
        "interview": interview,
        "total_tasks": total_tasks,
    }
    if not blocks:
        raise Exception("未解析到阶段内容")
    _save_aipm_cache(data)
    return data


def fetch_aipm(base_date):
    """优先抓取最新网页；抓取失败时回退本地缓存。"""
    try:
        data = _fetch_aipm_full()
        set_status("aipm", True,
                   f"{len(data['blocks'])} 阶段 · {data['total_tasks']} 任务 · {len(data['interview'])} 面试题")
        return data
    except Exception as e:
        cached = _load_aipm_cache()
        if cached and cached.get("blocks"):
            set_status("aipm", True, "使用本地缓存(抓取失败)")
            return cached
        set_status("aipm", False, str(e))
        log("aipm error", traceback.format_exc())
        return {"repo_url": AIPM_GITHUB_PAGE, "phases": [], "blocks": [], "interview": [], "total_tasks": 0}


# ---------------- 5. GitHub AI 热点 ----------------
AI_KW = ["ai", "llm", "agent", "gpt", " ml", "ml-", "model", "rag", "diffusion",
         "neural", "llama", "claude", "copilot", "transformer", "embedding",
         "inference", "fine-tun", "chatbot", "vision", "speech", "deep learning",
         "pytorch", "tensorflow", "gan", "nlp", "openai", "anthropic", "gemini"]


def fetch_github():
    try:
        r = S.get("https://github.com/trending?since=daily", timeout=25)
        soup = BeautifulSoup(r.text, "lxml")
        out = []
        for rep in soup.select("article.Box-row"):
            a = rep.select_one("h2 a")
            if not a:
                continue
            href = a.get("href", "").strip()
            desc_el = rep.select_one("p")
            lang_el = rep.select_one("span[itemprop=programmingLanguage]")
            stars_el = rep.select_one("a[href$=stargazers]")
            txt = rep.get_text(" ", strip=True)
            m_today = re.search(r"([\d,]+)\s+stars today", txt)
            title = a.get_text(" ", strip=True).replace("\n", "/").strip()
            desc = desc_el.get_text(strip=True) if desc_el else ""
            lang = lang_el.get_text(strip=True) if lang_el else ""
            total = stars_el.get_text(strip=True).replace(",", "") if stars_el else ""
            today = m_today.group(1) if m_today else ""
            blob = (title + " " + desc + " " + lang).lower()
            is_ai = any(k in blob for k in AI_KW)
            out.append({
                "repo": title, "url": "https://github.com" + href,
                "desc": desc, "lang": lang, "total": total,
                "today": today, "ai": is_ai,
            })
        ai = [x for x in out if x["ai"]]
        final = ai if len(ai) >= 6 else out
        set_status("github", True, f"{len(final)} 个(其中AI {len(ai)})")
        return final[:12]
    except Exception as e:
        set_status("github", False, str(e))
        log("github error", traceback.format_exc())
        return []


# ---------------- 6 & 7. 行测 / 申论 (粉笔网 fenbi.com) ----------------
FENBI_XINGCE_LIST = "https://www.fenbi.com/page/exams-preparation-materials-list/178"
FENBI_SHENLUN_LIST = "https://www.fenbi.com/page/exams-preparation-materials-list/181"
_DETAIL_RE = re.compile(r"/exam-preparation-material-detail/(\d+)/(\d+)")


def _fenbi_pick(list_url, cat_id, kind, base_date):
    name = "xingce" if cat_id == "178" else "shenlun"
    try:
        r = S.get(list_url, timeout=25)
        if r.status_code != 200:
            set_status(name, False, f"列表页 {r.status_code}")
            return None
        soup = BeautifulSoup(r.content, "lxml")
        urls = []
        for a in soup.find_all("a", href=True):
            m = _DETAIL_RE.search(a["href"])
            if m and m.group(1) == cat_id:
                h = a["href"]
                urls.append(h if h.startswith("http") else "https://www.fenbi.com" + h)
        # 去重保序
        seen, uniq = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u); uniq.append(u)
        urls = uniq
        if not urls:
            set_status(name, False, "列表无条目")
            return None
        idx = base_date.timetuple().tm_yday % len(urls)
        detail_url = urls[idx]
        d = S.get(detail_url, timeout=25)
        dsoup = BeautifulSoup(d.content, "lxml")
        title_el = dsoup.find("title")
        title = (title_el.get_text(" ", strip=True) if title_el else "未命名")
        title = title.replace("--粉笔资讯", "").replace("--粉笔", "").strip()
        cont = dsoup.select_one(".exam-preparation-materials-detail-content-container")
        opening = ""
        if cont:
            txt = cont.get_text(" ", strip=True)
            txt = txt.replace(title, "")
            txt = re.sub(r"\s+", " ", txt).strip()
            opening = txt[:180]
        set_status(name, True, f"{kind} 第{idx+1}/{len(urls)}篇")
        return {"title": title, "opening": opening, "url": detail_url,
                "index": idx + 1, "total": len(urls), "kind": kind}
    except Exception as e:
        set_status(name, False, str(e))
        log(f"{name} error", traceback.format_exc())
        return None


def fetch_xingce(base_date):
    return _fenbi_pick(FENBI_XINGCE_LIST, "178", "行测", base_date)


def fetch_shenlun(base_date):
    return _fenbi_pick(FENBI_SHENLUN_LIST, "181", "申论", base_date)


# ---------------- 雅思单词 (本地离线词库，按日轮换) ----------------
def fetch_ielts(base_date):
    try:
        words_all = list(IELTS_WORDS)
        if not words_all:
            raise Exception("词库为空")
        n = 15
        total = len(words_all)
        groups = (total + n - 1) // n
        day_idx = base_date.timetuple().tm_yday
        g = day_idx % groups
        start = g * n
        sel = words_all[start:start + n]
        if len(sel) < n:
            sel += words_all[:n - len(sel)]
        set_status("ielts", True, f"第 {g + 1}/{groups} 组 · {len(sel)} 词")
        return {"words": sel, "idx": g + 1, "total_groups": groups}
    except Exception as e:
        set_status("ielts", False, str(e))
        return {"words": []}


# ---------------- iCloud 同步 (iOS 文件 App 查看) ----------------
def sync_icloud(out_path):
    try:
        icloud = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")
        if not os.path.isdir(icloud):
            return False, "当前 Mac 未启用 iCloud Drive，跳过同步"
        dest_dir = os.path.join(icloud, "Workbench")
        os.makedirs(dest_dir, exist_ok=True)
        import shutil
        shutil.copy2(out_path, os.path.join(dest_dir, "dashboard.html"))
        return True, dest_dir
    except Exception as e:
        return False, f"iCloud 同步失败: {e}"


# ---------------- HTML 生成 ----------------
CSS = """
:root{--bg:#fff2f8;--card:#ffffff;--ink:#3a2b33;--sub:#9a7f8c;--line:#f6e1ec;
--accent:#e85a9b;--green:#1f9d55;--red:#d8442f;--chip:#ffe9f3;--shadow:0 1px 3px rgba(214,120,170,.10);
--sidebar-active:#ec6aa6;--sidebar-active-text:#ffffff;--sidebar-hover:#fdeef5;
--page-bg:radial-gradient(120% 120% at 15% 8%, #fff7fb 0%, transparent 46%), linear-gradient(135deg,#ffe6f2 0%,#ffd3e8 45%,#f1d9ff 100%)}
[data-theme=dark]{--bg:#16181d;--card:#1f232b;--ink:#e6e8ec;--sub:#9aa3b2;--line:#2c313a;
--accent:#5b8bff;--green:#34d27b;--red:#ff6b54;--chip:#232a36;--shadow:0 1px 3px rgba(0,0,0,.4);
--sidebar-active:#8cae62;--sidebar-active-text:#11151a;--sidebar-hover:#252b33;
--page-bg:linear-gradient(135deg,#1b1e25,#14161b)}
*{box-sizing:border-box}html,body{margin:0;height:100%;overflow:hidden;background:var(--page-bg,var(--bg));background-attachment:fixed;color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
font-size:15px;line-height:1.55}
.app{display:flex;height:100vh;width:100vw}
/* sidebar */
.sidebar{width:260px;flex-shrink:0;background:var(--card);border-right:1px solid var(--line);
display:flex;flex-direction:column;padding:22px 12px 16px;transition:transform .25s ease}
.brand{display:flex;align-items:center;gap:12px;padding:0 8px 18px;border-bottom:1px solid var(--line);margin-bottom:12px}
.avatar{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,#6b8c42,#9db36b);
display:flex;align-items:center;justify-content:center;font-size:22px;color:#fff;flex-shrink:0}
.brand-text{display:flex;flex-direction:column}
.brand-name{font-size:17px;font-weight:700;color:var(--ink)}
.brand-sub{font-size:12px;color:var(--sub);margin-top:2px}
.nav-list{flex:1;overflow:auto;padding:4px 0}
.nav-item{display:flex;align-items:center;gap:12px;padding:12px 14px;margin:2px 6px;border-radius:12px;
cursor:pointer;color:var(--ink);transition:background .15s, color .15s}
.nav-item:hover{background:var(--sidebar-hover)}
.nav-item.active{background:var(--sidebar-active);color:var(--sidebar-active-text);box-shadow:0 2px 8px rgba(107,140,66,.35)}
.nav-item.active .nav-sub{color:rgba(255,255,255,.85)}
.nav-icon{font-size:20px;width:26px;text-align:center;flex-shrink:0}
.nav-text{flex:1;display:flex;flex-direction:column}
.nav-title{font-weight:600;font-size:14.5px}
.nav-sub{font-size:11px;color:var(--sub);margin-top:1px}
.sidebar-footer{padding:10px 8px 0;font-size:11px;color:var(--sub);line-height:1.5}
/* main */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.topbar{height:64px;background:var(--card);border-bottom:1px solid var(--line);display:flex;
align-items:center;justify-content:space-between;padding:0 22px;flex-shrink:0}
.topbar-left{display:flex;align-items:center;gap:14px}
.menu-toggle{display:none;background:transparent;border:1px solid var(--line);border-radius:8px;
padding:6px 10px;font-size:18px;cursor:pointer}
.page-date{font-size:16px;font-weight:600;color:var(--ink)}
.page-weekday{font-size:13px;color:var(--sub)}
.topbar-right{display:flex;align-items:center;gap:10px}
.btn{display:inline-flex;align-items:center;gap:6px;background:var(--chip);color:var(--ink);
border:1px solid var(--line);border-radius:10px;padding:7px 13px;cursor:pointer;font-size:13px;
transform:translateY(0);transition:all .15s}
.btn:hover{background:var(--sidebar-hover)}
.btn-primary{background:var(--sidebar-active);color:var(--sidebar-active-text);border-color:var(--sidebar-active)}
.btn-primary:hover{filter:brightness(1.08)}
.content{flex:1;overflow:auto;padding:22px 26px 40px}
.section{display:none;max-width:980px;margin:0 auto;animation:fadeIn .25s ease}
.section.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.section-title{font-size:24px;font-weight:700;margin:0 0 4px}
.section-sub{color:var(--sub);font-size:14px;margin-bottom:18px}
.ielts-bar{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.ielts-progress{font-size:14px;color:var(--sub)}
.ielts-progress b{color:var(--accent)}
.ielts-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.ielts-card{background:var(--chip);border:1px solid var(--line);border-radius:14px;padding:14px 16px;cursor:pointer;transition:all .15s}
.ielts-card:hover{box-shadow:var(--shadow);transform:translateY(-2px)}
.ielts-wordrow{display:flex;align-items:center;justify-content:space-between;gap:8px}
.ielts-word{font-size:19px;font-weight:700;color:var(--ink)}
.ielts-spk{border:none;background:transparent;font-size:16px;cursor:pointer;padding:2px 4px;border-radius:8px}
.ielts-spk:hover{background:var(--sidebar-hover)}
.ielts-phon{color:var(--sub);font-size:13px;margin:4px 0 6px;font-style:italic}
.ielts-hint{font-size:12px;color:var(--accent);user-select:none}
.ielts-back{margin-top:10px;border-top:1px dashed var(--line);padding-top:10px}
.ielts-pos{font-weight:600;color:var(--green);font-size:14px;margin-bottom:6px}
.ielts-ex{font-size:13px;color:var(--ink);line-height:1.5;margin-bottom:4px}
.ielts-exzh{font-size:12px;color:var(--sub);line-height:1.5;margin-bottom:10px}
.ielts-master{width:100%;border:1px solid var(--line);background:var(--card);color:var(--ink);
border-radius:10px;padding:7px;cursor:pointer;font-size:13px;transition:all .15s}
.ielts-master:hover{background:var(--sidebar-hover)}
.ielts-master.done{background:var(--green);color:#fff;border-color:var(--green)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px;
box-shadow:var(--shadow);margin-bottom:16px}
.card h2{margin:0 0 12px;font-size:17px;display:flex;align-items:center;gap:8px}
.badge{font-size:11px;padding:2px 8px;border-radius:20px;background:var(--chip);color:var(--sub)}
.ok{color:var(--green)}.warn{color:var(--red)}
ul{list-style:none;margin:0;padding:0}
li{padding:9px 0;border-bottom:1px dashed var(--line)}
li:last-child{border-bottom:none}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.muted{color:var(--sub);font-size:13px}
.row{display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.gain{font-weight:700}.up{color:var(--red)}.down{color:var(--green)}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:6px 7px;border-bottom:1px solid var(--line)}
th{color:var(--sub);font-weight:600;font-size:12px}
.tag{display:inline-block;background:var(--chip);color:var(--sub);font-size:11px;
border-radius:6px;padding:1px 7px;margin:1px 2px}
.src{color:var(--sub);font-size:12px}
.score{background:var(--chip);border-radius:6px;padding:1px 7px;font-size:12px;color:var(--accent)}
.pick{background:linear-gradient(135deg,var(--chip),transparent);border-radius:12px;
padding:14px 16px;margin-bottom:12px}
.pick .t{font-weight:700;font-size:16px;margin:4px 0}
.note{font-size:12px;color:var(--sub);margin-top:8px}
.scroll{max-height:520px;overflow:auto}
footer{color:var(--sub);font-size:11.5px;text-align:center;padding:18px 0 8px}
/* 每日计划页 */
.plan-list{display:grid;gap:10px}
.plan-item{display:flex;align-items:center;gap:14px;background:var(--card);border:1px solid var(--line);
border-radius:14px;padding:13px 16px;cursor:pointer;transition:transform .1s, box-shadow .15s}
.plan-item:hover{transform:translateY(-1px);box-shadow:var(--shadow)}
.plan-icon{font-size:22px;width:30px;text-align:center}
.plan-info{flex:1}
.plan-title{font-weight:600;font-size:15px}
.plan-desc{font-size:12px;color:var(--sub);margin-top:2px}
.plan-status{font-size:12px;color:var(--sub);white-space:nowrap}
.plan-check{width:22px;height:22px;border:2px solid var(--line);border-radius:50%;
display:flex;align-items:center;justify-content:center;font-size:13px;color:#fff;flex-shrink:0;
transition:all .15s}
.plan-check.done{background:var(--sidebar-active);border-color:var(--sidebar-active)}
.progress-bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin-top:14px}
.progress-fill{height:100%;background:var(--sidebar-active);border-radius:4px;transition:width .4s ease}
.progress-text{font-size:12px;color:var(--sub);margin-top:6px}
/* 我的任务 / 备忘 */
.todo-wrap{margin-top:22px;border-top:1px solid var(--line);padding-top:18px}
.todo-add{display:flex;gap:8px;margin:12px 0}
.todo-input{flex:1;border:1px solid var(--line);border-radius:10px;padding:9px 12px;font-size:14px;
background:var(--bg);color:var(--ink);font-family:inherit}
.todo-input:focus{outline:none;border-color:var(--sidebar-active)}
.todo-list{margin-top:4px}
.todo-item{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px dashed var(--line)}
.todo-item:last-child{border-bottom:none}
.todo-box{width:20px;height:20px;border:2px solid var(--line);border-radius:6px;flex-shrink:0;
display:flex;align-items:center;justify-content:center;font-size:12px;color:#fff;cursor:pointer;
transition:all .15s}
.todo-box.done{background:var(--sidebar-active);border-color:var(--sidebar-active)}
.todo-text{flex:1;font-size:14px}
.todo-text.done{text-decoration:line-through;color:var(--sub)}
.todo-del{color:var(--sub);cursor:pointer;font-size:14px;padding:2px 6px;border-radius:6px}
.todo-del:hover{background:var(--sidebar-hover);color:var(--red)}
.memo{width:100%;min-height:90px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;
font-size:14px;background:var(--bg);color:var(--ink);font-family:inherit;resize:vertical;line-height:1.5}
.memo:focus{outline:none;border-color:var(--sidebar-active)}
.memo-wrap{margin-top:18px}
/* mobile */
@media (max-width:860px){
  .sidebar{position:fixed;left:0;top:0;bottom:0;z-index:100;transform:translateX(-100%)}
  .sidebar.open{transform:translateX(0)}
  .overlay{position:fixed;inset:0;background:rgba(0,0,0,.25);z-index:99;display:none}
  .overlay.open{display:block}
  .menu-toggle{display:inline-flex}
  .content{padding:16px}
  .page-date{font-size:14px}
}
/* AIPM 学习路径 (镜像 GitHub 网页) */
.aipm-hero{margin-bottom:16px}
.aipm-hero-title{font-size:18px;font-weight:700;margin-bottom:4px}
.aipm-rail{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}
.aipm-chip{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 13px;box-shadow:var(--shadow)}
.aipm-chip-num{font-size:11px;color:var(--sub);font-weight:600;letter-spacing:.5px}
.aipm-chip-title{font-size:15px;font-weight:700;margin:3px 0 2px}
.aipm-chip-meta{font-size:12px;color:var(--sub)}
.aipm-blocks{display:grid;gap:14px}
.aipm-block{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 18px;box-shadow:var(--shadow)}
.aipm-block-head{display:flex;gap:12px;align-items:flex-start;margin-bottom:12px}
.aipm-block-idx{font-size:12px;font-weight:700;color:var(--sidebar-active-text);background:var(--sidebar-active);
border-radius:10px;padding:5px 9px;white-space:nowrap;flex-shrink:0}
.aipm-block-title{font-size:16px;font-weight:700}
.aipm-tasklist{display:grid;gap:2px}
.aipm-task{display:flex;align-items:center;gap:10px;padding:9px 4px;border-bottom:1px dashed var(--line);cursor:pointer}
.aipm-task:last-child{border-bottom:none}
.aipm-task input{width:18px;height:18px;accent-color:var(--sidebar-active);flex-shrink:0;cursor:pointer}
.aipm-task-txt{flex:1;font-size:14px}
.aipm-task input:checked ~ .aipm-task-txt{text-decoration:line-through;color:var(--sub)}
.aipm-task-time{font-size:12px;color:var(--sub);white-space:nowrap;flex-shrink:0}
.aipm-task-row{display:flex;align-items:center;gap:8px}
.aipm-task{flex:1}
.aipm-video{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:8px;background:var(--bg);border:1px solid var(--line);font-size:15px;text-decoration:none;flex-shrink:0;transition:.15s}
.aipm-video:hover{background:var(--sidebar-active);border-color:var(--sidebar-active);transform:translateY(-1px)}
.aipm-task-wrap{padding:4px 0;border-bottom:1px dashed var(--line)}
.aipm-task-wrap:last-child{border-bottom:none}
.aipm-note{margin:6px 0 4px 28px;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:6px 12px}
.aipm-note>summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--sidebar-active);list-style:none}
.aipm-note>summary::-webkit-details-marker{display:none}
.aipm-note-sum{font-size:13px;color:var(--fg);margin:6px 0 4px;line-height:1.6}
.aipm-note-pts{margin:0;padding-left:18px}
.aipm-note-pts li{font-size:13px;color:var(--fg);line-height:1.7;margin:2px 0}
.aipm-res-label{font-size:12px;font-weight:600;color:var(--sub);margin:12px 0 6px}

.aipm-res-list{display:grid;gap:8px}
.aipm-res{display:flex;align-items:center;gap:10px;background:var(--bg);border:1px solid var(--line);border-radius:12px;
padding:10px 12px;text-decoration:none;color:var(--ink);transition:transform .1s,box-shadow .15s}
.aipm-res:hover{transform:translateY(-1px);box-shadow:var(--shadow);text-decoration:none}
.aipm-res-type{font-size:11px;background:var(--chip);color:var(--sub);border-radius:6px;padding:2px 7px;flex-shrink:0}
.aipm-res-body{flex:1;display:flex;flex-direction:column}
.aipm-res-title{font-size:14px;font-weight:600}
.aipm-res-sub{font-size:12px;color:var(--sub)}
.aipm-res-arrow{color:var(--sub);font-size:14px}
.aipm-iv{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin-bottom:8px}
.aipm-iv summary{display:flex;gap:10px;align-items:flex-start;cursor:pointer;list-style:none}
.aipm-iv summary::-webkit-details-marker{display:none}
.aipm-iv-tag{font-size:11px;background:var(--chip);color:var(--sub);border-radius:6px;padding:2px 7px;flex-shrink:0;height:fit-content}
.aipm-iv-q{font-size:14px;font-weight:600;flex:1}
.aipm-iv-body{padding:10px 0 2px 38px;font-size:13.5px;line-height:1.6}
.aipm-iv-row{margin-top:8px}
.aipm-iv-row b{color:var(--ink)}
@media (max-width:860px){.aipm-rail{grid-template-columns:repeat(2,1fr)}}
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_html(date_str, aihot, fund, fundnews, financial, aipm, github, xingce, shenlun, ielts):
    # 模块元信息 (icon, title, subtitle, key)
    modules = [
        ("🗓️", "每日计划", "完成一项打勾，进度一目了然", "dailyplan"),
        ("🤖", "AI 日报", "aihot 每日精选", "aihot"),
        ("📈", "基金涨幅榜", "Top20 日/近30天涨幅", "fund"),
        ("📰", "基金资讯", "每日基金要闻", "fundnews"),
        ("📄", "财报 & 招股书", "东方财富公告", "financial"),
        ("🎓", "AIPM 学习", "学习路径", "aipm"),
        ("🐙", "GitHub AI 热点", "trending 过滤", "github"),
        ("📝", "行测每日练", "粉笔小讲堂", "xingce"),
        ("📖", "申论每日读", "粉笔小讲堂", "shenlun"),
        ("🇬🇧", "雅思单词", "每日15词", "ielts"),
    ]

    # ---- AI 日报 ----
    ai_items = ""
    for it in aihot:
        tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in it["tags"])
        meta = f'<span class="src">{esc(it["time"])} · {esc(it["source"])}</span>'
        if it["score"]:
            meta += f' <span class="score">{esc(it["score"])}</span>'
        sumtxt = f'<div class="muted">{esc(it["summary"])}</div>' if it["summary"] else ""
        ai_items += (f'<li><div class="row"><a href="{esc(it["url"])}" target="_blank">{esc(it["title"])}</a></div>'
                     f'<div>{meta}</div>{sumtxt}'
                     f'<div>{tags}</div></li>')
    if not ai_items:
        ai_items = '<li class="muted">今日数据获取失败，请稍后重试或检查网络。</li>'

    # ---- 基金 ----
    fund_date = fund.get("date", "")
    fund_rows = ""
    for i, f in enumerate(fund.get("rows", []), 1):
        g = f["gain"]
        try:
            cls = "up" if float(g) >= 0 else "down"
        except Exception:
            cls = ""
        m = f.get("month", "")
        try:
            mcls = "up" if float(m) >= 0 else "down"
        except Exception:
            mcls = ""
        fund_rows += (f'<tr><td>{i}</td><td><a href="https://fundf10.eastmoney.com/jjjz_{esc(f["code"])}.html" '
                      f'target="_blank">{esc(f["name"])}</a></td><td class="muted">{esc(f["code"])}</td>'
                      f'<td class="gain {cls}">{esc(g)}%</td>'
                      f'<td class="gain {mcls}">{esc(m)}%</td></tr>')
    if not fund_rows:
        fund_rows = '<tr><td colspan="5" class="muted">暂无排行数据</td></tr>'
    news_items = ""
    for n in fundnews:
        news_items += f'<li><a href="{esc(n["url"])}" target="_blank">{esc(n["title"])}</a></li>'
    if not news_items:
        news_items = '<li class="muted">资讯源暂不可用</li>'
    fund_note = f'数据日期：{esc(fund_date)}（非交易日显示最近交易日）' if fund_date else "近8日无交易日数据"

    # ---- 财报 & 招股书 ----
    pros = financial.get("prospectus")
    rep = financial.get("report")
    fin_html = ""
    if pros:
        fin_html += (f'<div class="pick"><div class="muted">📘 今日招股书 · {esc(pros.get("date",""))}</div>'
                     f'<div class="t"><a href="{esc(pros["url"])}" target="_blank">{esc(pros["title"])}</a></div>'
                     f'<div class="muted">{esc(pros["company"])} ({esc(pros["code"])})</div></div>')
    else:
        fin_html += '<div class="pick"><div class="muted">📘 今日招股书</div><div class="muted">近30日无新招股书</div></div>'
    if rep:
        fin_html += (f'<div class="pick"><div class="muted">📊 今日财报 · {esc(rep.get("date",""))}</div>'
                     f'<div class="t"><a href="{esc(rep["url"])}" target="_blank">{esc(rep["title"])}</a></div>'
                     f'<div class="muted">{esc(rep["company"])} ({esc(rep["code"])})</div></div>')
    else:
        fin_html += '<div class="pick"><div class="muted">📊 今日财报</div><div class="muted">近30日无匹配报告</div></div>'

    # ---- AIPM (完整镜像 GitHub 学习路径网页) ----
    aipm_html = ""
    if aipm.get("blocks"):
        repo = aipm.get("repo_url", AIPM_GITHUB_PAGE)
        n_tasks = aipm.get("total_tasks", 0)
        n_iv = len(aipm.get("interview", []))
        # 阶段概览 rail
        rail = ""
        for p in aipm.get("phases", []):
            rail += (f'<div class="aipm-chip"><div class="aipm-chip-num">{esc(p.get("num",""))}</div>'
                     f'<div class="aipm-chip-title">{esc(p.get("title",""))}</div>'
                     f'<div class="aipm-chip-meta">{esc(p.get("weeks",""))} 周 · {esc(p.get("badge",""))}</div></div>')
        # 阶段详情
        blocks_html = ""
        for b in aipm["blocks"]:
            tasks_html = ""
            for ti, t in enumerate(b["tasks"]):
                time_txt = f'约 {esc(t["time"])} 小时' if t.get("time") else ""
                lesson = AIPM_LESSONS.get(t["text"])
                note_html = ""
                if lesson:
                    pts = "".join(f"<li>{esc(p)}</li>" for p in lesson.get("points", []))
                    note_html = (f'<details class="aipm-note"><summary>📖 学习要点（{len(lesson.get("points", []))} 条）</summary>'
                                 f'<div class="aipm-note-sum">{esc(lesson.get("summary", ""))}</div>'
                                 f'<ul class="aipm-note-pts">{pts}</ul></details>')
                vid_url = "https://www.youtube.com/results?search_query=" + quote(t["text"])
                tasks_html += (f'<div class="aipm-task-wrap">'
                               f'<div class="aipm-task-row">'
                               f'<label class="aipm-task"><input type="checkbox" data-key="aipm-{b["idx"]}-{ti}">'
                               f'<span class="aipm-task-txt">{esc(t["text"])}</span>'
                               f'<span class="aipm-task-time">{time_txt}</span></label>'
                               f'<a class="aipm-video" href="{esc(vid_url)}" target="_blank" rel="noopener" title="查看相关视频教程">📺</a>'
                               f'</div>'
                               f'{note_html}</div>')
            res_html = ""
            for rsc in b["resources"]:
                url = esc(rsc.get("url", "")) or repo
                res_html += (f'<a class="aipm-res" href="{url}" target="_blank" rel="noopener">'
                             f'<span class="aipm-res-type">{esc(rsc.get("type",""))}</span>'
                             f'<span class="aipm-res-body"><span class="aipm-res-title">{esc(rsc.get("title",""))}</span>'
                             f'<span class="aipm-res-sub">{esc(rsc.get("sub",""))}</span></span>'
                             f'<span class="aipm-res-arrow">↗</span></a>')
            blocks_html += (
                f'<div class="aipm-block" id="aipm-phase{b["idx"]}">'
                f'<div class="aipm-block-head"><span class="aipm-block-idx">{esc(b["num"])}</span>'
                f'<div><div class="aipm-block-title">{esc(b["title"])} · {esc(b["weeks"])}周 · {esc(b["badge"])}</div>'
                f'<div class="muted">{esc(b["desc"])}</div></div></div>'
                f'<div class="aipm-tasklist">{tasks_html}</div>'
                + (f'<div class="aipm-res-label">推荐资源</div><div class="aipm-res-list">{res_html}</div>' if res_html else "")
                + f'</div>')
        # 面试题
        iv_html = ""
        for it in aipm.get("interview", []):
            iv_html += (f'<details class="aipm-iv"><summary><span class="aipm-iv-tag">{esc(it.get("tag",""))}</span>'
                        f'<span class="aipm-iv-q">{esc(it.get("q",""))}</span></summary>'
                        f'<div class="aipm-iv-body"><div class="aipm-iv-row"><b>思路</b> {esc(it.get("hint",""))}</div>'
                        f'<div class="aipm-iv-row"><b>参考</b> {esc(it.get("answer",""))}</div></div></details>')
        aipm_html = (
            f'<div class="aipm-hero"><div class="aipm-hero-title">🎓 AI 产品管理学习路径</div>'
            f'<div class="muted">完整镜像 github.com/xiaokaishuibuxing/aipm-learning-path · {len(aipm["blocks"])} 阶段 / {n_tasks} 任务 / {n_iv} 面试题'
            f' · <a href="{esc(repo)}" target="_blank" rel="noopener">在 GitHub 打开原网页 ↗</a></div></div>'
            f'<div class="aipm-rail">{rail}</div>'
            f'<div class="aipm-blocks">{blocks_html}</div>'
            + (f'<div class="aipm-block"><div class="aipm-block-head"><span class="aipm-block-idx">💬</span>'
               f'<div class="aipm-block-title">高频面试题（{n_iv}）</div></div>{iv_html}</div>' if iv_html else ""))
    else:
        aipm_html = '<div class="muted">AIPM 学习路径加载失败，请检查网络后点击 ↻ 刷新。</div>'

    # ---- GitHub ----
    gh_items = ""
    for g in github:
        ai_badge = '<span class="badge ok">AI</span>' if g["ai"] else '<span class="badge">trending</span>'
        star = f'<span class="score">★ {esc(g["total"])}</span>'
        today = f'<span class="muted">今日 +{esc(g["today"])}</span>' if g["today"] else ""
        lang = f'<span class="tag">{esc(g["lang"])}</span>' if g["lang"] else ""
        gh_items += (f'<li><div class="row"><a href="{esc(g["url"])}" target="_blank">{esc(g["repo"])}</a>'
                     f'<span>{ai_badge} {star}</span></div>'
                     f'<div class="muted">{esc(g["desc"])}</div>'
                     f'<div>{lang} {today}</div></li>')
    if not gh_items:
        gh_items = '<li class="muted">GitHub 热点获取失败</li>'

    # ---- 行测 ----
    xc = xingce or {}
    if xc.get("title"):
        op = (f'<div class="muted" style="margin-top:8px">{esc(xc["opening"])}…</div>'
              if xc.get("opening") else "")
        xc_html = (f'<div class="pick"><div class="muted">📝 行测每日练 · 进度 {xc["index"]}/{xc["total"]}</div>'
                   f'<div class="t"><a href="{esc(xc["url"])}" target="_blank">{esc(xc["title"])}</a></div>{op}'
                   f'<div class="muted" style="margin-top:6px">点开即读粉笔「行测小讲堂」精讲。</div></div>')
    else:
        xc_html = '<div class="muted">行测资料加载失败</div>'

    # ---- 申论 ----
    sl = shenlun or {}
    if sl.get("title"):
        op = (f'<div class="muted" style="margin-top:8px">{esc(sl["opening"])}…</div>'
              if sl.get("opening") else "")
        sl_html = (f'<div class="pick"><div class="muted">📖 申论每日读 · 进度 {sl["index"]}/{sl["total"]}</div>'
                   f'<div class="t"><a href="{esc(sl["url"])}" target="_blank">{esc(sl["title"])}</a></div>{op}'
                   f'<div class="muted" style="margin-top:6px">点开即读粉笔「申论小讲堂」范文/技巧。</div></div>')
    else:
        sl_html = '<div class="muted">申论资料加载失败</div>'

    # ---- 雅思单词 ----
    iwords = ielts.get("words", []) if isinstance(ielts, dict) else []
    if iwords:
        cards = ""
        for w in iwords:
            cards += (f'<div class="ielts-card" data-word="{esc(w["word"])}">'
                      f'<div class="ielts-front" onclick="flipIelts(this)">'
                      f'<div class="ielts-wordrow"><span class="ielts-word">{esc(w["word"])}</span>'
                      f'<button class="ielts-spk" type="button" onclick="speakIelts(event,\'{esc(w["word"])}\')" title="朗读发音">🔊</button></div>'
                      f'<div class="ielts-phon">{esc(w["phon"])}</div>'
                      f'<div class="ielts-hint">点击看释义 ▾</div></div>'
                      f'<div class="ielts-back" style="display:none">'
                      f'<div class="ielts-pos">{esc(w["pos"])} {esc(w["mean"])}</div>'
                      f'<div class="ielts-ex">{esc(w["ex"])}</div>'
                      f'<div class="ielts-exzh">{esc(w["ex_zh"])}</div>'
                      f'<button class="ielts-master" type="button" onclick="masterIelts(this,\'{esc(w["word"])}\')">标记为已掌握</button>'
                      f'</div></div>')
        ielts_html = (f'<div class="ielts-bar"><span class="muted">🇬🇧 雅思核心词 · 第 {ielts["idx"]}/{ielts["total_groups"]} 组 · 共 {len(iwords)} 词</span>'
                      f'<span class="ielts-progress">累计掌握 <b id="ielts-count">0</b> 词</span></div>'
                      f'<div class="ielts-grid">{cards}</div>')
    else:
        ielts_html = '<div class="muted">雅思词库加载失败</div>'

    # ---- 模块状态文案（用于每日计划与侧边栏） ----
    def status_msg(key):
        ok, msg = STATUS.get(key, (False, ""))
        return f"{'✅' if ok else '⚠️'} {msg}" if msg else ("✅ 已加载" if ok else "⚠️ 未加载")


    # ---- 侧边栏导航 HTML ----
    nav_html = ""
    for icon, title, sub, key in modules:
        active = " active" if key == "dailyplan" else ""
        nav_html += (f'<div class="nav-item{active}" data-target="{key}" onclick="switchTab(this, \'{key}\')">'
                     f'<span class="nav-icon">{icon}</span>'
                     f'<span class="nav-text"><span class="nav-title">{esc(title)}</span>'
                     f'<span class="nav-sub" id="nav-sub-{key}">{esc(status_msg(key) if key != "dailyplan" else "总览")}</span></span>'
                     f'</div>')

    # ---- 每日计划页面：可勾选列表 ----
    plan_items = ""
    plan_modules = modules[1:]  # 跳过 dailyplan 自身
    for icon, title, sub, key in plan_modules:
        desc = status_msg(key)
        plan_items += (f'<div class="plan-item" onclick="jumpTo(\'{key}\')">'
                       f'<span class="plan-icon">{icon}</span>'
                       f'<div class="plan-info"><div class="plan-title">{esc(title)}</div>'
                       f'<div class="plan-desc">{esc(desc)}</div></div>'
                       f'<span class="plan-status" id="plan-status-{key}">待完成</span>'
                       f'<div class="plan-check" id="check-{key}" data-key="{key}" onclick="event.stopPropagation();toggleCheck(\'{key}\')"></div>'
                       f'</div>')

    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    weekday = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")
    weekdays = {"Monday":"星期一","Tuesday":"星期二","Wednesday":"星期三","Thursday":"星期四",
                "Friday":"星期五","Saturday":"星期六","Sunday":"星期日"}
    weekday_cn = weekdays.get(weekday, weekday)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日工作台 · {esc(date_str)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="brand">
      <div class="avatar">🧑‍💻</div>
      <div class="brand-text">
        <span class="brand-name">每日工作台</span>
        <span class="brand-sub">个人学习 & 资讯仪表盘</span>
      </div>
    </div>
    <nav class="nav-list">{nav_html}</nav>
    <div class="sidebar-footer">
      数据每日 08:00 自动生成<br>生成于 {esc(gen_time)}
    </div>
  </aside>
  <div class="overlay" id="overlay" onclick="toggleMenu()"></div>
  <main class="main">
    <div class="topbar">
      <div class="topbar-left">
        <button class="menu-toggle" onclick="toggleMenu()">☰</button>
        <div>
          <div class="page-date">{esc(date_str)} · {esc(weekday_cn)}</div>
        </div>
      </div>
      <div class="topbar-right">
        <button class="btn" onclick="showSync()">🔄 同步到手机</button>
        <button class="btn" onclick="document.documentElement.setAttribute('data-theme', document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark')">🌓 主题</button>
        <button class="btn" onclick="doRefresh()">↻ 刷新</button>
      </div>
    </div>
    <div class="content">
      <!-- 每日计划 -->
      <section class="section active" id="section-dailyplan">
        <div class="section-title">🗓️ 每日计划</div>
        <div class="section-sub">完成一项打勾，进度一目了然</div>
        <div class="card">
          <h2>今日进度 <span class="badge" id="progress-badge">0/8</span></h2>
          <div class="progress-bar"><div class="progress-fill" id="progress-fill" style="width:0%"></div></div>
          <div class="progress-text" id="progress-text">完成 0 项，继续加油 👇</div>
          <div class="plan-list" style="margin-top:18px">{plan_items}</div>
        </div>
        <div class="card todo-wrap">
          <h2>✏️ 我的任务 <span class="badge">可编辑</span></h2>
          <div class="todo-add">
            <input class="todo-input" id="todo-input" placeholder="添加今日任务，回车确认…" onkeydown="if(event.key==='Enter')addTodo()">
            <button class="btn btn-primary" onclick="addTodo()">＋ 添加</button>
          </div>
          <ul class="todo-list" id="todo-list"></ul>
        </div>
        <div class="card memo-wrap">
          <h2>📝 个人备忘</h2>
          <textarea class="memo" id="memo-input" placeholder="随手记点什么，自动保存…" oninput="saveMemo()"></textarea>
        </div>
      </section>

      <!-- AI 日报 -->
      <section class="section" id="section-aihot">
        <div class="section-title">🤖 AI 日报</div>
        <div class="section-sub">aihot.virxact.com 今日精选</div>
        <div class="card"><ul class="scroll">{ai_items}</ul></div>
      </section>

      <!-- 基金涨幅 -->
      <section class="section" id="section-fund">
        <div class="section-title">📈 基金涨幅榜 Top20</div>
        <div class="section-sub">天天基金公开排行 · {esc(fund_note)}</div>
        <div class="card">
          <table><thead><tr><th>#</th><th>基金</th><th>代码</th><th>日涨幅</th><th>近30天(近1月)</th></tr></thead>
          <tbody>{fund_rows}</tbody></table>
        </div>
      </section>

      <!-- 基金资讯 -->
      <section class="section" id="section-fundnews">
        <div class="section-title">📰 基金资讯</div>
        <div class="section-sub">每日基金要闻</div>
        <div class="card"><ul class="scroll">{news_items}</ul></div>
      </section>

      <!-- 财报招股书 -->
      <section class="section" id="section-financial">
        <div class="section-title">📄 每日财报 & 招股书</div>
        <div class="section-sub">东方财富公告</div>
        <div class="card">{fin_html}</div>
      </section>

      <!-- AIPM -->
      <section class="section" id="section-aipm">
        <div class="section-title">🎓 AIPM 学习</div>
        <div class="section-sub">完整镜像 GitHub 学习路径网页 · 四阶段任务 + 推荐资源 + 高频面试题</div>
        <div class="card">{aipm_html}</div>
      </section>

      <!-- GitHub -->
      <section class="section" id="section-github">
        <div class="section-title">🐙 GitHub AI 热点</div>
        <div class="section-sub">trending 过滤 AI 相关仓库</div>
        <div class="card"><ul class="scroll">{gh_items}</ul></div>
      </section>

      <!-- 行测 -->
      <section class="section" id="section-xingce">
        <div class="section-title">📝 行测每日练</div>
        <div class="section-sub">粉笔「行测小讲堂」按日轮换</div>
        <div class="card">{xc_html}</div>
      </section>

      <!-- 申论 -->
      <section class="section" id="section-shenlun">
        <div class="section-title">📖 申论每日读</div>
        <div class="section-sub">粉笔「申论小讲堂」按日轮换</div>
        <div class="card">{sl_html}</div>
      </section>

      <!-- 雅思单词 -->
      <section class="section" id="section-ielts">
        <div class="section-title">🇬🇧 雅思单词</div>
        <div class="section-sub">每日 15 个核心词 · 点击卡片看释义 · 🔊 朗读发音</div>
        <div class="card">{ielts_html}</div>
      </section>

      <footer>数据来源：aihot.virxact.com · 天天基金(东方财富) · 东方财富公告 · GitHub Trending ·
AIPM 学习路径(xiaokaishuibuxing/aipm-learning-path) · 粉笔网(行测/申论小讲堂) ｜ 本页由本地脚本每日生成，仅供学习参考，不构成投资建议。</footer>
    </div>
  </main>
</div>
<script>
const dateKey = "wb_done_{esc(date_str)}_";
const modules = {{
  aihot: "AI 日报",
  fund: "基金涨幅榜",
  fundnews: "基金资讯",
  financial: "财报 & 招股书",
  aipm: "AIPM 学习",
  github: "GitHub AI 热点",
  xingce: "行测每日练",
  shenlun: "申论每日读",
  ielts: "雅思单词"
}};
function switchTab(el, key){{
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('section-'+key).classList.add('active');
  if(window.innerWidth <= 860) toggleMenu(false);
}}
function jumpTo(key){{
  const nav = document.querySelector('.nav-item[data-target="'+key+'"]');
  if(nav) switchTab(nav, key);
}}
function toggleCheck(key){{
  const done = localStorage.getItem(dateKey+key) === '1';
  localStorage.setItem(dateKey+key, done ? '' : '1');
  renderChecks();
}}
function initAipmChecks(){{
  const dk = "wb_aipm_{esc(date_str)}";
  document.querySelectorAll('.aipm-task input[type=checkbox]').forEach(function(cb){{
    const k = cb.getAttribute('data-key');
    const store = dk + '_' + k;
    cb.checked = localStorage.getItem(store) === '1';
    cb.addEventListener('change', function(){{
      localStorage.setItem(store, cb.checked ? '1' : '');
    }});
  }});
}}
function flipIelts(front){{
  const card = front.closest('.ielts-card');
  const back = card.querySelector('.ielts-back');
  const hint = front.querySelector('.ielts-hint');
  const open = back.style.display === 'none';
  back.style.display = open ? 'block' : 'none';
  if(hint) hint.textContent = open ? '点击收起 ▴' : '点击看释义 ▾';
}}
function speakIelts(ev, word){{
  ev.stopPropagation();
  try{{
    const u = new SpeechSynthesisUtterance(word);
    u.lang = 'en-GB'; u.rate = 0.9;
    speechSynthesis.cancel(); speechSynthesis.speak(u);
  }}catch(e){{}}
}}
function masterIelts(btn, word){{
  let set = {{}};
  try{{ set = JSON.parse(localStorage.getItem('wb_ielts_mastered') || '{{}}'); }}catch(e){{}}
  if(set[word]){{ delete set[word]; btn.classList.remove('done'); btn.textContent = '标记为已掌握'; }}
  else{{ set[word] = 1; btn.classList.add('done'); btn.textContent = '已掌握 ✓'; }}
  try{{ localStorage.setItem('wb_ielts_mastered', JSON.stringify(set)); }}catch(e){{}}
  updateIeltsCount();
}}
function updateIeltsCount(){{
  let set = {{}};
  try{{ set = JSON.parse(localStorage.getItem('wb_ielts_mastered') || '{{}}'); }}catch(e){{}}
  const c = document.getElementById('ielts-count');
  if(c) c.textContent = Object.keys(set).length;
  document.querySelectorAll('.ielts-card').forEach(function(card){{
    const w = card.getAttribute('data-word');
    const b = card.querySelector('.ielts-master');
    if(set[w]){{ b.classList.add('done'); b.textContent = '已掌握 ✓'; }}
  }});
}}
function initIelts(){{ updateIeltsCount(); }}
function renderChecks(){{
  let doneCount = 0;
  Object.keys(modules).forEach(k=>{{
    const el = document.getElementById('check-'+k);
    const st = document.getElementById('plan-status-'+k);
    const isDone = localStorage.getItem(dateKey+k) === '1';
    if(isDone){{ el.classList.add('done'); el.innerHTML='✓'; st.textContent='已完成'; doneCount++; }}
    else{{ el.classList.remove('done'); el.innerHTML=''; st.textContent='待完成'; }}
  }});
  const total = Object.keys(modules).length;
  document.getElementById('progress-badge').textContent = doneCount+'/'+total;
  document.getElementById('progress-fill').style.width = (doneCount/total*100)+'%';
  const texts = ['完成 0 项，开始今日计划吧 💪','完成 1 项， momentum 有了 ⚡','完成 '+doneCount+' 项，继续加油 👇','完成 '+doneCount+' 项，过半啦 🚀','完成 '+doneCount+' 项，冲刺最后几项 🏁','全部完成！今日计划清空 ✨'];
  let ti = doneCount === 0 ? 0 : doneCount === total ? 5 : doneCount >= total*0.75 ? 4 : doneCount >= total*0.5 ? 3 : doneCount >= 2 ? 2 : 1;
  document.getElementById('progress-text').textContent = texts[ti];
}}
function toggleMenu(force){{
  const sb = document.getElementById('sidebar');
  const ov = document.getElementById('overlay');
  const open = force===undefined ? !sb.classList.contains('open') : force;
  sb.classList.toggle('open', open);
  ov.classList.toggle('open', open);
}}
function showSync(){{
  alert('iCloud 同步路径：~/Library/Mobile Documents/com~apple~CloudDocs/Workbench/dashboard.html  （iPhone 文件App → iCloud Drive → Workbench 用 Safari 打开）');
}}
function doRefresh(){{
  if(location.protocol === 'http:' || location.protocol === 'https:'){{
    const btn = event && event.target;
    if(btn){{ btn.textContent='⏳ 抓取中…'; btn.disabled=true; }}
    fetch('/refresh').then(function(r){{ return r.text(); }}).then(function(){{
      location.href = '/?t=' + Date.now();
    }}).catch(function(){{
      alert('实时刷新服务未启动。请先运行 server.py，或此份为 iCloud 静态副本（直接双击本地 dashboard.html 也可）。');
      if(btn){{ btn.textContent='↻ 刷新'; btn.disabled=false; }}
    }});
  }} else {{
    location.reload();
  }}
}}
/* 我的任务 CRUD (localStorage 按日持久化) */
const todoKey = "wb_todo_{esc(date_str)}";
const memoKey = "wb_memo_{esc(date_str)}";
function loadTodos(){{
  try {{ return JSON.parse(localStorage.getItem(todoKey)) || []; }} catch(e) {{ return []; }}
}}
function saveTodos(list){{
  localStorage.setItem(todoKey, JSON.stringify(list));
  renderTodos();
}}
function addTodo(){{
  const inp = document.getElementById('todo-input');
  const text = inp.value.trim();
  if(!text) return;
  const list = loadTodos();
  list.push({{id: Date.now(), text: text, done: false}});
  inp.value = '';
  saveTodos(list);
}}
function toggleTodo(id){{
  const list = loadTodos().map(function(t){{ if(t.id===id) t.done=!t.done; return t; }});
  saveTodos(list);
}}
function delTodo(id){{
  saveTodos(loadTodos().filter(function(t){{ return t.id!==id; }}));
}}
function renderTodos(){{
  const list = loadTodos();
  const ul = document.getElementById('todo-list');
  if(!ul) return;
  ul.innerHTML = '';
  list.forEach(function(t){{
    const li = document.createElement('li');
    li.className = 'todo-item';
    const box = document.createElement('div');
    box.className = 'todo-box' + (t.done ? ' done' : '');
    box.textContent = t.done ? '✓' : '';
    box.onclick = function(){{ toggleTodo(t.id); }};
    const span = document.createElement('span');
    span.className = 'todo-text' + (t.done ? ' done' : '');
    span.textContent = t.text;
    const del = document.createElement('span');
    del.className = 'todo-del';
    del.textContent = '✕';
    del.title = '删除';
    del.onclick = function(){{ delTodo(t.id); }};
    li.appendChild(box); li.appendChild(span); li.appendChild(del);
    ul.appendChild(li);
  }});
  if(list.length === 0){{
    ul.innerHTML = '<li class="muted" style="border:none;padding:6px 0">还没有任务，上面加一条吧。</li>';
  }}
}}
function loadMemo(){{
  const ta = document.getElementById('memo-input');
  if(ta) ta.value = localStorage.getItem(memoKey) || '';
}}
function saveMemo(){{
  const ta = document.getElementById('memo-input');
  if(ta) localStorage.setItem(memoKey, ta.value);
}}
renderChecks();
initAipmChecks();
initIelts();
renderTodos();
loadMemo();
</script>
</body>
</html>"""
    return html


# ---------------- 主流程 ----------------
def main():
    global DEBUG
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--date", default=None, help="基准日 YYYY-MM-DD")
    ap.add_argument("--no-icloud", action="store_true", help="跳过 iCloud 同步（CI / 非 Mac 环境）")
    args = ap.parse_args()
    DEBUG = args.debug

    if args.date:
        base_date = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        base_date = datetime.now()
    date_str = base_date.strftime("%Y-%m-%d")

    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    print(f"▶ 生成 {date_str} 每日工作台 ...") if not DEBUG else None
    aihot = fetch_aihot()
    fund = fetch_fund_ranking(base_date)
    fundnews = fetch_fund_news()
    financial = fetch_financial(base_date)
    aipm = fetch_aipm(base_date)
    github = fetch_github()
    xingce = fetch_xingce(base_date)
    shenlun = fetch_shenlun(base_date)
    ielts = fetch_ielts(base_date)

    html = build_html(date_str, aihot, fund, fundnews, financial, aipm, github, xingce, shenlun, ielts)

    out_path = os.path.join(OUT_DIR, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    arc_path = os.path.join(ARCHIVE_DIR, f"{date_str}.html")
    with open(arc_path, "w", encoding="utf-8") as f:
        f.write(html)

    # iOS 同步: 复制到 iCloud Drive -> iPhone 文件 App 可看
    if args.no_icloud or os.environ.get("DISABLE_ICLOUD"):
        ic_ok, ic_msg = False, "CI/--no-icloud 跳过 iCloud 同步"
    else:
        ic_ok, ic_msg = sync_icloud(out_path)

    ok = sum(1 for v in STATUS.values() if v[0])
    print(f"✅ 已生成: {out_path}")
    print(f"   归档: {arc_path}")
    if ic_ok:
        print(f"   📱 iCloud 同步: {ic_msg}/dashboard.html (iPhone 文件App→iCloud Drive→Workbench)")
    else:
        print(f"   📱 iCloud 同步跳过: {ic_msg}")
    print(f"   模块状态: {ok}/{len(STATUS)} 成功")
    for n, (s, m) in STATUS.items():
        print(f"   [{'OK' if s else 'XX'}] {n}: {m}")


if __name__ == "__main__":
    main()
