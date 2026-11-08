import pathlib
import urllib.parse
import pytest

from digest import atom, config


@pytest.fixture
def fixture_xml() -> str:
    fixture_path = pathlib.Path(__file__).parent / "fixtures" / "multi_sub.rss"
    return fixture_path.read_text(encoding="utf-8")


@pytest.fixture
def parsed_posts(fixture_xml: str) -> list[atom.Post]:
    return atom.parse(fixture_xml)


def test_parse_fixture_count(parsed_posts: list[atom.Post]):
    assert len(parsed_posts) == 100


def test_first_post_fields(parsed_posts: list[atom.Post]):
    first = parsed_posts[0]
    assert first.id == "t3_1xqxv0m"
    assert first.sub == "FPGA"
    assert first.title.startswith("IMC Hardware Engineering role")
    assert first.body.startswith("Hello ! I am in the process")
    assert "<" not in first.body and ">" not in first.body
    assert len(first.body) <= 600
    assert first.url == "https://www.reddit.com/r/FPGA/comments/1xqxv0m/imc_hardware_engineering_role_interview/"
    assert first.published == "2026-11-08T12:59:14+00:00"


def test_self_post_link_is_none(parsed_posts: list[atom.Post]):
    first = parsed_posts[0]
    assert first.link is None


def test_media_link_is_not_external(parsed_posts: list[atom.Post]):
    for post in parsed_posts:
        if post.link is not None:
            parsed = urllib.parse.urlsplit(post.link)
            host = (parsed.hostname or "").lower()
            assert not host.endswith("redd.it"), f"Post {post.id} link host ends with redd.it: {post.link}"
            assert "/gallery/" not in post.link, f"Post {post.id} link contains /gallery/: {post.link}"


def test_github_links_found(parsed_posts: list[atom.Post]):
    github_posts = [
        post
        for post in parsed_posts
        if post.link and (urllib.parse.urlsplit(post.link).hostname or "").lower() == "github.com"
    ]
    assert len(github_posts) >= 2


def test_body_has_no_table_text(parsed_posts: list[atom.Post]):
    table_post = next(p for p in parsed_posts if p.id == "t3_1xqwv1g")
    assert "submitted by" not in table_post.body
    assert "[link]" not in table_post.body
    assert "[comments]" not in table_post.body
    for p in parsed_posts:
        assert "submitted by" not in p.body
        assert "[link]" not in p.body
        assert "[comments]" not in p.body


def test_feed_config():
    assert len(config.FEEDS) == 13

    expected_subs = {
        # solo
        "LocalLLaMA",
        "LocalLLM",
        "ClaudeCode",
        "ClaudeAI",
        # multi: local AI
        "DeepSeek",
        "Qwen_AI",
        "unsloth",
        # multi: AI agents
        "GeminiAI",
        "google_antigravity",
        "CommandCode",
        "opencodeCLI",
        "PiCodingAgent",
        "claudeskills",
        "claude",
        "Claudeopus",
        # multi: hardware
        "embedded",
        "esp32",
        "IOT",
        "FPGA",
        "PCB",
        "KiCad",
        "CheapYellowDisplay",
        "PrintedCircuitBoard",
        "electronics",
        # multi: game/3D
        "blender",
        "IndieDev",
        "TopologyAI",
        "aigamedev",
        "mocap",
        "threejs",
        "SoloDevelopment",
        "DestroyMyGame",
        # multi: repos
        "SideProject",
        "BestGitHubRepos",
        "coolgithubprojects",
        # multi: AI media / creator
        "StableDiffusion",
        "AI_UGC_Marketing",
        "YT_Faceless",
        "DigitalProductSellers",
        # multi: career
        "softwareengineer",
        "cscareerquestions",
        "EngineeringResumes",
        # multi: security
        "netsecstudents",
        "SecurityCareerAdvice",
        "AskNetsec",
        # multi: learning
        "compsci",
        "Learning",
        "learnpython",
    }

    all_subs = []
    feed_names = []
    for name, subs in config.FEEDS:
        feed_names.append(name)
        for s in subs:
            all_subs.append(s)

    assert len(all_subs) == len(expected_subs)
    assert set(all_subs) == expected_subs
    assert len(all_subs) == len(set(all_subs)), "Duplicate subreddits found in config.FEEDS"

    assert "vozforums" not in all_subs
    assert "announcements" not in all_subs

    expected_feed_names = [
        "LocalLLaMA",
        "LocalLLM",
        "ClaudeCode",
        "ClaudeAI",
        "local-ai",
        "ai-agents",
        "hardware",
        "game-3d",
        "repos",
        "ai-media",
        "career",
        "security",
        "learning",
    ]
    assert feed_names == expected_feed_names

    assert config.WORK.name == "work"
    assert config.DIGESTS.name == "digests"
