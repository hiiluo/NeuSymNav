# Household robot geometry

Explicit user implementation request: radius .125m, diameter .25m, height1m.
Small closed change: keep margin .05m, near-ground tolerance .05m, map5cm,
speed/control/TTL/CGvisual/detector and sensor transforms. Main demo only; historical
experiment profiles remain pinned baselines. NewgeometryID cylinder-r125-h1000-v1.

- [x] Main: runtime launches sensor with explicit agentgeometry derived from the same navigation.robot. No independent sensor override.
- [x] Main: optional workeragentgeometry validates positivefiniteclosedschema before importingHabitat; assigns agentradius/height and recomputes simulator-only navmesh with those dimensions; readback/provenance. No navmesh enters mapper/planner and no file saved to source sibling.
- [x] RED/GREEN tests: launcherbinding; badgeometryreject; nativeagent/navmeshfields; guarded narrow corridor permits .125+.05 envelope and rejects too narrow/unknown. Legacy sensorconfigs without geometry remain compatible.
- [x] Update selected11s CGvisual profile only, resync workerhashes in eightmaintainedprofiles as implementationpin maintenance. No silent profilegeometry retrofit.
- [x] IndependentSolHigh review, scoped+fullCPUchecks, localnative sensor/body smoke; native narrowpassage success unproven unless measured. Status/exits/artifacts.

No dependency/model download, training, source siblingwrites, commit/push. No claim householdvacuumtrueheight:1m is the user's explicit requested value. Need newepisode after configurationchange.

Allscopedcheckscomplete; nativepassagetraversal remainsunproven. See resultsreport/evidence.
