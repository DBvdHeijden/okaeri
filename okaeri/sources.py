"""Curated default sources. All URLs checked to return items (2026-10-11)."""

from dataclasses import replace

from okaeri.models import Source


def _arxiv(cat: str, name: str) -> Source:
    # The arXiv RSS feeds are empty on weekends; the API always returns the latest.
    return Source(
        f"arxiv-{cat.lower()}", name, "paper",
        "https://export.arxiv.org/api/query?search_query=cat:"
        f"{cat}&sortBy=submittedDate&sortOrder=descending&max_results=30",
        f"arxiv.org/list/{cat}",
        refresh_minutes=180,
    )


def _substack(id: str, name: str, host: str) -> Source:
    return Source(id, name, "blog", f"https://{host}/feed", host)


SOURCES: list[Source] = [
    # Papers
    Source("hf-papers", "HF Daily Papers", "paper", "https://huggingface.co/api/daily_papers",
           "huggingface.co/papers", fetcher="hf_papers", refresh_minutes=120),
    _arxiv("cs.LG", "arXiv cs.LG"),
    _arxiv("cs.CL", "arXiv cs.CL"),
    _arxiv("cs.AI", "arXiv cs.AI"),
    Source("nature", "Nature", "paper", "https://www.nature.com/nature.rss", "nature.com", refresh_minutes=180),
    Source("science", "Science", "paper",
           "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science", "science.org",
           refresh_minutes=180),
    Source("pnas", "PNAS", "paper", "https://www.pnas.org/action/showFeed?type=etoc&feed=rss&jc=pnas",
           "pnas.org", refresh_minutes=180),
    Source("natmachintell", "Nature Machine Intelligence", "paper",
           "https://www.nature.com/natmachintell.rss", "nature.com/natmachintell", refresh_minutes=180),
    Source("aps-physics", "APS Physics", "paper", "https://feeds.aps.org/rss/recent/physics.xml",
           "physics.aps.org", refresh_minutes=180),
    # Blogs
    Source("simonw", "Simon Willison", "blog", "https://simonwillison.net/atom/everything/", "simonwillison.net"),
    Source("jvns", "Julia Evans", "blog", "https://jvns.ca/atom.xml", "jvns.ca"),
    Source("lilianweng", "Lilian Weng", "blog", "https://lilianweng.github.io/index.xml", "lilianweng.github.io"),
    Source("danluu", "Dan Luu", "blog", "https://danluu.com/atom.xml", "danluu.com"),
    Source("fowler", "Martin Fowler", "blog", "https://martinfowler.com/feed.atom", "martinfowler.com"),
    Source("eugeneyan", "Eugene Yan", "blog", "https://eugeneyan.com/rss/", "eugeneyan.com"),
    _substack("raschka", "Sebastian Raschka", "magazine.sebastianraschka.com"),
    _substack("importai", "Import AI", "importai.substack.com"),
    _substack("interconnects", "Interconnects", "www.interconnects.ai"),
    Source("karpathy", "Andrej Karpathy", "blog", "https://karpathy.bearblog.dev/feed/", "karpathy.bearblog.dev"),
    _substack("gwern", "Gwern", "gwern.substack.com"),
    Source("tao", "Terence Tao", "blog", "https://terrytao.wordpress.com/feed/", "terrytao.wordpress.com"),
    Source("aaronson", "Scott Aaronson", "blog", "https://scottaaronson.blog/?feed=rss2", "scottaaronson.blog"),
    Source("argmin", "arg min", "blog", "https://www.argmin.net/feed", "argmin.net"),
    Source("bair", "BAIR", "blog", "https://bair.berkeley.edu/blog/feed.xml", "bair.berkeley.edu/blog"),
    Source("google-research", "Google Research", "blog", "https://research.google/blog/rss/", "research.google/blog"),
    Source("deepmind", "Google DeepMind", "blog", "https://deepmind.google/blog/rss.xml", "deepmind.google/blog"),
    Source("openai", "OpenAI", "blog", "https://openai.com/news/rss.xml", "openai.com/news"),
    Source("hf-blog", "Hugging Face", "blog", "https://huggingface.co/blog/feed.xml", "huggingface.co/blog"),
    Source("cloudflare", "Cloudflare", "blog", "https://blog.cloudflare.com/rss/", "blog.cloudflare.com"),
    # Forums
    Source("hn", "Hacker News", "forum", "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30",
           "news.ycombinator.com", fetcher="hn_algolia", refresh_minutes=5),
    Source("lobsters", "Lobsters", "forum", "https://lobste.rs/hottest.json", "lobste.rs",
           fetcher="lobsters_json", refresh_minutes=10),
    Source("r-ml", "r/MachineLearning", "forum", "https://www.reddit.com/r/MachineLearning/.rss",
           "reddit.com/r/MachineLearning", refresh_minutes=60),  # Reddit rate-limits (429) quickly
    Source("tildes-comp", "Tildes ~comp", "forum", "https://tildes.net/~comp/topics.rss", "tildes.net/~comp",
           refresh_minutes=15),
    Source("alignmentforum", "Alignment Forum", "forum", "https://www.alignmentforum.org/graphql",
           "alignmentforum.org", fetcher="lw_graphql", refresh_minutes=30),
    # Science & tech journalism
    Source("quanta", "Quanta", "scitech", "https://www.quantamagazine.org/feed/", "quantamagazine.org", refresh_minutes=20),
    Source("science-news", "Science News", "scitech", "https://www.science.org/rss/news_current.xml",
           "science.org/news", refresh_minutes=20),
    Source("ars", "Ars Technica", "scitech", "https://feeds.arstechnica.com/arstechnica/index", "arstechnica.com",
           refresh_minutes=15),
    Source("lwn", "LWN.net", "scitech", "https://lwn.net/headlines/rss", "lwn.net", refresh_minutes=20),
    Source("spectrum", "IEEE Spectrum", "scitech", "https://spectrum.ieee.org/feeds/feed.rss", "spectrum.ieee.org", refresh_minutes=20),
    Source("physorg", "Phys.org", "scitech", "https://phys.org/rss-feed/", "phys.org", refresh_minutes=15),
    Source("bbc-science", "BBC Science", "scitech", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
           "bbc.com/news/science_and_environment", refresh_minutes=20),
    Source("bbc-tech", "BBC Technology", "scitech", "https://feeds.bbci.co.uk/news/technology/rss.xml",
           "bbc.com/news/technology", refresh_minutes=20),
    Source("nos-tech", "NOS Tech", "scitech", "https://feeds.nos.nl/nosnieuwstech", "nos.nl/nieuws/tech",
           refresh_minutes=20),
    Source("tweakers", "Tweakers", "scitech", "https://tweakers.net/feeds/nieuws.xml", "tweakers.net",
           refresh_minutes=15),
    # General news (free to read, no subscription)
    Source("nos", "NOS Nieuws", "news", "https://feeds.nos.nl/nosnieuwsalgemeen", "nos.nl", refresh_minutes=15),
    Source("nu", "NU.nl", "news", "https://www.nu.nl/rss/Algemeen", "nu.nl", refresh_minutes=15),
    Source("bbc-world", "BBC World", "news", "https://feeds.bbci.co.uk/news/world/rss.xml", "bbc.com/news/world",
           refresh_minutes=15),
    Source("guardian-world", "The Guardian World", "news", "https://www.theguardian.com/world/rss",
           "theguardian.com/world", refresh_minutes=15),
    Source("aljazeera", "Al Jazeera", "news", "https://www.aljazeera.com/xml/rss/all.xml", "aljazeera.com",
           refresh_minutes=15),
    Source("dw", "DW", "news", "https://rss.dw.com/rdf/rss-en-all", "dw.com/en", refresh_minutes=15),
    Source("npr", "NPR News", "news", "https://feeds.npr.org/1001/rss.xml", "npr.org", refresh_minutes=15),
]

DESCRIPTIONS = {
    # Papers
    "hf-papers": "Papers hand-picked and upvoted by the Hugging Face community each day.",
    "arxiv-cs.lg": "The newest machine learning preprints on arXiv.",
    "arxiv-cs.cl": "The newest preprints on language models and NLP.",
    "arxiv-cs.ai": "The newest preprints across artificial intelligence.",
    "nature": "Research articles and news from Nature's weekly issues.",
    "science": "Research and commentary from the journal Science's table of contents.",
    "pnas": "Peer-reviewed research across the sciences from PNAS.",
    "natmachintell": "Nature's journal for machine learning and AI research.",
    "aps-physics": "Accessible write-ups of notable physics papers from the American Physical Society.",
    # Blogs
    "simonw": "Daily notes on LLMs, tools and building with AI, from Datasette's creator.",
    "jvns": "Friendly, curious deep dives into how computers and command-line tools work.",
    "lilianweng": "Long, thorough survey posts on machine learning topics.",
    "danluu": "Data-heavy essays on software, hardware and how tech companies work.",
    "fowler": "Software architecture, refactoring and engineering practice.",
    "eugeneyan": "Practical write-ups on recommender systems, LLM products and applied ML.",
    "raschka": "Clear explanations of LLM research and training techniques.",
    "importai": "Jack Clark's weekly newsletter on AI research and policy.",
    "interconnects": "Nathan Lambert on open models, RLHF and the AI industry.",
    "karpathy": "Occasional essays on deep learning and AI from Andrej Karpathy.",
    "gwern": "Long-form essays and monthly roundups on AI, statistics and psychology.",
    "tao": "Mathematics research, expository notes and occasional AI experiments from Terence Tao.",
    "aaronson": "Quantum computing, complexity theory and AI from Scott Aaronson.",
    "argmin": "Ben Recht on optimisation, machine learning and the philosophy of science.",
    "bair": "Research highlights from the Berkeley AI Research lab.",
    "google-research": "Announcements and explainers from Google Research teams.",
    "deepmind": "Research and model announcements from Google DeepMind.",
    "openai": "Research, product and policy updates from OpenAI.",
    "hf-blog": "Tutorials, releases and research from the Hugging Face team.",
    "cloudflare": "Detailed engineering posts on networking, security and the web.",
    # Forums
    "hn": "The front page of Hacker News, voted on by programmers and founders.",
    "lobsters": "A smaller, invite-only link aggregator focused on computing.",
    "r-ml": "Papers, projects and discussion from the machine learning subreddit.",
    "tildes-comp": "Calm, thoughtful discussion of computing on Tildes.",
    "alignmentforum": "Technical discussion of AI alignment research.",
    # Science & tech journalism
    "quanta": "Beautifully written stories on maths, physics, biology and computer science.",
    "science-news": "Science magazine's daily news coverage across research fields.",
    "ars": "In-depth tech, science and policy news.",
    "lwn": "Authoritative news on the Linux kernel and free software.",
    "spectrum": "IEEE's magazine on engineering, robotics and emerging technology.",
    "physorg": "A fast-moving wire of science and research press releases.",
    "bbc-science": "BBC News coverage of science, health and the environment.",
    "bbc-tech": "BBC News coverage of technology and the tech industry.",
    "nos-tech": "Dutch public broadcaster NOS on technology, in Dutch.",
    "tweakers": "Dutch tech news, in Dutch.",
    # General news
    "nos": "The Dutch public broadcaster's main news feed, in Dutch.",
    "nu": "The Netherlands' most-read news site, fast and broad, in Dutch.",
    "bbc-world": "International news from the BBC.",
    "guardian-world": "The Guardian's world news, free to read.",
    "aljazeera": "Global news with strong coverage of the Middle East and Global South.",
    "dw": "Germany's international broadcaster, with a European perspective, in English.",
    "npr": "Top stories from US public radio.",
}

SOURCES = [replace(s, description=DESCRIPTIONS[s.id]) for s in SOURCES]
BY_ID: dict[str, Source] = {s.id: s for s in SOURCES}
