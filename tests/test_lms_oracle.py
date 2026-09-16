import unittest

from model.reference.lms import (
    LMOTS_SHA256_N32_W4,
    RFC8554_TEST2,
    lmots_public_key,
    lms_public_key,
)


class LmsOracleTests(unittest.TestCase):
    def test_rfc8554_appendix_f_test2_root(self) -> None:
        vector = RFC8554_TEST2
        actual = lms_public_key(
            vector["identifier"],
            vector["seed"],
            vector["height"],
            LMOTS_SHA256_N32_W4,
        )
        self.assertEqual(actual, vector["expected_root"])

    def test_lmots_trace_classes_and_count(self) -> None:
        observed: list[str] = []
        lmots_public_key(
            RFC8554_TEST2["identifier"],
            5,
            RFC8554_TEST2["seed"],
            observe=lambda kind, _inp, _out: observed.append(kind),
        )
        self.assertEqual(observed.count("lmots_prf"), 67)
        self.assertEqual(observed.count("ots_chain"), 67 * 15)
        self.assertEqual(observed.count("ots_compress"), 1)


if __name__ == "__main__":
    unittest.main()
