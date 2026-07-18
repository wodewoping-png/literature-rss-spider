import importlib.util
import sys
import types
import unittest
from pathlib import Path


def load_spider_module():
    sys.modules.setdefault("feedparser", types.ModuleType("feedparser"))
    sys.modules.setdefault("requests", types.ModuleType("requests"))
    playwright = sys.modules.setdefault("playwright", types.ModuleType("playwright"))
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: None
    sys.modules.setdefault("playwright.sync_api", sync_api)
    playwright.sync_api = sync_api

    path = Path(__file__).with_name("spider0301.py")
    spec = importlib.util.spec_from_file_location("spider0301_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


spider = load_spider_module()


class AbstractSourceTests(unittest.TestCase):
    def test_content_encoded_is_used_when_summary_is_absent(self):
        entry = {"content": [{"value": "<p>publisher header</p>Useful abstract body"}]}
        self.assertIn("Useful abstract", spider.get_entry_description_html(entry))

    def test_nature_rss_citation_prefix_is_removed(self):
        raw = (
            "<p>Nature Energy, Published online: 17 July 2026; "
            "<a href='x'>doi:10.1038/example</a></p>"
            + "This publisher-provided abstract explains the research findings in enough "
            + "detail to pass the minimum length validation and be useful downstream."
        )
        abstract = spider.extract_nature_abstract_from_rss(raw, "Different title")
        self.assertTrue(abstract.startswith("This publisher-provided abstract"))
        self.assertNotIn("Published online", abstract)

    def test_pnas_volume_prefix_is_removed(self):
        raw = (
            "Proceedings of the National Academy of Sciences, Volume 123. <br/>"
            "Significance This official summary contains enough detail to be treated as a "
            "useful fallback when public metadata APIs do not return a full abstract."
        )
        abstract = spider.extract_pnas_abstract_from_rss(raw, "Different title")
        self.assertTrue(abstract.startswith("Significance"))
        self.assertNotIn("Volume 123", abstract)

    def test_sciencedirect_pii_is_extracted(self):
        link = "https://www.sciencedirect.com/science/article/pii/S0306261926008019?dgcid=rss"
        self.assertEqual("S0306261926008019", spider.extract_sciencedirect_pii(link))

    def test_elsevier_xml_extracts_doi_and_description(self):
        xml = """<response xmlns:dc='http://purl.org/dc/elements/1.1/'
                    xmlns:prism='http://prismstandard.org/namespaces/basic/2.0/'>
          <coredata>
            <prism:doi>10.1016/j.apenergy.2026.128149</prism:doi>
            <dc:description>This is a sufficiently long Elsevier abstract returned by the API,
            containing more than eighty characters so that it is accepted by the parser.</dc:description>
          </coredata>
        </response>"""
        info = spider.parse_elsevier_article_xml(xml)
        self.assertEqual("10.1016/j.apenergy.2026.128149", info["doi"])
        self.assertTrue(info["abstract"].startswith("This is a sufficiently long"))

    def test_reader_extracts_markdown_abstract_section(self):
        markdown = """# Article title

## Abstract

This third-party reader result contains a complete abstract with enough detail
to pass validation and remain useful for downstream literature classification.

## Keywords

energy storage
"""
        abstract, blocked = spider.extract_reader_markdown_abstract(markdown, "Article title")
        self.assertFalse(blocked)
        self.assertTrue(abstract.startswith("This third-party reader result"))
        self.assertNotIn("Keywords", abstract)

    def test_reader_rejects_captcha_page(self):
        markdown = "# Are you a robot?\nPlease complete the CAPTCHA challenge."
        abstract, blocked = spider.extract_reader_markdown_abstract(markdown)
        self.assertTrue(blocked)
        self.assertEqual("", abstract)


if __name__ == "__main__":
    unittest.main()
