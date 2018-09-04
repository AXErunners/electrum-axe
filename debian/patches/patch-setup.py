Index: Electrum-DASH-3.2.3/setup.py
===================================================================
--- Electrum-DASH-3.2.3.orig/setup.py
+++ Electrum-DASH-3.2.3/setup.py
@@ -77,6 +77,7 @@ setup(
         'electrum_dash',
         'electrum_dash.gui',
         'electrum_dash.gui.qt',
+        'electrum_dash.plugins',
     ] + [('electrum_dash.plugins.'+pkg) for pkg in find_packages('electrum_dash/plugins')],
     package_dir={
         'electrum_dash': 'electrum_dash'
