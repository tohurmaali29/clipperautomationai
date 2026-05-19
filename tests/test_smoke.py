import unittest

import main
from services.subtitle_service import generate_subtitles


class SmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_check(self):
        response = await main.health_check()
        self.assertEqual(response["status"], "healthy")
        self.assertEqual(response["service"], "AI Video Clipper Backend")

    async def test_analyze_returns_normalized_clip_shape(self):
        request = main.AnalyzeRequest(
            url="https://youtu.be/dQw4w9WgXcQ",
            mode="viral",
            duration=30,
        )

        response = await main.analyze(request)

        self.assertEqual(response["status"], "success")
        self.assertTrue(response["clips"])
        first_clip = response["clips"][0]
        self.assertIn("title", first_clip)
        self.assertIn("headline", first_clip)
        self.assertIn("score", first_clip)
        self.assertIn("start_time", first_clip)
        self.assertIn("end_time", first_clip)
        self.assertIn("metadata", response)
        self.assertIn("pipeline", response)
        self.assertIn("demo_mode", response["metadata"])
        self.assertIn("cache", response["metadata"])
        self.assertIn("cache_hit", response["pipeline"]["transcript"])
        self.assertIn("cache_hit", response["pipeline"]["analysis"])

    def test_generate_subtitles_returns_ass_payload(self):
        result = generate_subtitles("Halo dunia ini adalah transcript pendek", "id")
        self.assertIn("[Script Info]", result)
        self.assertIn("[Events]", result)
        self.assertIn("Dialogue:", result)


if __name__ == "__main__":
    unittest.main()
