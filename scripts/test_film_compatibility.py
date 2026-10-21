#!/usr/bin/env python3
"""Regression checks for loudness time slots and complete credit-aware muxing."""
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

FILM = Path(__file__).resolve().parents[1] / 'skills/demo-video-builder/scripts/film'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load('film_audio_gate', FILM / 'gates/audio_gate.py')


class MomentaryTests(unittest.TestCase):
    def measure(self, metadata, pcm=None, channels=1, band=None):
        calls = [SimpleNamespace(stdout=metadata, stderr='')]
        if pcm is not None:
            calls += [SimpleNamespace(stdout=json.dumps({'streams': [{'channels': channels}]})),
                      SimpleNamespace(stdout=pcm.astype(np.float32).tobytes())]
        with patch.object(gate.subprocess, 'run', side_effect=calls) as run:
            result = gate.momentary_lufs('fixture.wav', band)
            return result, run.call_args_list

    def test_finite_values_keep_order(self):
        values, calls = self.measure('lavfi.r128.M=-20\nlavfi.r128.M=-25\n')
        self.assertEqual(values.tolist(), [-20, -25])
        self.assertEqual(len(calls), 1)
        self.assertIn('0:a:0', calls[0].args[0])

    def test_negative_infinity_on_silence_keeps_slot(self):
        values, _ = self.measure('lavfi.r128.M=-inf\n', np.zeros(4800))
        self.assertEqual(values.tolist(), [-120])

    def test_negative_infinity_on_non_silence_fails(self):
        with self.assertRaises(RuntimeError):
            self.measure('lavfi.r128.M=-inf\n', np.ones(4800))

    def test_silent_nan_keeps_clock_slot(self):
        values, _ = self.measure('lavfi.r128.M=-20\nlavfi.r128.M=nan\nlavfi.r128.M=-25\n', np.zeros(14400))
        self.assertEqual(values.tolist(), [-20, -120, -25])

    def test_non_silent_nan_fails(self):
        with self.assertRaises(RuntimeError):
            self.measure('lavfi.r128.M=nan\n', np.ones(4800))

    def test_opposite_channels_cannot_cancel_to_silence(self):
        with self.assertRaises(RuntimeError):
            self.measure('lavfi.r128.M=nan\n', np.tile([1, -1], (4800, 1)), channels=2)

    def test_nonfinite_pcm_fails(self):
        with self.assertRaises(RuntimeError):
            self.measure('lavfi.r128.M=nan\n', np.full(4800, np.nan))

    def test_empty_pcm_fails(self):
        with self.assertRaises(RuntimeError):
            self.measure('lavfi.r128.M=nan\n', np.array([]))

    def test_truncated_pcm_window_fails(self):
        with self.assertRaises(RuntimeError):
            self.measure('lavfi.r128.M=nan\nlavfi.r128.M=-20\n', np.zeros(4799))

    def test_silent_partial_final_window_passes(self):
        result, _ = self.measure('lavfi.r128.M=-20\nlavfi.r128.M=-25\nlavfi.r128.M=nan\n', np.zeros(12000))
        self.assertEqual(result.tolist(), [-20, -25, -120])

    def test_non_silent_partial_final_window_fails(self):
        with self.assertRaises(RuntimeError):
            self.measure('lavfi.r128.M=-20\nlavfi.r128.M=-25\nlavfi.r128.M=nan\n', np.ones(12000))

    def test_infinite_measurement_fails_even_on_silence(self):
        with self.assertRaises(RuntimeError):
            self.measure('lavfi.r128.M=inf\n', np.zeros(4800))

    def test_band_is_applied_to_silence_verification(self):
        _, calls = self.measure('lavfi.r128.M=nan\n', np.zeros(4800), band=(250, 3500))
        self.assertIn('acrossover=split=250 3500', ' '.join(calls[-1].args[0]))

    def test_decoder_errors_propagate(self):
        with patch.object(gate.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'ffmpeg')):
            with self.assertRaises(subprocess.CalledProcessError):
                gate.momentary_lufs('broken.wav')


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'vo').mkdir()
        (self.root / 'vo/film_phases.json').write_text(json.dumps({'total': 0.4}))
        shutil.copy2(FILM / 'build_film.py', self.root / 'build_film.py')
        shutil.copy2(FILM.parent / 'credit.py', self.root / 'credit.py')

    def builder(self, **config):
        (self.root / 'film.json').write_text(json.dumps(config))
        return load('fixture_builder', self.root / 'build_film.py')

    def test_lra_defaults_and_validation(self):
        self.assertEqual(self.builder().LUFS_LRA, 11)
        self.assertEqual(self.builder(loudness_range=20).LUFS_LRA, 20)
        for value in (0, 51, 'nan', 'inf', True, False, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.builder(loudness_range=value)

    def test_mux_credit_default_and_explicit_omission(self):
        for enabled in (True, False):
            builder = self.builder(**({} if enabled else {'creator_credit': False}))
            with patch.object(builder, 'run') as run, patch.object(builder, 'tool_versions', return_value=('test', 'test')), patch.object(builder, 'video_frames', return_value=120):
                builder.mux()
            command = run.call_args.args[0]
            self.assertNotIn('-shortest', command)
            self.assertEqual(float(command[command.index('-t') + 1]), 4)
            self.assertEqual('FDE Demo Builder' in command[command.index('-metadata') + 1], enabled)

    def test_mux_rejects_a_dropped_frame(self):
        builder = self.builder()
        with patch.object(builder, 'run'), patch.object(builder, 'tool_versions', return_value=('test', 'test')), patch.object(builder, 'video_frames', side_effect=[120, 119]):
            with self.assertRaisesRegex(SystemExit, 'frame count'):
                builder.mux()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools not installed')
    def test_live_mux_preserves_all_frames(self):
        self.assert_live_mux(.4)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools not installed')
    def test_live_mux_preserves_fractional_clock_frames(self):
        self.assert_live_mux(.417)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools not installed')
    def test_live_default_credit_preserves_final_frames(self):
        self.assert_live_mux(.417, credit=True)

    def assert_live_mux(self, total, credit=False):
        (self.root / 'vo/film_phases.json').write_text(json.dumps({'total': total}))
        builder = self.builder(**({} if credit else {'creator_credit': False}))
        duration = total + builder.TAIL
        size = '640x360' if credit else '160x90'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        f'color=c=green:s={size}:r=30:d={duration}', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', builder.SEG], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        f'sine=frequency=440:sample_rate=48000:duration={duration}', '-ac', '2', builder.MASTER], check=True)
        builder.mux()
        result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                                 '-show_format', '-of', 'json', builder.PRE], check=True, capture_output=True, text=True)
        doc = json.loads(result.stdout)
        video = next(s for s in doc['streams'] if s['codec_type'] == 'video')
        self.assertEqual(int(video['nb_read_frames']), math.ceil(duration * 30))
        self.assertAlmostEqual(float(doc['format']['duration']), duration, delta=1 / 30)
        self.assertEqual('FDE Demo Builder' in doc['format']['tags'].get('comment', ''), credit)
        subprocess.run(['ffmpeg', '-v', 'error', '-i', builder.PRE, '-f', 'null', '-'], check=True)
        builder.credit()
        self.assertEqual(builder.video_frames(builder.FILM), math.ceil(duration * 30))


if __name__ == '__main__':
    if '--require-ffmpeg' in sys.argv:
        sys.argv.remove('--require-ffmpeg')
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            raise SystemExit('FFmpeg and ffprobe are required; refusing to skip the live mux test.')
    unittest.main()
