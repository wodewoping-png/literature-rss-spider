# -*- coding: utf-8 -*-
"""Run the established weekly XLSX/DOCX pipeline with Z.AI GLM-5.2."""

import classify_weekly_onefile as pipeline
from classify_daily_zai import install_zai_backend


if __name__ == "__main__":
    install_zai_backend()
    pipeline.main()
