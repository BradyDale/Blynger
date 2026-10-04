"""Read the site's homepage post list without changing any files."""
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PostList(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.heading = []
        self.in_posts = False
        self.current = None
        self.posts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'h3':
            self.in_heading = True
            self.heading = []
        if self.in_posts and tag == 'a':
            self.current = {'url': dict(attrs).get('href', ''), 'title': ''}

    def handle_data(self, data):
        if self.in_heading:
            self.heading.append(data)
        if self.current is not None:
            self.current['title'] += data

    def handle_endtag(self, tag):
        if tag == 'h3':
            self.in_heading = False
            if ''.join(self.heading).strip() == 'Posts':
                self.in_posts = True
        if tag == 'a' and self.current is not None:
            self.current['title'] = ' '.join(self.current['title'].split())
            self.posts.append(self.current)
            self.current = None
        if tag == 'center' and self.in_posts:
            self.in_posts = False


def main():
    config_path = Path(__file__).resolve().with_name('site.json')
    config = json.loads(config_path.read_text())
    root = (config_path.parent / config['site_root']).resolve()
    parser = PostList()
    parser.feed((root / config['homepage']).read_text())
    for post in parser.posts:
        url = urlsplit(post['url'])
        candidate = (root / unquote(url.path).lstrip('/')).resolve()
        post['local_file_exists'] = (
            not url.scheme and not url.netloc
            and candidate.is_relative_to(root) and candidate.is_file()
        )
    print(json.dumps({'post_count': len(parser.posts), 'posts': parser.posts}, indent=2))


if __name__ == '__main__':
    main()
