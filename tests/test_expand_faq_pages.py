import unittest

from crawler.expand_faq_pages import html_to_expanded_text, is_faq_like_control


class ExpandedFaqCrawlerTests(unittest.TestCase):
    def test_is_faq_like_control_detects_numbered_questions(self) -> None:
        self.assertTrue(is_faq_like_control("6. What are the entrance requirements?"))

    def test_is_faq_like_control_detects_offer_keywords(self) -> None:
        self.assertTrue(is_faq_like_control("Accept Offer - Offer Acceptance"))

    def test_html_to_expanded_text_preserves_links(self) -> None:
        html = """
        <html>
          <body>
            <main>
              <h2>What documents are needed?</h2>
              <p>Please click <a href="/visa/documents">here</a> for details.</p>
            </main>
          </body>
        </html>
        """

        text = html_to_expanded_text(html, "https://example.edu.hk/admissions/faq")

        self.assertIn("What documents are needed?", text)
        self.assertIn("here (https://example.edu.hk/visa/documents)", text)

    def test_html_to_expanded_text_does_not_append_same_page_faq_anchor(self) -> None:
        html = """
        <html>
          <body>
            <main>
              <a href="#collapse-24">Where can I obtain the class schedule?</a>
              <div id="collapse-24">Please refer to the programme website.</div>
            </main>
          </body>
        </html>
        """

        text = html_to_expanded_text(html, "https://example.edu.hk/faq")

        self.assertIn("Where can I obtain the class schedule?", text)
        self.assertNotIn("#collapse-24", text)


if __name__ == "__main__":
    unittest.main()
