"""W5 of the active set - one conversation (John, 2026-10-01 13:3x: "is there some type of reset for the steward
conversation in Cave of Wonders and Campaign? That should not be the case"; his call at 18:5x: both - stay awake AND wake
silently).

What read as a reset: the Campaign's steward parked itself after thirty quiet minutes; the wake (his next message, or any
restart) put six system lines into the dialogue ("steward awake - resuming the last session", "Last time: ...", "Plan:",
"Goal:", "Open:") and the resume brief asked the model for a pickup - a recap as its first words. Now the Campaign's own
steward holds one conversation: it takes its idle checkpoint and stays awake; its wake emits nothing and asks for no
pickup. Every other cockpit keeps its sleep and its wake summary (his word of 2026-08-25)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import campaign_say  # noqa: E402
from steward_cockpit import steward_engine as eng_mod  # noqa: E402
from steward_cockpit import steward_routes as routes  # noqa: E402

GREETING = ("resuming the last session", "Last time:", "Plan:", "Goal:", "Open:")


class OneConversationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-w5-")
        self.camp = os.path.join(self.tmp, "Campaign")
        self.other = os.path.join(self.tmp, "effort")
        for d in (self.camp, self.other):
            os.makedirs(d)
            Path(d, "ECGBERHT.md").write_text("# face", encoding="utf-8")
        self._old = (eng_mod.STATE_FILE, routes.CONFIG.get("fake"), campaign_say.campaign_dir, eng_mod.IDLE_SLEEP_SECONDS)
        eng_mod.STATE_FILE = Path(self.tmp) / "state.json"
        routes.CONFIG["fake"] = True
        campaign_say.campaign_dir = lambda: Path(self.camp).resolve()
        self.engines = []

    def tearDown(self):
        for e in self.engines:
            try:
                e.stop()
            except Exception:
                pass
        eng_mod.STATE_FILE, routes.CONFIG["fake"], campaign_say.campaign_dir, eng_mod.IDLE_SLEEP_SECONDS = self._old

    def _parked(self, cdir):
        eng_mod._update_state(cdir, {"session_id": "fake-parked-1", "last_text": "the trusts meeting is set", "last_used": "2026-10-01 12:28"})
        e = eng_mod.Engine(cdir, fake=True)
        self.engines.append(e)
        return e

    def test_only_the_campaign_s_own_steward_holds_one_conversation(self):
        self.assertTrue(eng_mod.Engine(self.camp, fake=True).one_conversation)
        self.assertFalse(eng_mod.Engine(self.other, fake=True).one_conversation)
        self.assertFalse(eng_mod.Engine(self.camp, fake=True, general=True, tid=1).one_conversation, "a workbench terminal in the Campaign folder is not the steward")

    def test_its_wake_puts_no_greeting_in_the_dialogue_and_asks_for_no_pickup(self):
        e = self._parked(self.camp)
        ok, why = e.wake()
        self.assertTrue(ok, why)
        said = " | ".join(str(ev.get("text", "")) for ev in e.events)
        for line in GREETING:
            self.assertNotIn(line, said)
        self.assertEqual(e._resume_prefix, eng_mod.RESUME_QUIET)

    def test_another_cockpit_keeps_its_wake_summary(self):
        e = self._parked(self.other)
        ok, why = e.wake()
        self.assertTrue(ok, why)
        said = " | ".join(str(ev.get("text", "")) for ev in e.events)
        for line in GREETING:
            self.assertIn(line, said)
        self.assertTrue(str(e._resume_prefix).startswith(eng_mod.RESUME_BRIEF))

    def test_the_quiet_brief_rereads_the_record_and_answers_as_the_next_turn(self):
        q, b = eng_mod.RESUME_QUIET, eng_mod.RESUME_BRIEF
        self.assertIn("give John a SHORT pickup", b)
        self.assertNotIn("give John a SHORT pickup", q)
        self.assertNotIn("give a brief pickup", q)
        self.assertIn("no pickup, no recap, no re-introduction", q)
        for kept in ("Silently re-read ECGBERHT.md, roadmap.json, strip.json", ".ecgberht/conversation-log.json", "Continue agreed work under explicit, still-current authorization", "ATTENTION FLAG"):
            self.assertIn(kept, q)

    def test_a_quiet_half_hour_parks_a_cockpit_and_not_the_campaign(self):
        eng_mod.IDLE_SLEEP_SECONDS = 60
        for cdir, parks in ((self.other, True), (self.camp, False)):
            e = self._parked(cdir)
            ok, why = e.wake()
            self.assertTrue(ok, why)
            commits = []
            e._commit_if_dirty = lambda msg, _c=commits: _c.append(msg)
            now = e.woke_at + 30
            self.assertFalse(e._idle_tick(now), "not quiet long enough")
            self.assertTrue(e.alive() and not commits)
            now = e.woke_at + 61
            self.assertEqual(e._idle_tick(now), parks)
            self.assertEqual(e.alive(), not parks)
            if parks:
                self.assertEqual(commits[0], "steward auto-sleep checkpoint")
                self.assertIn("steward asleep after 1 quiet minutes", " | ".join(str(ev.get("text", "")) for ev in e.events))
                continue
            self.assertEqual(commits, ["steward idle checkpoint"])
            self.assertFalse(e._idle_tick(now + 300) or e._idle_tick(now + 3000))
            self.assertEqual(len(commits), 1, "once per quiet spell")
            e.last_say = now + 3000                       # he speaks; a new quiet spell begins
            self.assertFalse(e._idle_tick(now + 3030))
            self.assertFalse(e._idle_tick(now + 3100))
            self.assertEqual(len(commits), 2)
            self.assertNotIn("steward asleep", " | ".join(str(ev.get("text", "")) for ev in e.events))
            self.assertTrue(e.alive())

    def test_work_in_hand_is_never_an_idle_spell(self):
        eng_mod.IDLE_SLEEP_SECONDS = 60
        e = self._parked(self.other)
        ok, why = e.wake()
        self.assertTrue(ok, why)
        e.busy = True
        self.assertFalse(e._idle_tick(e.woke_at + 600))
        e.busy = False
        e._working_bg = lambda: True
        self.assertFalse(e._idle_tick(e.woke_at + 600))
        self.assertTrue(e.alive())


if __name__ == "__main__":
    unittest.main()
