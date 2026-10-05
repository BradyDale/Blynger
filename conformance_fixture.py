"""Generate a disposable Blynger publication for the official toolkit adapter."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from core import Studio, new_page, region
from configuration import DEFAULT_SETTINGS


def command(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def publish(studio):
    review = studio.prepare()
    studio.publish(review["signature"])


def generate(destination):
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        site, private, remote = base / "site", base / "private", base / "remote.git"
        site.mkdir(); (site / "images").mkdir()
        (site / "index.html").write_text(new_page("Home", "<h3>Posts</h3>"))
        (site / "openers.html").write_text(new_page("Openers", "<p>No openers yet.</p>"))
        command("git", "init", "-b", "master", cwd=site)
        command("git", "config", "user.name", "Conformance Fixture", cwd=site)
        command("git", "config", "user.email", "fixture@example.invalid", cwd=site)
        command("git", "add", ".", cwd=site); command("git", "commit", "-m", "fixture", cwd=site)
        command("git", "init", "--bare", str(remote), cwd=base)
        command("git", "remote", "add", "website", str(remote), cwd=site)
        command("git", "push", "-u", "website", "master", cwd=site)
        config = copy.deepcopy(DEFAULT_SETTINGS)
        config.update(site_url="https://blynger.example/", site_label="blynger.example",
                      author_name="Blynger Fixture", author_signature="—Fixture",
                      blyg_title="Blynger conformance fixture",
                      feed_description="Disposable protocol evidence",
                      main_pages=["index.html", "openers.html"],
                      non_blyg_pages=["index.html", "openers.html"],
                      local_hostnames=["blynger.example"])
        studio = Studio(site, private, config)

        source = studio.create("Source fragment", body="<p>Local source words.</p>")
        publish(studio)
        source_id = studio.state["ids"][source["name"]]
        studio.pin(source["name"], 1); publish(studio)

        quote = studio.quote_item("local", source_id)
        thread = studio.create("Thread with a source", body=quote["html"] + "<p>Authored response.</p>")
        publish(studio)
        thread_id = studio.state["ids"][thread["name"]]

        generated = studio.create("Generated disclosure", body='<div class="blyg-tk-gen"><p>Generated fixture prose.</p></div>')
        saved = studio.page(generated["name"]); saved["generated"] = [{
            "sources": [], "model": "fixture-model", "at": "2026-10-05T12:00:00Z"
        }]
        studio.save_draft(saved); publish(studio)

        studio.delete_post(source["name"]); publish(studio)
        shutil.copytree(site / "blyg", destination, dirs_exist_ok=True)
        (destination / "scenario.json").write_text(json.dumps({
            "title": "Blynger production-path fixture",
            "origin": studio.origin,
            "labels": {source_id: "withdrawn pinned source", thread_id: "local transclusion"}
        }, indent=2) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: conformance_fixture.py OUTPUT_DIRECTORY")
    generate(sys.argv[1])
