import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

from build_boss_spell_text import render  # noqa: E402
from boss_spell_text import text_for  # noqa: E402


class FakeData:
    names = {2: "Soul Fragment"}
    desc = {
        1: "Inflicts $s1 Shadow damage every $t2 sec for $d and increases damage taken by $3s1% "
           "within $A2 yards. $?DIFF16[Mythic only.][] |cFF2959D3|Hspell:2|h[Soul Fragment]|h|r stacks $s3 times.",
        3: "$@spelldesc1",
        4: "Summons $@spellname2 every $s1 sec.",
        5: "Absorbing $s2% of incoming damage, up to $<absorb> total.",
    }
    duration = {1: 6000}
    effects = {1: {1: {"points": 5000.0}, 2: {"period": 1500, "radius": 8.0}, 3: {"points": 4.0}},
               3: {1: {"points": 25.0}}, 4: {1: {"points": 0.0}}, 5: {2: {"points": 30.0}}}


class RenderTests(unittest.TestCase):
    def test_template_filled_where_the_data_is_exact(self):
        self.assertEqual(render(FakeData, 1),
                         "Inflicts Shadow damage every 1.5 sec for 6 sec and increases damage taken by 25% "
                         "within 8 yards. Soul Fragment stacks 4 times.")

    def test_linked_description_and_names(self):
        self.assertTrue(render(FakeData, 3).startswith("Inflicts Shadow damage every 1.5 sec"))
        self.assertEqual(render(FakeData, 4), "Summons Soul Fragment periodically.")

    def test_a_scaled_cap_left_out(self):
        self.assertEqual(render(FakeData, 5), "Absorbing 30% of incoming damage, up to a cap.")

    def test_generated_file(self):
        self.assertIn("frontal cone", text_for(1299684))       # Sever, The Coiled Altar
        self.assertIsNone(text_for(1))


if __name__ == "__main__":
    unittest.main()
