import ctypes, json, sys
lib = ctypes.CDLL(sys.argv[1])
lib.nsn_room_stability_version.restype = ctypes.c_char_p
assert lib.nsn_room_stability_version().decode() == 'neusymnav-room-stability-v1'
lib.nsn_room_stability_configure.argtypes = [ctypes.c_char_p]
assert lib.nsn_room_stability_configure(json.dumps({'enabled': True, 'confirm_observations': 3, 'candidate_tolerance_m': .02, 'numerical_epsilon_m': .0001}).encode()) == 0
assert lib.nsn_room_stability_configure(b'{"enabled":"true"}') != 0
