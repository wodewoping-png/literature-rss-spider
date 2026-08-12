# 项目架构

## 当前生产链路

```text
feeds1211.txt
  -> spider0301.py
  -> output/news_with_abstract_YYYY-MM-DD.csv
  -> weekly_aggrerate_with_abs.py
  -> output/weekly/weekly_news_with_abstract_YYYY-MM-DD.csv
  -> classify_weekly_onefile.py prepare
  -> openai/codex-action（仅分类，结构化 JSON）
  -> classify_weekly_onefile.py export
  -> translated CSV / XLSX / DOCX
  -> monthly_literature_stats.py
  -> output/monthly/YYYY-MM 文献统计表.xlsx
```

分类只使用 Codex。仓库中不包含 Gemini 客户端、Gemini endpoint、Gemini 模型参数或
Gemini API key。翻译与分类相互独立：翻译可选择 Google Translate 或 `none`，不会使用
Gemini API。

## GitHub Actions 职责

- `rss_abs.yaml`：每日抓取、每周聚合，只安装 `requirements-spider.txt`。
- `csv_to_xlsx.yaml`：prepare / Codex classify / export 三个隔离阶段；分类输入按约 150 条
  分批，并最多并行 3 批。Codex job 只读；
  具有仓库写权限的 export job不能访问 OpenAI 密钥。
- `monthly_literature_stats.yaml`：周报成功后按月生成统计表，只安装
  `requirements-report.txt`。
- `tests.yaml`：在 PR 和 `main` push 上运行离线测试、编译检查和 Gemini API 禁用扫描。

旧版并行 RSS workflow 已删除，避免同一天重复抓取、重复提交和 main 分支 push 竞争。

## 本地验证

本地测试不需要模型密钥，也不发起分类网络请求：

```bash
python -m unittest discover -v
python -m compileall -q -x '(output|filtered_news|csv|.git)' .
```

分类端到端采用文件契约测试：生成 Codex input/schema，用固定 JSON 模拟 Codex 输出，
再验证严格校验、Excel 和 Word 导出。GitHub Actions 中才由 `openai/codex-action@v1`
替换该固定输出。

## 保留的历史/专项代码

根目录中的旧爬虫与 `filtered_news/`、`csv/` 下的专项分析脚本仍保留，便于追溯历史
数据。但它们不属于默认生产 workflow；新增功能应优先进入上述主链路，避免复制脚本。
