from poll_rss import fetch_url, poll_all_feeds
from pprint import pprint

articles = poll_all_feeds()
content = fetch_url(articles[1]["article_url"])

pprint(articles[1])
pprint(content)
