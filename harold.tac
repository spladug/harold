import os

import harold


ini_file = os.environ["HAROLD_CONFIGURATION"]
application = harold.make_application(ini_file)
