"""Ending guard regression checks; native checkpoint checks live separately."""
import unittest
from pcestress import final_cue_matches

class EndingGuard(unittest.TestCase):
    def test_native_prefixed_page(self):
        page='\uf8f2\x05Metal Gear: \uf8f2\x03Right,  Gillian!    <fb01>\x03\uf8f2<0389>'
        self.assertTrue(final_cue_matches(page,670,0x16,'act3_b'))

    def test_wrong_story_track_and_phase(self):
        for module,track,phase in [(638,0x16,'act3_a'),(None,0x16,'act3_b'),(670,0x23,'act3_b'),(670,0x16,'act1_b')]:
            with self.subTest(module=module,track=track,phase=phase):
                self.assertFalse(final_cue_matches('Right, Gillian!',module,track,phase))

    def test_other_dialogue_is_not_the_final_cue(self):
        for page in ['All right, Gillian!','Right, Gillian! Keep going.','Right, Gillian?']:
            self.assertFalse(final_cue_matches(page,670,0x16,'act3_b'))

if __name__=='__main__':unittest.main()
