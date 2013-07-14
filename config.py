import json

__user = {}
__defaults = {}
try:
    fp = open('config.json', 'r+')
    __user = json.load(fp)
    fp.close()
except ValueError:
# could not decode json, file empty?
    pass

try:
    fp = open('defaults.json', 'r+')
    __defaults = json.load(fp)
    fp.close()
except ValueError:
# could not decode json, file empty?
    pass


import atexit
@atexit.register
def __save_config():
    fp = open('config.json', 'r+')
    json.dump(__defaults, fp, indent=4, sort_keys=True)
    fp.close()


__defaults.update(__user)

config = __defaults
get = config.get
