import unittest

from measurement.calculator import (
    assign_4_point_score,
    calculate_points_per_100_sq_yards,
    grade_fabric,
    measure_defect,
)


class TestFabricCalculation(unittest.TestCase):
    def test_4_point_boundaries(self):
        self.assertEqual(assign_4_point_score(3.0), 1)
        self.assertEqual(assign_4_point_score(3.01), 2)
        self.assertEqual(assign_4_point_score(6.0), 2)
        self.assertEqual(assign_4_point_score(6.01), 3)
        self.assertEqual(assign_4_point_score(9.0), 3)
        self.assertEqual(assign_4_point_score(9.01), 4)

    def test_pixel_to_real_measurement(self):
        measurement = measure_defect((10, 10, 110, 60), mm_per_pixel=0.254)
        self.assertEqual(measurement.width_px, 100)
        self.assertEqual(measurement.height_px, 50)
        self.assertAlmostEqual(measurement.width_mm, 25.4)
        self.assertAlmostEqual(measurement.size_inch, 1.0)
        self.assertEqual(measurement.points, 1)

    def test_roll_grading(self):
        self.assertEqual(calculate_points_per_100_sq_yards(117, 202, 110.8), 17.7)
        self.assertEqual(grade_fabric(20), "ACCEPT")
        self.assertEqual(grade_fabric(40), "SECOND QUALITY")
        self.assertEqual(grade_fabric(40.01), "REJECT")


if __name__ == "__main__":
    unittest.main()
