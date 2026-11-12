"""Unit tests. No network, no Claude call: python3 -m unittest discover -s tests"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coeos_memory import capture, hooks_install, llm, rag_sync, search, settings, transcript, vault


class VaultCase(unittest.TestCase):
    """Each test gets an empty vault and no user configuration."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        clean = {k: v for k, v in os.environ.items() if not k.startswith("COEOS_")}
        clean["COEOS_MEMORY_DIR"] = str(Path(self.tmp.name) / "vault")
        patches = [
            mock.patch.dict(os.environ, clean, clear=True),
            mock.patch.object(settings, "CONFIG_FILE", Path(self.tmp.name) / "config.json"),
            mock.patch.object(settings, "_extension_settings_file",
                              lambda: Path(self.tmp.name) / "extension.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        vault.init()

    def write_transcript(self, turns):
        entries = [{"type": role, "message": {"role": role, "content": [
            {"type": "text", "text": text}, {"type": "tool_use", "name": "Bash"}]}}
            for role, text in turns]
        return self.write_entries(entries)

    def write_entries(self, entries):
        path = Path(self.tmp.name) / "session.jsonl"
        with open(path, "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry) + "\n")
            handle.write("not json\n")
        return path

    def article(self, name, title, summary, body="Body.", sources="[]"):
        (vault.knowledge_dir() / f"{name}.md").write_text(
            f"---\ntitle: {title}\nsummary: {summary}\ntags: [alpha, beta]\n"
            f"sources: {sources}\nupdated: 2026-01-02\n---\n\n# {title}\n\n{body}\n",
            encoding="utf-8")


class TestVault(VaultCase):
    def test_entries_round_trip(self):
        when = datetime(2026, 1, 2, 9, 30)
        vault.append_entry("**Context** first", "proj", when)
        vault.append_entry("**Context** second", "other  proj", when.replace(hour=10))
        found = list(vault.entries())
        self.assertEqual([(e[0], e[1], e[2]) for e in found],
                         [("2026-01-02", "09:30", "proj"), ("2026-01-02", "10:30", "other proj")])
        self.assertEqual(found[1][3], "**Context** second")
        self.assertEqual(list(vault.entries(since="2026-01-03")), [])

    def test_recently_logged_ignores_case_and_spacing(self):
        vault.append_entry("A decision  was made\nabout Tailscale.", "proj")
        self.assertTrue(vault.recently_logged("a decision was made about tailscale."))
        self.assertFalse(vault.recently_logged("something else entirely"))

    def test_front_matter_and_index(self):
        self.article("net", "Network", "How the network is laid out.",
                     sources="\n  - 2026-01-01\n  - 2026-01-02")
        article = vault.articles()[0]
        self.assertEqual(article["sources"], ["2026-01-01", "2026-01-02"])
        self.assertEqual(article["tags"], ["alpha", "beta"])
        index = vault.rebuild_index().read_text(encoding="utf-8")
        self.assertIn("| [[net]] | How the network is laid out. | 2026-01-02 |", index)
        self.assertEqual(len(vault.articles()), 1, "the index is not an article")


def user_entry(text, **fields):
    """A human message, as Claude Code writes it, with extra top-level fields."""
    return {"type": "user", "message": {"role": "user", "content": text}, **fields}


def assistant_entry(text, **fields):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": text}, {"type": "tool_use", "name": "Bash"}]}, **fields}


class TestTranscript(VaultCase):
    def kept(self, *entries):
        return transcript.turns(self.write_entries(list(entries)))

    def test_only_spoken_text_is_kept(self):
        path = self.write_transcript([("user", "hello"), ("assistant", "hi"), ("system", "x")])
        self.assertEqual(transcript.turns(path), [("user", "hello"), ("assistant", "hi")])

    def test_api_request_blob_is_not_conversation(self):
        blob = {"type": "api-request-blob", "message": {"role": "user",
                "content": "<system-reminder>Plan mode is on.</system-reminder>"}}
        self.assertEqual(self.kept(blob, user_entry("a real question")),
                         [("user", "a real question")])

    def test_meta_compact_and_sidechain_user_entries_are_dropped(self):
        self.assertEqual(self.kept(
            user_entry("Skill body text", isMeta=True),
            user_entry("This session is being continued from an earlier one", isCompactSummary=True),
            user_entry("delegated question", isSidechain=True),
            user_entry("the human asks"),
        ), [("user", "the human asks")])

    def test_task_notification_is_dropped(self):
        notice = user_entry("A background job has finished.", origin={"kind": "task-notification"})
        self.assertEqual(self.kept(notice), [])

    def test_leading_command_tag_is_dropped(self):
        command = user_entry("<command-name>/clear</command-name>\n<command-message>clear</command-message>")
        self.assertEqual(self.kept(command), [])

    def test_assistant_api_error_and_synthetic_are_dropped(self):
        synthetic = assistant_entry("No response requested.")
        synthetic["message"]["model"] = "<synthetic>"
        self.assertEqual(self.kept(
            assistant_entry("Request failed.", isApiErrorMessage=True),
            synthetic,
            assistant_entry("A real answer."),
        ), [("assistant", "A real answer.")])

    def test_system_reminder_is_stripped_from_a_human_message(self):
        message = user_entry("Please check the router.\n<system-reminder>Plan mode is on.</system-reminder>\nThanks.")
        self.assertEqual(self.kept(message), [("user", "Please check the router.\n\nThanks.")])

    def test_human_origin_is_kept(self):
        self.assertEqual(self.kept(user_entry("typed by a person", origin={"kind": "human"})),
                         [("user", "typed by a person")])

    def test_entry_without_origin_is_kept(self):
        self.assertEqual(self.kept(user_entry("older transcript")), [("user", "older transcript")])

    def test_chunks_keep_every_turn_in_order(self):
        spoken = [("user", "x" * 900)] * 10
        groups = transcript.chunks(spoken, 2000)
        self.assertGreater(len(groups), 1)
        self.assertEqual(sum(len(g) for g in groups), 10)


class TestCapture(VaultCase):
    def test_same_turns_are_never_queued_twice(self):
        turns = [("user", f"question {i}") if i % 2 == 0 else ("assistant", f"answer {i}")
                 for i in range(8)]
        path = self.write_transcript(turns)
        self.assertEqual(capture.enqueue("s1", str(path), "/tmp/proj"), 1)
        self.assertEqual(capture.enqueue("s1", str(path), "/tmp/proj", force=True), 0)
        path = self.write_transcript(turns + [("user", "one more"), ("assistant", "done")])
        self.assertEqual(capture.enqueue("s1", str(path), "/tmp/proj"), 0, "too few new turns")
        self.assertEqual(capture.enqueue("s1", str(path), "/tmp/proj", force=True), 1)
        pieces = sorted((vault.state_dir() / "queue").glob("*.json"))
        last = json.loads(pieces[-1].read_text(encoding="utf-8"))
        self.assertIn("one more", last["text"])
        self.assertNotIn("question 0", last["text"])
        self.assertEqual(last["project"], "proj")

    def test_drain_saves_entries_and_keeps_failures(self):
        path = self.write_transcript([("user", "a"), ("assistant", "b")] * 3)
        capture.enqueue("s1", str(path), "/tmp/proj")
        with mock.patch.object(llm, "ask", side_effect=llm.LLMError("Not logged in")):
            self.assertEqual(capture.drain()["left"], 1)
        self.assertEqual(list(vault.entries()), [], "an error is never written as memory")
        with mock.patch.object(llm, "ask", return_value="**Context** it worked"):
            self.assertEqual(capture.drain()["saved"], 1)
        self.assertEqual(len(list(vault.entries())), 1)
        self.assertEqual(list((vault.state_dir() / "queue").glob("*.json")), [])

    def test_an_answer_that_is_not_an_entry_is_refused(self):
        with mock.patch.object(llm, "ask", return_value="Please run /login"):
            with self.assertRaises(llm.LLMError):
                capture.extract("text")
        with mock.patch.object(llm, "ask", return_value="NOTHING"):
            self.assertEqual(capture.extract("text"), "")

    def test_a_project_can_opt_out(self):
        project = Path(self.tmp.name) / "private"
        project.mkdir()
        self.assertFalse(capture.ignored(str(project)))
        (project / capture.IGNORE_MARKER).touch()
        self.assertTrue(capture.ignored(str(project)))


class TestSearch(VaultCase):
    def test_keywords_rank_and_drop_noise(self):
        self.article("tailscale", "Tailscale remote access", "Subnet routing for the home lab.")
        self.article("bench", "Benchmark merge", "How runs are merged.")
        found = search.search("tailscale subnet")
        self.assertEqual(found["method"], "keywords")
        self.assertEqual([r["article"]["slug"] for r in found["results"]], ["tailscale"])
        self.assertEqual(search.search("unrelated words here")["results"], [])
        self.assertEqual(search.find_article("Tailscale Remote Access")["slug"], "tailscale")


class TestSettings(VaultCase):
    def test_environment_wins_over_files(self):
        settings.write_config({"decision_endpoint": "http://from-config/v1", "decision_model": "m"})
        self.assertEqual(settings.decision()["url"], "http://from-config/v1")
        with mock.patch.dict(os.environ, {"COEOS_DECISION_URL": "http://from-env/v1/"}):
            self.assertEqual(settings.decision()["url"], "http://from-env/v1")
        self.assertEqual(settings.lightrag()["url"], "", "no RAG unless one is named")

    def test_unresolved_placeholder_counts_as_unset(self):
        with mock.patch.dict(os.environ, {"COEOS_DECISION_URL": "${user_config.decision_endpoint}"}):
            self.assertEqual(settings.decision()["url"], "")


class TestRag(VaultCase):
    def test_document_id_matches_lightrag(self):
        self.assertEqual(rag_sync.doc_id_of("  hello\n"), "doc-5d41402abc4b2a76b9719d911017c592")

    def test_pending_lists_only_new_or_changed_files(self):
        self.article("net", "Network", "Summary.", body="word " * 80)
        todo = rag_sync.pending({})
        self.assertEqual(len(todo), 1)
        source, text = todo[0]
        self.assertEqual(rag_sync.pending({source: {"doc_id": rag_sync.doc_id_of(text)}}), [])


class TestHooksInstall(VaultCase):
    def test_install_is_idempotent_and_removable(self):
        path = Path(self.tmp.name) / "settings.json"
        path.write_text(json.dumps({"hooks": {"SessionEnd": [
            {"matcher": "", "hooks": [{"type": "command", "command": "echo other"}]}]}}))
        self.assertEqual(len(hooks_install.apply(path)), 3)
        self.assertEqual(hooks_install.apply(path), [])
        self.assertEqual(len(hooks_install.installed(path)), 3)
        self.assertEqual(len(hooks_install.apply(path, remove=True)), 3)
        left = json.loads(path.read_text())["hooks"]
        self.assertEqual(list(left), ["SessionEnd"], "hooks of other tools are untouched")
        self.assertEqual(left["SessionEnd"][0]["hooks"][0]["command"], "echo other")


if __name__ == "__main__":
    unittest.main()
