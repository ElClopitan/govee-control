"""Tests for tray.py."""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import arbiter
from helpers import StateDirMixin


class TestMenuItems(StateDirMixin, unittest.TestCase):
    """Test build_menu() creates the correct menu items."""

    def test_menu_items_in_order(self):
        """Menu has Off, Weather, Game, Music, separator, Quit in that order."""
        import tray

        fake = mock.MagicMock()
        fake.MenuItem.side_effect = lambda *a, **k: types.SimpleNamespace(args=a, kwargs=k)
        fake.Menu.side_effect = lambda *items: list(items)

        menu = tray.build_menu(fake, "config.json")

        # First four items are the mode items
        self.assertEqual(len(menu), 6)  # 4 modes + separator + quit
        self.assertEqual(menu[0].args[0], "Off")
        self.assertEqual(menu[1].args[0], "Weather")
        self.assertEqual(menu[2].args[0], "Game")
        self.assertEqual(menu[3].args[0], "Music")
        # Last item is Quit
        self.assertEqual(menu[5].args[0], "Quit")
        # Mode items have radio=True
        for i in range(4):
            self.assertTrue(menu[i].kwargs.get("radio"))


class TestMenuChecked(StateDirMixin, unittest.TestCase):
    """Test that only the current mode is checked."""

    def test_only_current_mode_checked(self):
        """Only the item for the current mode is checked."""
        import tray

        arbiter.set_mode("game")

        fake = mock.MagicMock()
        fake.MenuItem.side_effect = lambda *a, **k: types.SimpleNamespace(args=a, kwargs=k)
        fake.Menu.side_effect = lambda *items: list(items)

        menu = tray.build_menu(fake, "config.json")

        # Call checked(item) for each mode item
        results = []
        for i in range(4):
            item = types.SimpleNamespace()
            results.append(menu[i].kwargs["checked"](item))

        self.assertEqual(results, [False, False, True, False])


class TestChoose(StateDirMixin, unittest.TestCase):
    """Test choose() switches modes correctly."""

    def test_choose_music_calls_switch(self):
        """Choosing music calls mode.switch('music', None)."""
        import tray

        fake = mock.MagicMock()
        fake.MenuItem.side_effect = lambda *a, **k: types.SimpleNamespace(args=a, kwargs=k)
        fake.Menu.side_effect = lambda *items: list(items)

        menu = tray.build_menu(fake, "config.json")

        icon = mock.MagicMock()
        with mock.patch("mode.switch") as mock_switch:
            with mock.patch.object(tray, "make_icon_image"):
                # Music is the 4th item (index 3)
                menu[3].args[1](icon, None)

        mock_switch.assert_called_once_with("music", None)
        icon.update_menu.assert_called()

    def test_choose_off_loads_config(self):
        """Choosing off loads the config and passes it to switch."""
        import tray

        fake = mock.MagicMock()
        fake.MenuItem.side_effect = lambda *a, **k: types.SimpleNamespace(args=a, kwargs=k)
        fake.Menu.side_effect = lambda *items: list(items)

        menu = tray.build_menu(fake, "config.json")

        icon = mock.MagicMock()
        with mock.patch("govee.load_config", return_value={"devices": []}) as mock_load:
            with mock.patch("mode.switch") as mock_switch:
                with mock.patch.object(tray, "make_icon_image"):
                    # Off is the 1st item (index 0)
                    menu[0].args[1](icon, None)

        mock_load.assert_called_once_with("config.json")
        mock_switch.assert_called_once_with("off", {"devices": []})

    def test_each_item_switches_to_its_own_mode(self):
        """Each menu item switches to its own mode, not the last one."""
        import tray

        fake = mock.MagicMock()
        fake.MenuItem.side_effect = lambda *a, **k: types.SimpleNamespace(args=a, kwargs=k)
        fake.Menu.side_effect = lambda *items: list(items)

        menu = tray.build_menu(fake, "config.json")

        icon = mock.MagicMock()
        with mock.patch("govee.load_config", return_value={"devices": []}):
            with mock.patch("mode.switch") as mock_switch:
                with mock.patch.object(tray, "make_icon_image"):
                    for i in range(4):
                        menu[i].args[1](icon, None)

        calls = [c[0][0] for c in mock_switch.call_args_list]
        self.assertEqual(calls, ["off", "weather", "game", "music"])


class TestChooseErrors(StateDirMixin, unittest.TestCase):
    """Test that choose() logs errors but doesn't raise."""

    def test_switch_error_is_logged_not_raised(self):
        """If mode.switch raises, the error is logged and the icon is still refreshed."""
        import tray

        fake = mock.MagicMock()
        fake.MenuItem.side_effect = lambda *a, **k: types.SimpleNamespace(args=a, kwargs=k)
        fake.Menu.side_effect = lambda *items: list(items)

        menu = tray.build_menu(fake, "config.json")

        icon = mock.MagicMock()
        with mock.patch("mode.switch", side_effect=OSError("boom")):
            with mock.patch.object(tray, "make_icon_image"):
                # Should not raise
                menu[3].args[1](icon, None)

        # Error was logged
        log_file = Path(self.state_dir) / "tray.log"
        self.assertTrue(log_file.exists())
        self.assertIn("boom", log_file.read_text())
        # Icon was still refreshed
        icon.update_menu.assert_called()

    def test_off_with_missing_config_is_logged(self):
        """If govee.load_config raises for 'off', the error is logged and switch is not called."""
        import tray

        fake = mock.MagicMock()
        fake.MenuItem.side_effect = lambda *a, **k: types.SimpleNamespace(args=a, kwargs=k)
        fake.Menu.side_effect = lambda *items: list(items)

        menu = tray.build_menu(fake, "config.json")

        icon = mock.MagicMock()
        with mock.patch("govee.load_config", side_effect=FileNotFoundError("nope")):
            with mock.patch("mode.switch") as mock_switch:
                with mock.patch.object(tray, "make_icon_image"):
                    # Should not raise
                    menu[0].args[1](icon, None)

        # switch was not called
        mock_switch.assert_not_called()
        # Error was logged
        log_file = Path(self.state_dir) / "tray.log"
        self.assertTrue(log_file.exists())
        self.assertIn("nope", log_file.read_text())


class TestQuit(StateDirMixin, unittest.TestCase):
    """Test the Quit menu item."""

    def test_quit_stops_icon_only(self):
        """Quit calls icon.stop() but doesn't change the mode."""
        import tray

        arbiter.set_mode("game")

        fake = mock.MagicMock()
        fake.MenuItem.side_effect = lambda *a, **k: types.SimpleNamespace(args=a, kwargs=k)
        fake.Menu.side_effect = lambda *items: list(items)

        menu = tray.build_menu(fake, "config.json")

        icon = mock.MagicMock()
        with mock.patch("mode.switch") as mock_switch:
            # Quit is the last item (index 5)
            menu[5].args[1](icon, None)

        icon.stop.assert_called_once()
        mock_switch.assert_not_called()
        self.assertEqual(arbiter.get_mode(), "game")


class TestRefresh(StateDirMixin, unittest.TestCase):
    """Test refresh() updates the icon."""

    def test_refresh_sets_title(self):
        """refresh() sets the icon title and image based on the current mode."""
        import tray

        arbiter.set_mode("weather")

        icon = mock.MagicMock()
        with mock.patch.object(tray, "make_icon_image") as mock_img:
            tray.refresh(icon)

        self.assertEqual(icon.title, "Govee: weather")
        mock_img.assert_called_once_with("weather")
        icon.update_menu.assert_called()


class TestPoll(StateDirMixin, unittest.TestCase):
    """Test poll() refreshes until stopped."""

    def test_poll_refreshes_until_stopped(self):
        """poll() calls refresh() on each interval until the stop event is set."""
        import tray

        arbiter.set_mode("game")

        icon = mock.MagicMock()

        # Fake stop event: wait() returns False, False, True
        stop_event = mock.MagicMock()
        call_count = [0]

        def wait_side_effect(interval):
            call_count[0] += 1
            if call_count[0] == 1:
                # First wait: change mode, return False (continue)
                arbiter.set_mode("weather")
                return False
            elif call_count[0] == 2:
                # Second wait: change mode again, return False (continue)
                arbiter.set_mode("music")
                return False
            else:
                # Third wait: return True (stop)
                return True

        stop_event.wait.side_effect = wait_side_effect

        with mock.patch.object(tray, "refresh") as mock_refresh:
            tray.poll(icon, stop_event, interval=0.01)

        # refresh called twice (once for each mode change)
        self.assertEqual(mock_refresh.call_count, 2)


class TestImportWithoutPystray(unittest.TestCase):
    """Test that tray.py can be imported without pystray installed."""

    def test_import_without_pystray(self):
        """import tray works even when pystray is not installed."""
        import tray

        # pystray should not be in sys.modules after importing tray
        self.assertNotIn("pystray", sys.modules)


class TestMainMissingPIL(StateDirMixin, unittest.TestCase):
    """Test that main() handles missing PIL gracefully."""

    def test_pil_missing_exits_with_log(self):
        """When PIL is missing, main() exits 1 and logs the install hint."""
        import tray

        # Remove PIL from sys.modules to simulate it being missing
        saved_pil = sys.modules.pop("PIL", None)
        saved_pil_image = sys.modules.pop("PIL.Image", None)
        saved_pil_imagedraw = sys.modules.pop("PIL.ImageDraw", None)

        # Also remove pystray to trigger the ImportError path
        saved_pystray = sys.modules.pop("pystray", None)

        try:
            with mock.patch.object(tray, "log") as mock_log:
                with mock.patch.object(sys, "stderr"):
                    with mock.patch.object(sys, "argv", ["tray.py"]):
                        # sys.exit raises SystemExit, so we catch it
                        with self.assertRaises(SystemExit) as cm:
                            tray.main()

            # Should have exited with code 1
            self.assertEqual(cm.exception.code, 1)
            # Should have logged the install hint
            mock_log.assert_called_once()
            self.assertIn("requirements-tray.txt", mock_log.call_args[0][0])
        finally:
            # Restore modules
            if saved_pil is not None:
                sys.modules["PIL"] = saved_pil
            if saved_pil_image is not None:
                sys.modules["PIL.Image"] = saved_pil_image
            if saved_pil_imagedraw is not None:
                sys.modules["PIL.ImageDraw"] = saved_pil_imagedraw
            if saved_pystray is not None:
                sys.modules["pystray"] = saved_pystray


class TestChooseRefreshError(StateDirMixin, unittest.TestCase):
    """Test that choose() handles refresh errors gracefully."""

    def test_refresh_error_logged_not_raised(self):
        """If refresh raises inside choose, the error is logged and not raised."""
        import tray

        fake = mock.MagicMock()
        fake.MenuItem.side_effect = lambda *a, **k: types.SimpleNamespace(args=a, kwargs=k)
        fake.Menu.side_effect = lambda *items: list(items)

        menu = tray.build_menu(fake, "config.json")

        icon = mock.MagicMock()
        with mock.patch("mode.switch"):
            with mock.patch.object(tray, "refresh", side_effect=RuntimeError("refresh boom")):
                # Should not raise
                menu[3].args[1](icon, None)

        # Error was logged
        log_file = Path(self.state_dir) / "tray.log"
        self.assertTrue(log_file.exists())
        self.assertIn("refresh failed", log_file.read_text())
        self.assertIn("refresh boom", log_file.read_text())


class TestPollUnchangedMode(StateDirMixin, unittest.TestCase):
    """Test that poll() only refreshes when the mode changes."""

    def test_poll_unchanged_mode_no_refresh(self):
        """poll() does not call refresh when the mode hasn't changed."""
        import tray

        arbiter.set_mode("game")

        icon = mock.MagicMock()

        # Fake stop event: wait() returns False, False, True
        stop_event = mock.MagicMock()
        stop_event.wait.side_effect = [False, False, True]

        with mock.patch.object(tray, "refresh") as mock_refresh:
            tray.poll(icon, stop_event, interval=0.01)

        # refresh should not be called because mode never changed
        mock_refresh.assert_not_called()

    def test_poll_changed_mode_refreshes_once(self):
        """poll() calls refresh once when the mode changes."""
        import tray

        arbiter.set_mode("game")

        icon = mock.MagicMock()

        # Fake stop event: wait() returns False, False, True
        stop_event = mock.MagicMock()
        call_count = [0]

        def wait_side_effect(interval):
            call_count[0] += 1
            if call_count[0] == 1:
                # First wait: change mode, return False (continue)
                arbiter.set_mode("weather")
                return False
            elif call_count[0] == 2:
                # Second wait: return False (continue)
                return False
            else:
                # Third wait: return True (stop)
                return True

        stop_event.wait.side_effect = wait_side_effect

        with mock.patch.object(tray, "refresh") as mock_refresh:
            tray.poll(icon, stop_event, interval=0.01)

        # refresh should be called once when mode changed
        mock_refresh.assert_called_once()


if __name__ == "__main__":
    unittest.main()
