import unittest
from test_spider_abstract_sources import spider

class IEEEDiscoveryTests(unittest.TestCase):
    def test_year_only_publication_is_not_january_first(self):
        day = max(spider.TARGET_DATES)
        meta = spider.CROSSREF_FALLBACK_FEEDS['https://ieeexplore.ieee.org/rss/TOC9424.XML']
        record = spider._crossref_work_to_record({
            'DOI': '10.1109/tii.2026.example', 'title': ['A novel industrial control method'],
            'published-print': {'date-parts': [[2026]]},
            'created': {'date-parts': [[day.year, day.month, day.day]]},
        }, meta)
        self.assertIsNotNone(record)
        self.assertIsNone(record['pub_date'])
        self.assertEqual(record['published_str'], '')
        self.assertTrue(record['discovery_date'].startswith(day.isoformat()))

    def test_all_six_ieee_sources_use_registration_discovery(self):
        sources = [m for m in spider.CROSSREF_FALLBACK_FEEDS.values() if m['doi_prefix'] == '10.1109/']
        self.assertEqual(len(sources), 6)
        self.assertTrue(all(m['date_source'] == 'created' for m in sources))
