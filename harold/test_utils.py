import unittest
from urlparse import urlparse


class Test_ExtractUrls(unittest.TestCase):
    def test_empty_string(self):
        from utils import extract_urls
        extracted = extract_urls("")
        self.assertEquals(extracted, [])

    def test_single_link(self):
        from utils import extract_urls
        extracted = extract_urls("http://www.reddit.com?x=f;3")
        self.assertEquals(extracted,
                          [urlparse("http://www.reddit.com?x=f;3")])

    def test_single_link_in_text(self):
        from utils import extract_urls
        extracted = extract_urls("ceci n'est pas une link "
                                 "http://www.reddit.com?x=f;3")
        self.assertEquals(extracted,
                          [urlparse("http://www.reddit.com?x=f;3")])

    def test_many_links_in_text(self):
        from utils import extract_urls
        extracted = extract_urls("ceci n'est pas une link "
                                 "http://www.reddit.com?x=f;3 "
                                 "pero este es uno"
                                 "http://notalink.com/333"
                                )
        self.assertEquals(extracted,
                          [urlparse("http://www.reddit.com?x=f;3"),
                           urlparse("http://notalink.com/333")])

    def test_with_bad_url(self):
        from utils import extract_urls
        extracted = extract_urls("http://]")
        self.assertEquals(extracted, [])


if __name__ == "__main__":
    unittest.main()
