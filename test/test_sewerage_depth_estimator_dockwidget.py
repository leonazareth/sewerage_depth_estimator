# coding=utf-8
"""DockWidget test.

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = 'leonazareth@gmail.com'
__date__ = '2025-08-08'
__copyright__ = 'Copyright 2025, Leonardo Nazareth'

import unittest

from qgis.PyQt.QtGui import QDockWidget

from sewerage_depth_estimator_dockwidget import SewerageDepthEstimatorDockWidget

from utilities import get_qgis_app

QGIS_APP = get_qgis_app()


class SewerageDepthEstimatorDockWidgetTest(unittest.TestCase):
    """Test dockwidget works."""

    def setUp(self):
        """Runs before each test."""
        self.dockwidget = SewerageDepthEstimatorDockWidget(None)

    def tearDown(self):
        """Runs after each test."""
        self.dockwidget = None

    def test_dockwidget_ok(self):
        """Test we can click OK."""
        pass

if __name__ == "__main__":
    suite = unittest.makeSuite(SewerageDepthEstimatorDialogTest)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

