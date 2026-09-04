# Z.AI 每日文献分类流程

## 运行方式

新 workflow `.github/workflows/daily_classification_zai.yaml` 会在现有日报抓取 workflow 成功结束后启动，不依赖固定延时。

1. 读取最新的 `output/news_with_abstract_YYYY-MM-DD.csv`。
2. 沿用 `classification.txt`、关键词排除/包含规则和 sentence-transformers 语义候选。
3. 标题、摘要仍由 Google Translate 翻译。
4. 最终分类由 `glm-5.2` 完成，输出 `output/daily_classified/news_with_abstract_YYYY-MM-DD_zai_classified.xlsx`。
5. 每周五只读取最近 7 天已经分类好的每日 XLSX，去重后汇总到 `output/weekly_classified/weekly_daily_classified_YYYY-MM-DD.xlsx`，不会再次调用翻译或大模型。

原 `.github/workflows/csv_to_xlsx.yaml` 已移除定时触发，但保留 `workflow_dispatch`，可在 GitHub Actions 页面手动运行 Gemini 备份流程。

## GitHub Secrets

必须配置一个 Secret：

- `ZAI_API_KEY`：三个接口共用的 API Key。主线路失败后先使用 `https://open.bigmodel.cn/api/paas/v4`，仍失败才使用 `https://open.bigmodel.cn/api/anthropic`。

接口自动回退顺序固定为：

1. `https://api.z.ai/api/paas/v4/chat/completions`
2. `https://open.bigmodel.cn/api/paas/v4/chat/completions`
3. `https://open.bigmodel.cn/api/anthropic/v1/messages`

密钥只从环境变量读取，不写入代码、日志或产物。

## 手动命令

```bash
python classify_daily_zai.py -i output/news_with_abstract_2026-09-02.csv -c classification.txt
python aggregate_daily_classified.py -c classification.txt --days 7
```

GitHub Actions 的手动参数 `api-test` 会使用 `ZAI_API_KEY` 分别向三个接口发送一次最小 GLM-5.2 请求，只验证鉴权和模型调用，不生成日报文件。

分类任务具有按输入日期命名的检查点。已有每日 XLSX 时，workflow 会跳过，避免同一天重复消耗额度。周汇总文件已存在时也会跳过；只有显式传入 `--force` 才会覆盖。
