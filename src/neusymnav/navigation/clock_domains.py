"""Clock domains accepted by the live navigation safety layer.

``host_monotonic:<boot id>``  real host time (realtime demo).
``sim_lockstep:<run id>``     simulated time of the deterministic ObjectNav
                              evaluation runner (objectnav/sim_worker_entry.py):
                              time advances only with simulator work, so every
                              freshness/horizon rule is measured in sim time.
``replay:<...>``              recorded data, offline replay only (never live).

The rules applied to a command are identical in the two live domains; only the
source of ``now`` differs. Wall-time pacing is meaningless in simulated time.
"""

HOST_MONOTONIC = 'host_monotonic:'
SIM_LOCKSTEP = 'sim_lockstep:'
REPLAY = 'replay:'


def is_live(clock_domain: str) -> bool:
    return type(clock_domain) is str and clock_domain.startswith((HOST_MONOTONIC, SIM_LOCKSTEP))


def is_simulated(clock_domain: str) -> bool:
    return type(clock_domain) is str and clock_domain.startswith(SIM_LOCKSTEP)
