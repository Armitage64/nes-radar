"""Check board.py's pin choice and board guard with fake M5 and machine modules.

board.py imports UIFlow's M5 and MicroPython's machine, which CPython lacks,
so this installs stand-ins before importing it.
"""

import importlib
import sys
import types
import unittest

STICK_S3 = 26
STICKC_PLUS2 = 5


class FakeUART:
    INV_TX = 1
    INV_RX = 2

    def __init__(self, uart_id, **settings):
        self.uart_id = uart_id
        self.settings = settings


def load_board(board_id):
    fake_m5 = types.ModuleType("M5")
    fake_m5.BOARD = types.SimpleNamespace(M5StickS3=STICK_S3, M5StickCPlus2=STICKC_PLUS2)
    fake_m5.getBoard = lambda: board_id
    fake_machine = types.ModuleType("machine")
    fake_machine.UART = FakeUART
    sys.modules["M5"] = fake_m5
    sys.modules["machine"] = fake_machine
    sys.modules.pop("nesradar.board", None)
    return importlib.import_module("nesradar.board")


class BoardTest(unittest.TestCase):
    def tearDown(self):
        for name in ("M5", "machine", "nesradar.board"):
            sys.modules.pop(name, None)

    def test_sticks3_link_pins_avoid_strapping_pins(self):
        board = load_board(STICK_S3)
        uart = board.open_link_uart()
        self.assertEqual(uart.uart_id, 1)
        self.assertEqual((uart.settings["tx"], uart.settings["rx"]), (8, 1))
        self.assertNotIn(0, (uart.settings["tx"], uart.settings["rx"]))
        self.assertEqual(uart.settings["invert"], FakeUART.INV_TX | FakeUART.INV_RX)

    def test_non_inverting_shifter(self):
        board = load_board(STICK_S3)
        self.assertEqual(board.open_link_uart(invert=False).settings["invert"], 0)

    def test_other_boards_are_refused(self):
        board = load_board(STICKC_PLUS2)
        with self.assertRaisesRegex(ValueError, "M5StickS3"):
            board.check_board()
        with self.assertRaises(ValueError):
            board.open_link_uart()


if __name__ == "__main__":
    unittest.main()
