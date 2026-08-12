# 项目架构

## 当前生产链路

```text
feeds1211.txt
  -> spider0301.py
  -> output/news_with_abstract_YYYY-MM-DD.csv
  -> weekly_aggrerate_with_abs.py
  -> output/weekly/weekly_news_with_abstract_YYYY-MM-DD.csv
  -> classify_weekly_onefile.py
       规则排除/强匹配 -> sentence-transformers 候选召回 -> Gemini 最终分类
       Google Translate（可选）
  -> translated CSV / XLSX / DOCX
  -> monthly_literature_stats.py
  -> output/monthly/YYYY-MM 文献统计表.xlsx
```

正式周报分类继续使用 Gemini。`classification.txt` 是类别定义的唯一维护入口，
`classify_weekly_onefile.py` 负责稳定 ID、断点续跑、规则/向量路由、Gemini 批量确认和报表导出。

## GitHub Actions 职责

- `rss_abs.yaml`：每日抓取、每周聚合，只安装 `requirements-spider.txt`。
- `csv_to_xlsx.yaml`：每周运行 Gemini 分类和周报导出，只安装
  `requirements-classifier.txt`。
- `monthly_literature_stats.yaml`：周报成功后按月生成统计表，只安装
  `requirements-report.txt`。
- `tests.yaml`：在 PR 和 `main` push 上运行编译检查与离线单元测试。

旧版并行 RSS workflow 已删除，避免同一天重复抓取、重复提交和 main 分支 push 竞争。
旧版 `new_tran.py` 与名为测试、实际会联网分类的 `test_classify_only.py` 也已删除；生产能力
由主分类脚本保留。

## 测试边界

本地和 CI 测试不调用 Gemini API，也不需要模型密钥：

```bash
GEMINI_NETWORK_DISABLED=1 python -m unittest discover -v
python -m compileall -q -x '(output|filtered_news|csv|.git)' .
```

测试通过 Mock 注入固定 Gemini JSON，验证请求/响应解析、标签白名单、混合分类、断点数据和
XLSX/DOCX 导出。`gemini_client.py` 在 `GEMINI_NETWORK_DISABLED=1` 时会在创建网络请求前
直接失败，防止本地或 CI 测试误用真实 API；该开关不应设置在生产分类 workflow 中。

## 依赖分层

- `requirements-spider.txt`：RSS、网页抓取和 Playwright。
- `requirements-report.txt`：Pandas、Excel、Word 和基础 HTTP。
- `requirements-classifier.txt`：报告依赖加 Torch、Transformers、句向量与 scikit-learn。
- `requirements-analytics.txt`：专项分析和绘图。
- `requirements.txt`：兼容全量安装的聚合入口。

## 保留的历史/专项代码

根目录中的旧爬虫与 `filtered_news/`、`csv/` 下的专项分析脚本仍保留，便于追溯历史数据，
但不属于默认生产 workflow。新增能力应优先进入上述主链路，避免继续复制完整脚本。
