
### 每日行业图景分类（2026-10-17 起）

北京时间 2026-10-17 起，现有每日分类工作流改用 `classify_daily_industry.py`。
GLM-5.3-Flash 根据原始标题与完整英文摘要，从
`config/monthly/industry_taxonomy.json` 中选择最贴切的一条主路径。
输出包含“分类概览、零碳产业、AI与智能科技、通用技术、未纳入分类、ALL”六个工作表，
并保留一至五级分类、分类说明、状态及全部原始字段；“未纳入分类”保留无适用路径或信息不足等记录。
电池正极、负极、电解质、非活性材料/检测技术均在第五级体现，不增加第六级。
缺少摘要时只按明确标题判定；宏观气候政策不归入资源加工，图景无专类时暂挂其他环境治理并提示复核。

每日文件仍保存为 `output/daily_classified/news_with_abstract_YYYY-MM-DD_zai_classified.xlsx`。
翻译继续使用原有免费翻译路线及 Z.AI 备用路线。新分类缓存为
`output/checkpoints/industry_classification.json`，按模型、提示词、图景版本及原文内容失效；
接口失败、漏项或非法路径只保存进度，不生成一个看似完成的工作簿。
现有采集后触发和每小时 17/47 分的额度重试机制继续使用，两个入口均从切换日期开始选取待处理 CSV。
`force_reclassify` 可重新生成切换日期后的最新表格，但仍复用有效语义缓存。
显式命令行输入不受自动切换日期限制，可单独测试历史 CSV：

```bash
python classify_daily_industry.py -i output/news_with_abstract_2026-10-17.csv --translation-provider google
python -m unittest discover -s tests -v
```

旧 `classify_daily_zai.py`、`classify_weekly_onefile.py`、`classify_weekly_zai.py` 和
`classification.txt` 保留；自动每日入口不再调用旧专题分类逻辑。
周报直接合并每日行业判定，不再调用模型；切换后必须等该周七份日表均为最新后才汇总。
手动混合新旧日表时，尚无行业判定的旧记录保留在“未纳入分类”中，不将旧标签冒充新路径。
月报沿用出版社配色、出版社/期刊/数量合并及明细折叠版式，三个行业 sheet 直接沿用新日表路径；
切换前的历史记录继续用保留的月度兼容映射。每日未纳入的文献仍在日表和周报的 ALL 中，
月报日志单独报告其数量，不强行塞进三个行业分表。
