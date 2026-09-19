"""Exact-bytes coverage for the ToUnicode CMap ROT-3 rewrite (xberg issue #1696 fixtures)."""

import unittest

from corpus_tools.wrong_mapping.cmap import rewrite_mapping_body, shift_destination


class RewriteMappingBodyTest(unittest.TestCase):
    def test_should_expand_identity_bfrange_into_rotated_bfchar_pairs(self) -> None:
        result = rewrite_mapping_body("1 beginbfrange\n<0041> <005A> <0041>\nendbfrange\n")
        expected_pairs = "\n".join(
            f"<{code:04X}> <{(code - 0x41 + 3) % 26 + 0x41:04X}>" for code in range(0x41, 0x5A + 1)
        )
        self.assertEqual(result, f"26 beginbfchar\n{expected_pairs}\nendbfchar\n")

    def test_should_leave_digit_destination_unshifted(self) -> None:
        result = rewrite_mapping_body("1 beginbfchar\n<0007> <0030>\nendbfchar\n")
        self.assertEqual(result, "1 beginbfchar\n<0007> <0030>\nendbfchar\n")

    def test_should_leave_digit_destination_from_bfrange_unshifted(self) -> None:
        result = rewrite_mapping_body("1 beginbfrange\n<0007> <0009> <0030>\nendbfrange\n")
        self.assertEqual(
            result,
            "3 beginbfchar\n<0007> <0030>\n<0008> <0031>\n<0009> <0032>\nendbfchar\n",
        )

    def test_should_shift_each_code_unit_of_a_ligature_destination(self) -> None:
        self.assertEqual(shift_destination("00660069"), "0069006C")
        result = rewrite_mapping_body("1 beginbfchar\n<0012> <00660069>\nendbfchar\n")
        self.assertEqual(result, "1 beginbfchar\n<0012> <0069006C>\nendbfchar\n")

    def test_should_map_bfrange_array_destinations_one_to_one_with_no_increment(self) -> None:
        result = rewrite_mapping_body("1 beginbfrange\n<0001> <0002> [<0041> <0043>]\nendbfrange\n")
        self.assertEqual(result, "2 beginbfchar\n<0001> <0044>\n<0002> <0046>\nendbfchar\n")

    def test_should_combine_preexisting_bfchar_with_expanded_bfrange_in_order(self) -> None:
        text = "1 beginbfchar\n<04E9> <0042>\nendbfchar\n1 beginbfrange\n<0001> <0002> <0061>\nendbfrange\n"
        result = rewrite_mapping_body(text)
        self.assertEqual(
            result,
            "3 beginbfchar\n<04E9> <0045>\n<0001> <0064>\n<0002> <0065>\nendbfchar\n",
        )


if __name__ == "__main__":
    unittest.main()
