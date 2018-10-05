Index: Electrum-AXE-3.2.3/setup.py
===================================================================
--- Electrum-AXE-3.2.3.orig/setup.py
+++ Electrum-AXE-3.2.3/setup.py
@@ -77,6 +77,7 @@ setup(
         'electrum_axe',
         'electrum_axe.gui',
         'electrum_axe.gui.qt',
+        'electrum_axe.plugins',
     ] + [('electrum_axe.plugins.'+pkg) for pkg in find_packages('electrum_axe/plugins')],
     package_dir={
         'electrum_axe': 'electrum_axe'
