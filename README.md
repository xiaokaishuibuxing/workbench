# 每日工作台 (Daily Workbench)

一个 0 依赖的单文件每日仪表盘：每日 AI 发布、基金涨幅/资讯、财报与招股书、AIPM 学习路径（含视频入口）、GitHub AI 热点、行测/申论、雅思单词。所有交互（导航、打卡、任务、备忘、雅思朗读）均在浏览器内完成，数据存在 localStorage。

## 模块
- 🤖 每日 AI 发布（aihot.virxact.com）
- 📈 基金涨幅榜 Top20 + 近30天涨幅（天天基金/东方财富）
- 📰 基金资讯（新浪基金）
- 📑 每日财报与招股书（东方财富公告）
- 🎓 AIPM 学习路径（github.com/xiaokaishuibuxing/aipm-learning-path，含任务讲解 + YouTube 视频入口）
- 🌟 GitHub AI 热点（GitHub Trending）
- 📝 行测 / 📖 申论（粉笔网小讲堂，按日轮换）
- 🇬🇧 雅思单词（本地词库 141 词，每日 15 词，可翻转/朗读/标记掌握）

## 本地运行
```bash
pip install -r requirements.txt
python workbench.py          # 生成 dashboard.html（并同步到 iCloud）
python server.py            # 可选：起本地服务，页面内 ↻ 实时刷新
```

## 部署到 GitHub Pages（全自动）
1. 在 GitHub 新建一个空仓库（如 `workbench`）。
2. 将本仓库 push 上去：
   ```bash
   git remote add origin https://github.com/<你的用户名>/workbench.git
   git branch -M main
   git push -u origin main
   ```
3. 仓库 → Settings → Pages → Source 选择 **gh-pages** 分支 / **root**。
4. 完成。GitHub Actions 会每天 08:00（北京）自动重抓数据并发布；也可在 Actions 页手动触发。

> 免费 GitHub 无常驻服务器，因此为**每日刷新一次**（非实时）。如需实时刷新需付费主机。
