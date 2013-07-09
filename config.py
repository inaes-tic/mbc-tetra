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

__defaults.update(__user)

config = __defaults
get = config.get
